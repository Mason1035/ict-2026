/*
 * SPDX-FileCopyrightText: 2015-2025 Espressif Systems (Shanghai) CO LTD
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdbool.h>
#include <stddef.h>
#include <inttypes.h>
#include <sys/param.h>
#include "esp_log.h"
#include "esp_heap_caps.h"
#include "driver/gpio.h"
#include "sd_protocol_defs.h"
#include "driver/sdspi_host.h"
#include "sdspi_private.h"
#include "sdspi_crc.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "soc/soc_memory_layout.h"
#include "esp_private/esp_cache_private.h"

/// Max number of transactions in flight (used in start_command_write_blocks)
#define SDSPI_TRANSACTION_COUNT 4
#define SDSPI_MOSI_IDLE_VAL     0xff    //!< Data value which causes MOSI to stay high
#define GPIO_UNUSED 0xff                //!< Flag indicating that CD/WP is unused
/// Size of the buffer returned by get_block_buf
#define SDSPI_BLOCK_BUF_SIZE    (SDSPI_MAX_DATA_LEN + 4)
/// Maximum number of dummy bytes between the request and response (minimum is 1)
#define SDSPI_RESPONSE_MAX_DELAY  8
/// Fast-spin window before yielding 1 RTOS tick during extended busy/token waits
#define SDSPI_POLL_FAST_SPIN_US   2000

/**
 * @brief Structure containing run time configuration for a single SD slot
 *
 * The slot info is referenced to by an sdspi_dev_handle_t (alias int). The handle may be the raw
 * pointer to the slot info itself (force converted to, new API in IDFv4.2), or the index of the
 * s_slot array (deprecated API). Returning the raw pointer to the caller instead of storing it
 * locally can save some static memory.
 */
typedef struct {
    spi_host_device_t   host_id; //!< SPI host id.
    spi_device_handle_t spi_handle; //!< SPI device handle, used for transactions
    uint8_t* block_buf;
    /// semaphore of gpio interrupt
    SemaphoreHandle_t   semphr_int;
    uint16_t duty_cycle_pos;  ///< Duty cycle of positive clock, in 1/256th increments (128 = 50%/50% duty). Setting this to 0 (=not setting it) is equivalent to setting this to 128.
    uint8_t gpio_cs;            //!< CS GPIO, or GPIO_UNUSED
    uint8_t gpio_cd;            //!< Card detect GPIO, or GPIO_UNUSED
    uint8_t gpio_wp;            //!< Write protect GPIO, or GPIO_UNUSED
    uint8_t gpio_int;           //!< Write protect GPIO, or GPIO_UNUSED
    uint8_t poll_busy_start_command_timeout;  ///< Timeout value in milliseconds the driver will be waiting for MISO to be high before sending commands.
    /// GPIO write protect polarity.
    /// 0 means "active low", i.e. card is protected when the GPIO is low;
    /// 1 means "active high", i.e. card is protected when GPIO is high.
    uint8_t gpio_wp_polarity : 1;
    /// Set to 1 if the higher layer has asked the card to enable CRC checks
    uint8_t data_crc_enabled : 1;
    /// Intermediate buffer used when application buffer is not in DMA memory;
    /// allocated on demand, SDSPI_BLOCK_BUF_SIZE bytes long. May be zero.
} slot_info_t;

// Reserved for old API to be back-compatible
static slot_info_t *s_slots[SOC_SPI_PERIPH_NUM] = {};
static const char *TAG = "sdspi_host";
static sdspi_diag_stats_t s_diag = {0};

static const bool use_polling = true;
static const bool no_use_polling = true;

/// Functions to send out different kinds of commands
static esp_err_t start_command_read_blocks(slot_info_t *slot, sdspi_hw_cmd_t *cmd,
                                           uint8_t *data, uint32_t rx_length, bool need_stop_command);

static esp_err_t start_command_write_blocks(slot_info_t *slot, sdspi_hw_cmd_t *cmd,
                                            const uint8_t *data, uint32_t tx_length, bool multi_block, bool stop_trans);

static esp_err_t start_command_default(slot_info_t *slot, int flags, sdspi_hw_cmd_t *cmd);

static esp_err_t shift_cmd_response(sdspi_hw_cmd_t *cmd, int sent_bytes);

typedef struct {
    uint32_t zero_bytes;
    uint32_t non_ff_bytes;
    uint32_t elapsed_us;
    uint8_t first_rx;
    uint8_t last_rx;
    bool has_rx;
} sdspi_busy_info_t;

static esp_err_t poll_busy(slot_info_t *slot, int timeout_ms, bool polling);
static esp_err_t poll_busy_ex(slot_info_t *slot, int timeout_ms, bool polling, uint8_t *out_last_rx);
static esp_err_t poll_busy_detail(slot_info_t *slot, int timeout_ms, bool polling, sdspi_busy_info_t *out_info);

void sdspi_host_get_diag_stats(sdspi_diag_stats_t *out_stats)
{
    if (out_stats) {
        *out_stats = s_diag;
    }
}

void sdspi_host_reset_diag_stats(void)
{
    memset(&s_diag, 0, sizeof(s_diag));
}

static void record_read_fail(int cmd, uint32_t arg, uint32_t blocks, uint32_t blk_idx,
                             const char *stage, uint8_t r1, const uint8_t *rx, size_t rx_len,
                             int64_t read_start_us, esp_err_t rc)
{
    const int64_t now_us = esp_timer_get_time();
    const uint32_t elapsed_us = now_us >= read_start_us ? (uint32_t)(now_us - read_start_us) : 0;
    s_diag.last_fail_cmd = cmd;
    s_diag.last_fail_arg = arg;
    s_diag.last_fail_blocks = blocks;
    s_diag.last_fail_blk_idx = blk_idx;
    s_diag.last_fail_r1 = r1;
    memset(s_diag.last_fail_rx, 0xff, sizeof(s_diag.last_fail_rx));
    const size_t copy_len = (rx && rx_len > 0) ? MIN(rx_len, sizeof(s_diag.last_fail_rx)) : 0;
    if (copy_len > 0) {
        memcpy(s_diag.last_fail_rx, rx, copy_len);
    }
    s_diag.last_fail_rx_len = (uint8_t)copy_len;
    s_diag.last_fail_elapsed_us = elapsed_us;
    s_diag.last_fail_rc = rc;
    snprintf(s_diag.last_fail_stage, sizeof(s_diag.last_fail_stage), "%s", stage ? stage : "UNKNOWN");
    const uint8_t *w = s_diag.last_fail_rx;
    ESP_LOGW(TAG, "SD_READ_FAIL cmd=%d arg=0x%08" PRIx32 " blocks=%" PRIu32 " blk=%" PRIu32
             " stage=%s r1=0x%02x rx=%02x%02x%02x%02x%02x%02x%02x%02x rx_len=%u elapsed_us=%" PRIu32 " rc=0x%x",
             cmd, arg, blocks, blk_idx, s_diag.last_fail_stage, r1,
             w[0], w[1], w[2], w[3], w[4], w[5], w[6], w[7],
             (unsigned)copy_len, elapsed_us, rc);
}

static esp_err_t r1_read_err_to_esp_err(uint8_t r1)
{
    if (r1 & SD_SPI_R1_NO_RESPONSE) {
        return ESP_ERR_TIMEOUT;
    }
    if (r1 & SD_SPI_R1_CMD_CRC_ERR) {
        return ESP_ERR_INVALID_CRC;
    }
    if (r1 & SD_SPI_R1_ILLEGAL_CMD) {
        return ESP_ERR_NOT_SUPPORTED;
    }
    if (r1 & SD_SPI_R1_ADDR_ERR) {
        return ESP_ERR_INVALID_ARG;
    }
    if (r1 & SD_SPI_R1_PARAM_ERR) {
        return ESP_ERR_INVALID_SIZE;
    }
    if ((r1 & SD_SPI_R1_IDLE_STATE) || (r1 & SD_SPI_R1_ERASE_RST) || (r1 & SD_SPI_R1_ERASE_SEQ_ERR)) {
        return ESP_ERR_INVALID_STATE;
    }
    return ESP_ERR_INVALID_RESPONSE;
}

/// A few helper functions

/// Map handle to pointer of slot information
static slot_info_t* get_slot_info(sdspi_dev_handle_t handle)
{
    if ((uint32_t) handle < SOC_SPI_PERIPH_NUM) {
        return s_slots[handle];
    } else {
        return (slot_info_t *) handle;
    }
}

/// Store slot information (if possible) and return corresponding handle
static sdspi_dev_handle_t store_slot_info(slot_info_t *slot)
{
    /*
     * To be back-compatible, the first device of each bus will always be stored locally, and
     * referenced to by the handle `host_id`, otherwise the new API return the raw pointer to the
     * slot info as the handle, to save some static memory.
     */
    if (s_slots[slot->host_id] == NULL) {
        s_slots[slot->host_id] = slot;
        return slot->host_id;
    } else {
        return (sdspi_dev_handle_t)slot;
    }
}

/// Get the slot info for a specific handle, and remove the local reference (if exist).
static slot_info_t* remove_slot_info(sdspi_dev_handle_t handle)
{
    if ((uint32_t) handle < SOC_SPI_PERIPH_NUM) {
        slot_info_t* slot = s_slots[handle];
        s_slots[handle] = NULL;
        return slot;
    } else {
        return (slot_info_t *) handle;
    }
}

/// Set CS high for given slot
static void cs_high(slot_info_t *slot)
{
    if (slot->gpio_cs != GPIO_UNUSED) {
        gpio_set_level(slot->gpio_cs, 1);
    }
}

/// Set CS low for given slot
static void cs_low(slot_info_t *slot)
{
    if (slot->gpio_cs != GPIO_UNUSED) {
        gpio_set_level(slot->gpio_cs, 0);
    }
}

/// Return true if WP pin is configured and is set as per its polarity
static bool card_write_protected(slot_info_t *slot)
{
    if (slot->gpio_wp == GPIO_UNUSED) {
        return false;
    }
    return gpio_get_level(slot->gpio_wp) == (slot->gpio_wp_polarity ? 1 : 0);
}

/// Return true if CD pin is configured and is high
static bool card_missing(slot_info_t *slot)
{
    if (slot->gpio_cd == GPIO_UNUSED) {
        return false;
    }
    return gpio_get_level(slot->gpio_cd) == 1;
}

/// Get pointer to a block of DMA memory, allocate if necessary.
/// This is used if the application provided buffer is not in DMA capable memory.
static esp_err_t get_block_buf(slot_info_t *slot, uint8_t **out_buf)
{
    if (slot->block_buf == NULL) {
        slot->block_buf = heap_caps_malloc(SDSPI_BLOCK_BUF_SIZE, MALLOC_CAP_DMA);
        if (slot->block_buf == NULL) {
            return ESP_ERR_NO_MEM;
        }
    }
    *out_buf = slot->block_buf;
    return ESP_OK;
}

/// Clock out one byte (CS has to be high) to make the card release MISO
/// (clocking one bit would work as well, but that triggers a bug in SPI DMA)
static void release_bus(slot_info_t *slot)
{
    spi_transaction_t t = {
        .flags = SPI_TRANS_USE_RXDATA | SPI_TRANS_USE_TXDATA,
        .length = 8,
        .tx_data = {0xff}
    };
    spi_device_polling_transmit(slot->spi_handle, &t);
    // don't care if this failed
}

/// Clock out 80 cycles (10 bytes) before GO_IDLE command
static void go_idle_clockout(slot_info_t *slot)
{
    //actually we need 10, declare 12 to meet requirement of RXDMA
    uint8_t data[12];
    memset(data, 0xff, sizeof(data));
    spi_transaction_t t = {
        .length = 10 * 8,
        .tx_buffer = data,
        .rx_buffer = data,
    };
    spi_device_polling_transmit(slot->spi_handle, &t);
    // don't care if this failed
}

/**
 * (Re)Configure SPI device. Used to change clock speed.
 * @param slot Pointer to the slot to be configured
 * @param clock_speed_hz  clock speed, Hz
 * @return ESP_OK on success
 */
static esp_err_t configure_spi_dev(slot_info_t *slot, int clock_speed_hz)
{
    if (slot->spi_handle) {
        // Reinitializing
        spi_bus_remove_device(slot->spi_handle);
        slot->spi_handle = NULL;
    }
    spi_device_interface_config_t devcfg = {
        .clock_speed_hz = clock_speed_hz,
        .mode = 0,
        // For SD cards, CS must stay low during the whole read/write operation,
        // rather than a single SPI transaction.
        .spics_io_num = GPIO_NUM_NC,
        .queue_size = SDSPI_TRANSACTION_COUNT,
        .duty_cycle_pos = slot->duty_cycle_pos,
    };
    return spi_bus_add_device(slot->host_id, &devcfg, &slot->spi_handle);
}

esp_err_t sdspi_host_init(void)
{
    return ESP_OK;
}

static esp_err_t deinit_slot(slot_info_t *slot)
{
    esp_err_t err = ESP_OK;
    if (slot->spi_handle) {
        spi_bus_remove_device(slot->spi_handle);
        slot->spi_handle = NULL;
        free(slot->block_buf);
        slot->block_buf = NULL;
    }

    uint64_t pin_bit_mask = 0;
    if (slot->gpio_cs != GPIO_UNUSED) {
        pin_bit_mask |= BIT64(slot->gpio_cs);
    }
    if (slot->gpio_cd != GPIO_UNUSED) {
        pin_bit_mask |= BIT64(slot->gpio_cd);
    }
    if (slot->gpio_wp != GPIO_UNUSED) {
        pin_bit_mask |= BIT64(slot->gpio_wp);
    }
    if (slot->gpio_int != GPIO_UNUSED) {
        pin_bit_mask |= BIT64(slot->gpio_int);
        gpio_intr_disable(slot->gpio_int);
        gpio_isr_handler_remove(slot->gpio_int);
    }
    gpio_config_t config = {
        .pin_bit_mask = pin_bit_mask,
        .mode = GPIO_MODE_INPUT,
        .intr_type = GPIO_INTR_DISABLE,
    };
    if (pin_bit_mask != 0) {
        gpio_config(&config);
    }

    if (slot->semphr_int) {
        vSemaphoreDelete(slot->semphr_int);
        slot->semphr_int = NULL;
    }
    free(slot);
    return err;
}

esp_err_t sdspi_host_remove_device(sdspi_dev_handle_t handle)
{
    //Get the slot info and remove the reference in the static memory (if used)
    slot_info_t* slot = remove_slot_info(handle);
    if (slot == NULL) {
        return ESP_ERR_INVALID_ARG;
    }

    deinit_slot(slot);
    return ESP_OK;
}

//only the slots locally stored can be deinit in this function.
esp_err_t sdspi_host_deinit(void)
{
    for (size_t i = 0; i < sizeof(s_slots) / sizeof(s_slots[0]); ++i) {
        slot_info_t* slot = remove_slot_info(i);
        //slot isn't used, skip
        if (slot == NULL) {
            continue;
        }

        deinit_slot(slot);
    }
    return ESP_OK;
}

esp_err_t sdspi_host_set_card_clk(sdspi_dev_handle_t handle, uint32_t freq_khz)
{
    slot_info_t *slot = get_slot_info(handle);
    if (slot == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    ESP_LOGD(TAG, "Setting card clock to %"PRIu32" kHz", freq_khz);
    return configure_spi_dev(slot, freq_khz * 1000);
}

esp_err_t sdspi_host_get_real_freq(sdspi_dev_handle_t handle, int* real_freq_khz)
{
    slot_info_t *slot = get_slot_info(handle);
    if (slot == NULL) {
        return ESP_ERR_INVALID_ARG;
    }

    return spi_device_get_actual_freq(slot->spi_handle, real_freq_khz);
}

static void gpio_intr(void* arg)
{
    BaseType_t awoken = pdFALSE;
    slot_info_t* slot = (slot_info_t*)arg;
    xSemaphoreGiveFromISR(slot->semphr_int, &awoken);
    gpio_intr_disable(slot->gpio_int);
    if (awoken) {
        portYIELD_FROM_ISR();
    }
}

static inline int wait_for_miso_to_poll_busy_timeout_ms(int8_t wait_for_miso)
{
    static int default_timeout = 40; // default timeout in ms
    int ret;
    switch (wait_for_miso) {
    case -1:
        ret = 0; // no waiting
        break;
    case 0:
        ret = default_timeout;
        break;
    case 1 ... 127:
        ret = (int) wait_for_miso; // timeout in ms
        break;
    default:
        ret = default_timeout; // unsupported values (from -128 to -2), use default
        break;
    }
    assert(ret >= 0);
    return ret;
}

esp_err_t sdspi_host_init_device(const sdspi_device_config_t* slot_config, sdspi_dev_handle_t* out_handle)
{
    ESP_LOGD(TAG, "%s: SPI%d cs=%d cd=%d wp=%d wp_polarity:%d",
             __func__, slot_config->host_id + 1, slot_config->gpio_cs,
             slot_config->gpio_cd, slot_config->gpio_wp, slot_config->gpio_wp_polarity);

    slot_info_t* slot = (slot_info_t*)malloc(sizeof(slot_info_t));
    if (slot == NULL) {
        return ESP_ERR_NO_MEM;
    }
    *slot = (slot_info_t) {
        .host_id = slot_config->host_id,
        .gpio_cs = slot_config->gpio_cs,
        .duty_cycle_pos = slot_config->duty_cycle_pos,
        .poll_busy_start_command_timeout = wait_for_miso_to_poll_busy_timeout_ms(slot_config->wait_for_miso),
    };

    // Attach the SD card to the SPI bus
    esp_err_t ret = configure_spi_dev(slot, SDMMC_FREQ_PROBING * 1000);
    if (ret != ESP_OK) {
        ESP_LOGD(TAG, "spi_bus_add_device failed with rc=0x%x", ret);
        goto cleanup;
    }

    // Configure CS pin
    gpio_config_t io_conf = {
        .intr_type = GPIO_INTR_DISABLE,
        .mode = GPIO_MODE_OUTPUT,
        .pin_bit_mask = 1ULL << slot_config->gpio_cs,
    };
    if (slot_config->gpio_cs != SDSPI_SLOT_NO_CS) {
        slot->gpio_cs = slot_config->gpio_cs;
    } else {
        slot->gpio_cs = GPIO_UNUSED;
    }

    if (slot->gpio_cs != GPIO_UNUSED) {
        ret = gpio_config(&io_conf);
        if (ret != ESP_OK) {
            ESP_LOGD(TAG, "gpio_config (CS) failed with rc=0x%x", ret);
            goto cleanup;
        }
        cs_high(slot);
    }

    // Configure CD and WP pins
    io_conf = (gpio_config_t) {
        .intr_type = GPIO_INTR_DISABLE,
        .mode = GPIO_MODE_INPUT,
        .pin_bit_mask = 0,
        .pull_up_en = true
    };
    if (slot_config->gpio_cd != SDSPI_SLOT_NO_CD) {
        io_conf.pin_bit_mask |= (1ULL << slot_config->gpio_cd);
        slot->gpio_cd = slot_config->gpio_cd;
    } else {
        slot->gpio_cd = GPIO_UNUSED;
    }

    if (slot_config->gpio_wp != SDSPI_SLOT_NO_WP) {
        io_conf.pin_bit_mask |= (1ULL << slot_config->gpio_wp);
        slot->gpio_wp = slot_config->gpio_wp;
        slot->gpio_wp_polarity = slot_config->gpio_wp_polarity;
        if (slot->gpio_wp_polarity) {
            io_conf.pull_down_en = true;
            io_conf.pull_up_en = false;
        }
    } else {
        slot->gpio_wp = GPIO_UNUSED;
    }

    if (io_conf.pin_bit_mask != 0) {
        ret = gpio_config(&io_conf);
        if (ret != ESP_OK) {
            ESP_LOGD(TAG, "gpio_config (CD/WP) failed with rc=0x%x", ret);
            goto cleanup;
        }
    }

    if (slot_config->gpio_int != SDSPI_SLOT_NO_INT) {
        slot->gpio_int = slot_config->gpio_int;
        io_conf = (gpio_config_t) {
            .intr_type = GPIO_INTR_LOW_LEVEL,
            .mode = GPIO_MODE_INPUT,
            .pull_up_en = true,
            .pin_bit_mask = (1ULL << slot_config->gpio_int),
        };
        ret = gpio_config(&io_conf);
        if (ret != ESP_OK) {
            ESP_LOGE(TAG, "gpio_config (interrupt) failed with rc=0x%x", ret);
            goto cleanup;
        }

        slot->semphr_int = xSemaphoreCreateBinary();
        if (slot->semphr_int == NULL) {
            ret = ESP_ERR_NO_MEM;
            goto cleanup;
        }

        gpio_intr_disable(slot->gpio_int);
        // 1. the interrupt is better to be disabled before the ISR is registered
        // 2. the semaphore MUST be initialized before the ISR is registered
        // 3. the gpio_int member should be filled before the ISR is registered
        ret = gpio_isr_handler_add(slot->gpio_int, &gpio_intr, slot);
        if (ret != ESP_OK) {
            ESP_LOGE(TAG, "gpio_isr_handle_add failed with rc=0x%x", ret);
            goto cleanup;
        }
    } else {
        slot->gpio_int = GPIO_UNUSED;
    }
    //Initialization finished, store the store information if possible
    //Then return corresponding handle
    *out_handle = store_slot_info(slot);
    return ESP_OK;
cleanup:
    if (slot->semphr_int) {
        vSemaphoreDelete(slot->semphr_int);
        slot->semphr_int = NULL;
    }
    if (slot->spi_handle) {
        spi_bus_remove_device(slot->spi_handle);
        slot->spi_handle = NULL;
    }
    free(slot);
    return ret;
}

esp_err_t sdspi_host_start_command(sdspi_dev_handle_t handle, sdspi_hw_cmd_t *cmd, void *data,
                                   uint32_t data_size, int flags)
{
    slot_info_t *slot = get_slot_info(handle);
    if (slot == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    if (card_missing(slot)) {
        return ESP_ERR_NOT_FOUND;
    }
    // save some parts of cmd, as its contents will be overwritten
    int cmd_index = cmd->cmd_index;
    uint32_t cmd_arg;
    memcpy(&cmd_arg, cmd->arguments, sizeof(cmd_arg));
    cmd_arg = __builtin_bswap32(cmd_arg);
    ESP_LOGV(TAG, "%s: slot=%i, CMD%d, arg=0x%08"PRIx32" flags=0x%x, data=%p, data_size=%"PRIu32" crc=0x%02x",
             __func__, handle, cmd_index, cmd_arg, flags, data, data_size, cmd->crc7);

    esp_err_t ret;
    ret = spi_device_acquire_bus(slot->spi_handle, portMAX_DELAY);
    if (ret != ESP_OK) {
        ESP_LOGD(TAG, "%s: spi_device_acquire_bus returned 0x%x", __func__, ret);
        return ret;
    }

    ret = poll_busy(slot, slot->poll_busy_start_command_timeout, true);
    const esp_err_t preselect_rc = ret;
    if (ret != ESP_OK && ret != ESP_ERR_TIMEOUT) {
        ESP_LOGD(TAG, "%s: poll_busy error=0x%x", __func__, ret);
        cs_high(slot);
        release_bus(slot);
        spi_device_release_bus(slot->spi_handle);
        return ret;
    }

    // For CMD0, clock out 80 cycles to help the card enter idle state,
    // *before* CS is asserted.
    if (cmd_index == MMC_GO_IDLE_STATE) {
        go_idle_clockout(slot);
    }
    const int64_t cmd_start_us = esp_timer_get_time();
    // actual transaction
    ret = ESP_OK;

    cs_low(slot);
    if (cmd_index != MMC_GO_IDLE_STATE && cmd_index != MMC_STOP_TRANSMISSION) {
        sdspi_busy_info_t post_cs = {0};
        const int busy_timeout_ms = cmd->timeout_ms > 0 ? cmd->timeout_ms : 500;
        const esp_err_t post_cs_rc = poll_busy_detail(slot, busy_timeout_ms, true, &post_cs);
        if (post_cs.non_ff_bytes > 0) {
            ++s_diag.post_cs_busy_waits;
            s_diag.post_cs_busy_bytes += post_cs.non_ff_bytes;
        }
        if (post_cs_rc != ESP_OK) {
            ++s_diag.post_cs_busy_err;
            record_read_fail(cmd_index, cmd_arg, data_size / SDSPI_MAX_DATA_LEN, 0,
                             "POST_CS_BUSY", 0xff, &post_cs.last_rx, 1, cmd_start_us, post_cs_rc);
            ret = post_cs_rc;
        }
    }
    if (ret == ESP_OK) {
        if (flags & SDSPI_CMD_FLAG_DATA) {
            const bool multi_block = flags & SDSPI_CMD_FLAG_MULTI_BLK;
            //send stop transmission token only when multi-block write and non-SDIO mode
            const bool stop_transmission = multi_block && !(flags & SDSPI_CMD_FLAG_RSP_R5);
            if (flags & SDSPI_CMD_FLAG_WRITE) {
                ret = start_command_write_blocks(slot, cmd, data, data_size, multi_block, stop_transmission);
            } else {
                ret = start_command_read_blocks(slot, cmd, data, data_size, stop_transmission);
            }
        } else {
            ret = start_command_default(slot, flags, cmd);
        }
    }
    cs_high(slot);

    release_bus(slot);
    spi_device_release_bus(slot->spi_handle);

    if (cmd_index == MMC_READ_BLOCK_SINGLE) {
        if (ret == ESP_OK) {
            ++s_diag.cmd17_ok;
            s_diag.sectors_read_single += data_size / SDSPI_MAX_DATA_LEN;
        } else {
            ++s_diag.cmd17_err;
        }
    } else if (cmd_index == MMC_READ_BLOCK_MULTIPLE) {
        if (ret == ESP_OK) {
            ++s_diag.cmd18_ok;
            s_diag.sectors_read_multi += data_size / SDSPI_MAX_DATA_LEN;
        } else {
            ++s_diag.cmd18_err;
        }
    } else if (cmd_index == MMC_SEND_STATUS) {
        if (ret == ESP_OK) {
            ++s_diag.cmd13_ok;
        } else {
            ++s_diag.cmd13_err;
        }
    } else if (cmd_index == MMC_WRITE_BLOCK_SINGLE) {
        if (ret == ESP_OK) {
            ++s_diag.cmd24_ok;
        } else {
            ++s_diag.cmd24_err;
        }
    } else if (cmd_index == MMC_WRITE_BLOCK_MULTIPLE) {
        if (ret == ESP_OK) {
            ++s_diag.cmd25_ok;
        } else {
            ++s_diag.cmd25_err;
        }
    }

    if (ret != ESP_OK) {
        if (cmd_index == MMC_SEND_STATUS || cmd_index == MMC_WRITE_BLOCK_SINGLE || cmd_index == MMC_WRITE_BLOCK_MULTIPLE) {
            ESP_LOGW(TAG, "SD_CMD_FAIL cmd=%d arg=0x%08" PRIx32 " len=%" PRIu32 " preselect_rc=0x%x rc=0x%x"
                     " last_wr=(cmd=%u arg=0x%08" PRIx32 " r1=0x%02x drsp=0x%02x b0=%" PRIu32 " bus=%" PRIu32 " rx=%02x->%02x)",
                     cmd_index, cmd_arg, data_size, preselect_rc, ret,
                     (unsigned)s_diag.last_write_cmd, s_diag.last_write_arg,
                     (unsigned)s_diag.last_write_r1, (unsigned)s_diag.last_write_data_rsp,
                     s_diag.write_busy_zeros_last, s_diag.write_busy_last_us,
                     (unsigned)s_diag.last_write_first_rx, (unsigned)s_diag.last_write_last_rx);
        } else {
            ESP_LOGW(TAG, "SD_CMD_FAIL cmd=%d arg=0x%08" PRIx32 " len=%" PRIu32 " preselect_rc=0x%x rc=0x%x",
                     cmd_index, cmd_arg, data_size, preselect_rc, ret);
        }
    } else {
        // Update internal state when some commands are sent successfully
        if (cmd_index == SD_CRC_ON_OFF) {
            slot->data_crc_enabled = (uint8_t) cmd_arg;
            ESP_LOGD(TAG, "data CRC set=%d", slot->data_crc_enabled);
        }
    }
    return ret;
}

static esp_err_t start_command_default(slot_info_t *slot, int flags, sdspi_hw_cmd_t *cmd)
{
    const unsigned tx_opcode = cmd->cmd_index; // RX overwrites the six transmitted command bytes.
    size_t cmd_size = SDSPI_CMD_R1_SIZE;
    if ((flags & SDSPI_CMD_FLAG_RSP_R1) ||
            (flags & SDSPI_CMD_FLAG_NORSP) ||
            (flags & SDSPI_CMD_FLAG_RSP_R1B)) {
        cmd_size = SDSPI_CMD_R1_SIZE;
    } else if (flags & SDSPI_CMD_FLAG_RSP_R2) {
        cmd_size = SDSPI_CMD_R2_SIZE;
    } else if (flags & SDSPI_CMD_FLAG_RSP_R3) {
        cmd_size = SDSPI_CMD_R3_SIZE;
    } else if (flags & SDSPI_CMD_FLAG_RSP_R4) {
        cmd_size = SDSPI_CMD_R4_SIZE;
    } else if (flags & SDSPI_CMD_FLAG_RSP_R5) {
        cmd_size = SDSPI_CMD_R5_SIZE;
    } else if (flags & SDSPI_CMD_FLAG_RSP_R7) {
        cmd_size = SDSPI_CMD_R7_SIZE;
    }
    //add extra clocks to avoid polling
    cmd_size += (SDSPI_NCR_MAX_SIZE - SDSPI_NCR_MIN_SIZE);
    spi_transaction_t t = {
        .flags = 0,
        .length = cmd_size * 8,
        .tx_buffer = cmd,
        .rx_buffer = cmd,
    };
    esp_err_t ret = spi_device_polling_transmit(slot->spi_handle, &t);
    if (ret != ESP_OK) {
        ESP_LOGW(TAG, "SD_SPI_TRANSFER_FAIL cmd=%u rc=0x%x", tx_opcode, ret);
        return ret;
    }
    // For CMD12 the byte immediately after CRC is stuff. It occupies ncr
    // (offset 6); shift_cmd_response already starts at r1 (offset 7).
    _Static_assert(offsetof(sdspi_hw_cmd_t, r1) == SDSPI_CMD_SIZE + 1, "SPI response layout");
    if (tx_opcode != MMC_STOP_TRANSMISSION && cmd->cmd_index == MMC_STOP_TRANSMISSION && !(cmd->r1 & SD_SPI_R1_NO_RESPONSE)) {
        static bool recorded;
        if (!recorded) {
            recorded = true;
            ESP_LOGW(TAG, "SD_RX_OPCODE_ALIAS cmd=%u first_r1=%02x", tx_opcode, cmd->r1);
        }
    }
    if (flags & SDSPI_CMD_FLAG_NORSP) {
        /* no (correct) response expected from the card, so skip polling loop */
        ESP_LOGV(TAG, "%s: ignoring response byte", __func__);
        cmd->r1 = 0x00;
    }
    // we have sent and received bytes with enough length.
    // now shift the response to match the offset of sdspi_hw_cmd_t
    ret = shift_cmd_response(cmd, cmd_size);
    if (ret != ESP_OK) {
        const uint8_t *w = (const uint8_t *)cmd + offsetof(sdspi_hw_cmd_t, r1);
        ESP_LOGW(TAG, "SD_R1_MISSING cmd=%u rx=%02x%02x%02x%02x%02x%02x%02x%02x",
                 tx_opcode, w[0], w[1], w[2], w[3], w[4], w[5], w[6], w[7]);
        return ESP_ERR_TIMEOUT;
    }

    if (flags & SDSPI_CMD_FLAG_RSP_R1B) {
        uint8_t last_rx = 0xff;
        ret = poll_busy_ex(slot, cmd->timeout_ms, no_use_polling, &last_rx);
        if (ret != ESP_OK) {
            ESP_LOGW(TAG, "SD_R1B_BUSY_TIMEOUT cmd=%u r1=0x%02x last_rx=0x%02x rc=0x%x",
                     tx_opcode, cmd->r1, last_rx, ret);
            return ret;
        }
    }

    return ESP_OK;
}

// Wait until MISO returns idle 0xff (two consecutive 0xff bytes)
static esp_err_t poll_busy_detail(slot_info_t *slot, int timeout_ms, bool polling, sdspi_busy_info_t *out_info)
{
    sdspi_busy_info_t info = {
        .zero_bytes = 0,
        .non_ff_bytes = 0,
        .elapsed_us = 0,
        .first_rx = 0xff,
        .last_rx = 0xff,
        .has_rx = false,
    };
    if (timeout_ms < 0) {
        if (out_info) {
            *out_info = info;
        }
        return ESP_ERR_INVALID_ARG;
    } else if (timeout_ms == 0) {
        if (out_info) {
            *out_info = info;
        }
        return ESP_OK;
    }
    uint8_t t_rx;
    spi_transaction_t t = {
        .tx_buffer = &t_rx,
        .flags = SPI_TRANS_USE_RXDATA,  //data stored in rx_data
        .length = 8,
    };
    esp_err_t ret;

    const int64_t t_start = esp_timer_get_time();
    const int64_t t_end = t_start + (int64_t)timeout_ms * 1000;
    int ready_count = 0;
    do {
        t_rx = SDSPI_MOSI_IDLE_VAL;
        t.rx_data[0] = 0;
        if (polling) {
            ret = spi_device_polling_transmit(slot->spi_handle, &t);
        } else {
            ret = spi_device_transmit(slot->spi_handle, &t);
        }
        if (ret != ESP_OK) {
            const int64_t now_us = esp_timer_get_time();
            info.elapsed_us = now_us >= t_start ? (uint32_t)(now_us - t_start) : 0;
            if (out_info) {
                *out_info = info;
            }
            return ret;
        }
        const uint8_t rx = t.rx_data[0];
        if (!info.has_rx) {
            info.first_rx = rx;
            info.has_rx = true;
        }
        info.last_rx = rx;
        if (rx == 0xff) {
            if (++ready_count == 2) {
                const int64_t now_us = esp_timer_get_time();
                info.elapsed_us = now_us >= t_start ? (uint32_t)(now_us - t_start) : 0;
                if (out_info) {
                    *out_info = info;
                }
                return ESP_OK;
            }
        } else {
            ready_count = 0;
            ++info.non_ff_bytes;
            if (rx == 0x00) {
                ++info.zero_bytes;
            }
            const int64_t now_us = esp_timer_get_time();
            if (now_us >= t_end) {
                break;
            }
            if ((now_us - t_start) >= SDSPI_POLL_FAST_SPIN_US) {
                vTaskDelay(1);
            }
        }
    } while (esp_timer_get_time() < t_end);
    const int64_t now_us = esp_timer_get_time();
    info.elapsed_us = now_us >= t_start ? (uint32_t)(now_us - t_start) : 0;
    if (out_info) {
        *out_info = info;
    }
    ESP_LOGD(TAG, "%s: timeout", __func__);
    return ESP_ERR_TIMEOUT;
}

static esp_err_t poll_busy_ex(slot_info_t *slot, int timeout_ms, bool polling, uint8_t *out_last_rx)
{
    sdspi_busy_info_t info;
    const esp_err_t ret = poll_busy_detail(slot, timeout_ms, polling, &info);
    if (out_last_rx) {
        *out_last_rx = info.last_rx;
    }
    return ret;
}

static esp_err_t poll_busy(slot_info_t *slot, int timeout_ms, bool polling)
{
    return poll_busy_detail(slot, timeout_ms, polling, NULL);
}

// Wait for data token, reading 8 bytes at a time.
// If the token is found, write all subsequent bytes to extra_ptr,
// and store the number of bytes written to extra_size.
static esp_err_t poll_data_token_ex(slot_info_t *slot, uint8_t *extra_ptr, size_t *extra_size, int timeout_ms, uint8_t last_rx[8])
{
    uint8_t t_rx[8];
    if (last_rx) {
        memset(last_rx, 0xff, 8);
    }
    spi_transaction_t t = {
        .tx_buffer = &t_rx,
        .rx_buffer = &t_rx,
        .length = sizeof(t_rx) * 8,
    };
    esp_err_t ret;
    const int64_t t_start = esp_timer_get_time();
    const int64_t t_end = t_start + (int64_t)timeout_ms * 1000;
    do {
        memset(t_rx, SDSPI_MOSI_IDLE_VAL, sizeof(t_rx));
        ret = spi_device_polling_transmit(slot->spi_handle, &t);
        if (ret != ESP_OK) {
            return ret;
        }
        if (last_rx) {
            memcpy(last_rx, t_rx, sizeof(t_rx));
        }
        bool found = false;
        for (size_t byte_idx = 0; byte_idx < sizeof(t_rx); byte_idx++) {
            uint8_t rd_data = t_rx[byte_idx];
            if (rd_data == TOKEN_BLOCK_START) {
                found = true;
                memcpy(extra_ptr, t_rx + byte_idx + 1, sizeof(t_rx) - byte_idx - 1);
                *extra_size = sizeof(t_rx) - byte_idx - 1;
                break;
            }
            if (rd_data != 0xff && rd_data != 0) {
                ESP_LOGD(TAG, "%s: received 0x%02x while waiting for data",
                         __func__, rd_data);
                return ESP_ERR_INVALID_RESPONSE;
            }
        }
        if (found) {
            return ESP_OK;
        }
        const int64_t now_us = esp_timer_get_time();
        if (now_us >= t_end) {
            break;
        }
        if ((now_us - t_start) >= SDSPI_POLL_FAST_SPIN_US) {
            vTaskDelay(1);
        }
    } while (esp_timer_get_time() < t_end);
    ESP_LOGD(TAG, "%s: timeout", __func__);
    return ESP_ERR_TIMEOUT;
}

// the r1 respond could appear 1-8 clocks after the command token is sent
// this function search for r1 in the buffer after 1 clocks to max 8 clocks
// then shift the data after R1, to match the definition of sdspi_hw_cmd_t.
static esp_err_t shift_cmd_response(sdspi_hw_cmd_t* cmd, int sent_bytes)
{
    uint8_t* pr1 = (uint8_t*)cmd + offsetof(sdspi_hw_cmd_t, r1);
    int ncr_cnt = 1;
    while (true) {
        if ((*pr1 & SD_SPI_R1_NO_RESPONSE) == 0) {
            break;
        }
        pr1++;
        if (++ncr_cnt > 8) {
            return ESP_ERR_NOT_FOUND;
        }
    }

    int copy_bytes = sent_bytes - SDSPI_CMD_SIZE - ncr_cnt;
    if (copy_bytes > 0) {
        memmove((uint8_t*)cmd + offsetof(sdspi_hw_cmd_t, r1), pr1, copy_bytes);
    }

    return ESP_OK;
}

/**
 * Receiving one or more blocks of data happens as follows:
 * 1. send command + receive r1 response (SDSPI_CMD_R1_SIZE bytes total)
 * 2. keep receiving bytes until TOKEN_BLOCK_START is encountered (this may
 *    take a while, depending on card's read speed)
 * 3. receive up to SDSPI_MAX_DATA_LEN = 512 bytes of actual data
 * 4. receive 2 bytes of CRC
 * 5. for multi block transfers, go to step 2
 *
 * These steps can be done separately, but that leads to a less than optimal
 * performance on large transfers because of delays between each step.
 * For example, if steps 3 and 4 are separate SPI transactions queued one after
 * another, there will be ~16 microseconds of dead time between end of step 3
 * and the beginning of step 4. A delay between two blocking SPI transactions
 * in step 2 is even higher (~60 microseconds).
 *
 * To improve read performance the following sequence is adopted:
 * 1. Do the first transfer: command + r1 response + 8 extra bytes.
 *    Set pre_scan_data_ptr to point to the 8 extra bytes, and set
 *    pre_scan_data_size to 8.
 * 2. Search pre_scan_data_size bytes for TOKEN_BLOCK_START.
 *    If found, the rest of the bytes contain part of the actual data.
 *    Store pointer to and size of that extra data as extra_data_{ptr,size}.
 *    If not found, fall back to polling for TOKEN_BLOCK_START, 8 bytes at a
 *    time (in poll_data_token_ex function). Deal with extra data in the same way,
 *    copying into a stack buffer before reusing slot->block_buf.
 * 3. Receive the remaining 512 - extra_data_size bytes, plus 4 extra bytes
 *    (i.e. 516 - extra_data_size). Of the 4 extra bytes, first two will capture
 *    the CRC value, and the other two will capture 0xff 0xfe sequence
 *    indicating the start of the next block. Actual scanning is done by
 *    setting pre_scan_data_ptr to point to these last 2 bytes, and setting
 *    pre_scan_data_size = 2, then going to step 2 to receive the next block.
 *    When the final block is being received, the number of extra bytes is 2
 *    (only for CRC), because we don't need to wait for start token of the
 *    next block, and some cards are getting confused by these two extra bytes.
 *
 * With this approach the delay between blocks of a multi-block transfer is
 * ~95 microseconds, out of which 35 microseconds are spend doing the CRC check.
 * Further speedup is possible by pipelining transfers and CRC checks, at an
 * expense of one extra temporary buffer.
 */
static esp_err_t start_command_read_blocks(slot_info_t *slot, sdspi_hw_cmd_t *cmd,
                                           uint8_t *data, uint32_t rx_length, bool need_stop_command)
{
    const int tx_opcode = cmd->cmd_index;
    uint32_t tx_arg = 0;
    memcpy(&tx_arg, cmd->arguments, sizeof(tx_arg));
    tx_arg = __builtin_bswap32(tx_arg);
    const uint32_t total_blocks = (rx_length + SDSPI_MAX_DATA_LEN - 1) / SDSPI_MAX_DATA_LEN;
    const int64_t read_start_us = esp_timer_get_time();

    spi_transaction_t t_command = {
        .length = (SDSPI_CMD_R1_SIZE + SDSPI_RESPONSE_MAX_DELAY) * 8,
        .tx_buffer = cmd,
        .rx_buffer = cmd,
    };
    esp_err_t ret = spi_device_polling_transmit(slot->spi_handle, &t_command);
    if (ret != ESP_OK) {
        record_read_fail(tx_opcode, tx_arg, total_blocks, 0, "CMD_SPI_TX",
                         cmd->r1, NULL, 0, read_start_us, ret);
        return ret;
    }

    uint8_t* cmd_u8 = (uint8_t*) cmd;
    uint8_t r1_window[8];
    memcpy(r1_window, cmd_u8 + offsetof(sdspi_hw_cmd_t, r1), sizeof(r1_window));
    size_t pre_scan_data_size = SDSPI_RESPONSE_MAX_DELAY;
    uint8_t* pre_scan_data_ptr = cmd_u8 + SDSPI_CMD_R1_SIZE;

    /* R1 response is delayed by 1-8 bytes from the request.
     * This loop searches for the response and writes it to cmd->r1.
     */
    while ((cmd->r1 & SD_SPI_R1_NO_RESPONSE) != 0 && pre_scan_data_size > 0) {
        cmd->r1 = *pre_scan_data_ptr;
        ++pre_scan_data_ptr;
        --pre_scan_data_size;
    }
    if (cmd->r1 & SD_SPI_R1_NO_RESPONSE) {
        ESP_LOGD(TAG, "no response token found");
        record_read_fail(tx_opcode, tx_arg, total_blocks, 0, "R1_MISSING",
                         cmd->r1, r1_window, sizeof(r1_window), read_start_us, ESP_ERR_TIMEOUT);
        return ESP_ERR_TIMEOUT;
    }
    if (cmd->r1 != 0 && tx_opcode != SD_IO_RW_EXTENDED) {
        const esp_err_t r1_err = r1_read_err_to_esp_err(cmd->r1);
        record_read_fail(tx_opcode, tx_arg, total_blocks, 0, "R1_ERR",
                         cmd->r1, r1_window, sizeof(r1_window), read_start_us, r1_err);
        return r1_err;
    }

    uint32_t blk_idx = 0;
    while (rx_length > 0) {
        uint8_t extra_saved[SDSPI_RESPONSE_MAX_DELAY];
        size_t extra_data_size = 0;
        bool need_poll = true;

        for (size_t i = 0; i < pre_scan_data_size; ++i) {
            const uint8_t b = pre_scan_data_ptr[i];
            if (b == TOKEN_BLOCK_START) {
                extra_data_size = pre_scan_data_size - i - 1;
                if (extra_data_size > 0) {
                    memcpy(extra_saved, pre_scan_data_ptr + i + 1, extra_data_size);
                }
                need_poll = false;
                break;
            }
            if (b != 0xff && b != 0) {
                record_read_fail(tx_opcode, tx_arg, total_blocks, blk_idx, "PRESCAN_ERR",
                                 cmd->r1, pre_scan_data_ptr, pre_scan_data_size, read_start_us, ESP_ERR_INVALID_RESPONSE);
                return ESP_ERR_INVALID_RESPONSE;
            }
        }

        if (need_poll) {
            uint8_t poll_rx[8];
            // Wait for data to be ready
            ret = poll_data_token_ex(slot, extra_saved, &extra_data_size, cmd->timeout_ms, poll_rx);
            if (ret != ESP_OK) {
                const char *stage = (ret == ESP_ERR_TIMEOUT) ? "TOKEN_TIMEOUT" :
                                    (ret == ESP_ERR_INVALID_RESPONSE) ? "TOKEN_ERR" : "TOKEN_SPI_TX";
                record_read_fail(tx_opcode, tx_arg, total_blocks, blk_idx, stage,
                                 cmd->r1, poll_rx, sizeof(poll_rx), read_start_us, ret);
                return ret;
            }
        }

        // Arrange RX buffer
        const size_t block_len = MIN(rx_length, SDSPI_MAX_DATA_LEN);
        const size_t receive_extra_bytes = (rx_length > SDSPI_MAX_DATA_LEN) ? 4 : 2;
        uint8_t* rx_data;
        ret = get_block_buf(slot, &rx_data);
        if (ret != ESP_OK) {
            return ret;
        }

        if (block_len < sizeof(extra_saved) &&
                extra_data_size > block_len &&
                extra_data_size <= sizeof(extra_saved)) {
            const size_t surplus = MIN(extra_data_size - block_len, receive_extra_bytes);
            const size_t tail_rx = receive_extra_bytes - surplus;
            memcpy(data, extra_saved, block_len);
            memcpy(rx_data, extra_saved + block_len, surplus);
            if (tail_rx > 0) {
                memset(rx_data + surplus, 0xff, tail_rx);
                spi_transaction_t t_tail = {
                    .length = tail_rx * 8,
                    .rx_buffer = rx_data + surplus,
                    .tx_buffer = rx_data + surplus
                };
                ret = spi_device_transmit(slot->spi_handle, &t_tail);
                if (ret != ESP_OK) {
                    record_read_fail(tx_opcode, tx_arg, total_blocks, blk_idx, "DATA_SPI_TX",
                                     cmd->r1, NULL, 0, read_start_us, ret);
                    return ret;
                }
            }
            uint16_t crc = UINT16_MAX;
            memcpy(&crc, rx_data, sizeof(crc));
            pre_scan_data_size = receive_extra_bytes - sizeof(crc);
            pre_scan_data_ptr = rx_data + sizeof(crc);
            if (slot->data_crc_enabled) {
                uint16_t crc_of_data = sdspi_crc16(data, block_len);
                if (crc_of_data != crc) {
                    ESP_LOGE(TAG, "data CRC failed, got=0x%04x expected=0x%04x", crc_of_data, crc);
                    ESP_LOG_BUFFER_HEX(TAG, data, 16);
                    record_read_fail(tx_opcode, tx_arg, total_blocks, blk_idx, "DATA_CRC",
                                     cmd->r1, rx_data, receive_extra_bytes, read_start_us, ESP_ERR_INVALID_CRC);
                    return ESP_ERR_INVALID_CRC;
                }
            }
        } else {
            size_t will_receive = block_len - extra_data_size;

            // receive actual data
            memset(rx_data, 0xff, will_receive + receive_extra_bytes);
            spi_transaction_t t_data = {
                .length = (will_receive + receive_extra_bytes) * 8,
                .rx_buffer = rx_data,
                .tx_buffer = rx_data
            };

            ret = spi_device_transmit(slot->spi_handle, &t_data);
            if (ret != ESP_OK) {
                record_read_fail(tx_opcode, tx_arg, total_blocks, blk_idx, "DATA_SPI_TX",
                                 cmd->r1, NULL, 0, read_start_us, ret);
                return ret;
            }

            // CRC bytes need to be received even if CRC is not enabled
            uint16_t crc = UINT16_MAX;
            memcpy(&crc, rx_data + will_receive, sizeof(crc));

            // Bytes to scan for the start token
            pre_scan_data_size = receive_extra_bytes - sizeof(crc);
            pre_scan_data_ptr = rx_data + will_receive + sizeof(crc);

            // Copy data to the destination buffer
            if (will_receive > 0) {
                memcpy(data + extra_data_size, rx_data, will_receive);
            }
            if (extra_data_size > 0) {
                memcpy(data, extra_saved, extra_data_size);
            }

            // compute CRC of the received data
            uint16_t crc_of_data = 0;
            if (slot->data_crc_enabled) {
                crc_of_data = sdspi_crc16(data, block_len);
                if (crc_of_data != crc) {
                    ESP_LOGE(TAG, "data CRC failed, got=0x%04x expected=0x%04x", crc_of_data, crc);
                    ESP_LOG_BUFFER_HEX(TAG, data, 16);
                    record_read_fail(tx_opcode, tx_arg, total_blocks, blk_idx, "DATA_CRC",
                                     cmd->r1, rx_data + will_receive, receive_extra_bytes, read_start_us, ESP_ERR_INVALID_CRC);
                    return ESP_ERR_INVALID_CRC;
                }
            }
        }

        data += block_len;
        rx_length -= block_len;
        ++blk_idx;
    }

    if (need_stop_command) {
        // To end multi block transfer, send stop command and wait for the
        // card to process it
        sdspi_hw_cmd_t stop_cmd;
        make_hw_cmd(MMC_STOP_TRANSMISSION, 0, cmd->timeout_ms, &stop_cmd);
        ret = start_command_default(slot, SDSPI_CMD_FLAG_RSP_R1B, &stop_cmd);
        if (ret == ESP_OK) {
            ++s_diag.cmd12_ok;
        } else {
            ++s_diag.cmd12_err;
            const uint8_t *w = (const uint8_t *)&stop_cmd + offsetof(sdspi_hw_cmd_t, r1);
            record_read_fail(MMC_STOP_TRANSMISSION, tx_arg, total_blocks, blk_idx,
                             (stop_cmd.r1 & SD_SPI_R1_NO_RESPONSE) ? "STOP_R1_MISSING" : "STOP_BUSY_OR_ERR",
                             stop_cmd.r1, w, 8, read_start_us, ret);
            return ret;
        }
        if (stop_cmd.r1 != 0) {
            ESP_LOGD(TAG, "%s: STOP_TRANSMISSION response 0x%02x", __func__, stop_cmd.r1);
        }
        uint8_t last_busy_rx = 0xff;
        ret = poll_busy_ex(slot, cmd->timeout_ms, use_polling, &last_busy_rx);
        if (ret != ESP_OK) {
            record_read_fail(MMC_STOP_TRANSMISSION, tx_arg, total_blocks, blk_idx,
                             "POST_STOP_BUSY", stop_cmd.r1, &last_busy_rx, 1, read_start_us, ret);
            return ret;
        }
    }
    return ESP_OK;
}

/* For CMD53, we can send in byte mode, or block mode
 * The data start token is different, and cannot be determined by the length
 * That's why we need ``multi_block``.
 * It's also different that stop transmission token is not needed in the SDIO mode.
 */
static esp_err_t start_command_write_blocks(slot_info_t *slot, sdspi_hw_cmd_t *cmd,
                                            const uint8_t *data, uint32_t tx_length, bool multi_block, bool stop_trans)
{
    if (card_write_protected(slot)) {
        ESP_LOGW(TAG, "%s: card write protected", __func__);
        return ESP_ERR_INVALID_STATE;
    }
    const int tx_opcode = cmd->cmd_index;
    uint32_t tx_arg = 0;
    memcpy(&tx_arg, cmd->arguments, sizeof(tx_arg));
    tx_arg = __builtin_bswap32(tx_arg);
    const uint32_t total_blocks = (tx_length + SDSPI_MAX_DATA_LEN - 1) / SDSPI_MAX_DATA_LEN;
    const int64_t write_start_us = esp_timer_get_time();
    s_diag.last_write_cmd = (uint8_t)tx_opcode;
    s_diag.last_write_arg = tx_arg;
    s_diag.last_write_r1 = 0xff;
    s_diag.last_write_data_rsp = 0xff;
    s_diag.last_write_first_rx = 0xff;
    s_diag.last_write_last_rx = 0xff;
    s_diag.write_busy_zeros_last = 0;
    s_diag.write_busy_last_us = 0;

    // Send the minimum length that is sure to get the complete response
    // SD cards always return R1 (1bytes), SDIO returns R5 (2 bytes)
    const int send_bytes = SDSPI_CMD_R5_SIZE + SDSPI_NCR_MAX_SIZE - SDSPI_NCR_MIN_SIZE;

    spi_transaction_t t_command = {
        .length = send_bytes * 8,
        .tx_buffer = cmd,
        .rx_buffer = cmd,
    };
    esp_err_t ret = spi_device_polling_transmit(slot->spi_handle, &t_command);
    if (ret != ESP_OK) {
        record_read_fail(tx_opcode, tx_arg, total_blocks, 0, "WR_CMD_SPI_TX",
                         cmd->r1, NULL, 0, write_start_us, ret);
        return ret;
    }

    uint8_t r1_window[8];
    memcpy(r1_window, (const uint8_t *)cmd + offsetof(sdspi_hw_cmd_t, r1), sizeof(r1_window));

    // check if command response valid
    ret = shift_cmd_response(cmd, send_bytes);
    if (ret != ESP_OK) {
        ESP_LOGD(TAG, "%s: check_cmd_response returned 0x%x", __func__, ret);
        record_read_fail(tx_opcode, tx_arg, total_blocks, 0, "WR_R1_MISSING",
                         cmd->r1, r1_window, sizeof(r1_window), write_start_us, ESP_ERR_TIMEOUT);
        return ESP_ERR_TIMEOUT;
    }
    s_diag.last_write_r1 = cmd->r1;
    if (cmd->r1 != 0 && tx_opcode != SD_IO_RW_EXTENDED) {
        const esp_err_t r1_err = r1_read_err_to_esp_err(cmd->r1);
        record_read_fail(tx_opcode, tx_arg, total_blocks, 0, "WR_R1_ERR",
                         cmd->r1, r1_window, sizeof(r1_window), write_start_us, r1_err);
        return r1_err;
    }

    uint8_t start_token = multi_block ?
                          TOKEN_BLOCK_START_WRITE_MULTI : TOKEN_BLOCK_START;

    uint32_t blk_idx = 0;
    while (tx_length > 0) {
        // Write block start token
        spi_transaction_t t_start_token = {
            .length = sizeof(start_token) * 8,
            .tx_buffer = &start_token
        };
        ret = spi_device_polling_transmit(slot->spi_handle, &t_start_token);
        if (ret != ESP_OK) {
            record_read_fail(tx_opcode, tx_arg, total_blocks, blk_idx, "WR_TOKEN_SPI_TX",
                             cmd->r1, NULL, 0, write_start_us, ret);
            return ret;
        }

        // Prepare data to be sent
        size_t will_send = MIN(tx_length, SDSPI_MAX_DATA_LEN);
        const uint8_t* tx_data = data;
        if (!esp_ptr_in_dram(tx_data)) {
            // If the pointer can't be used with DMA, copy data into a new buffer
            uint8_t* tmp;
            ret = get_block_buf(slot, &tmp);
            if (ret != ESP_OK) {
                return ret;
            }
            memcpy(tmp, tx_data, will_send);
            tx_data = tmp;
        }

        // Write data
        spi_transaction_t t_data = {
            .length = will_send * 8,
            .tx_buffer = tx_data,
        };
        ret = spi_device_transmit(slot->spi_handle, &t_data);
        if (ret != ESP_OK) {
            record_read_fail(tx_opcode, tx_arg, total_blocks, blk_idx, "WR_DATA_SPI_TX",
                             cmd->r1, NULL, 0, write_start_us, ret);
            return ret;
        }

        // Write CRC and get the response in one transaction
        uint16_t crc = sdspi_crc16(data, will_send);
        const int size_crc_response = sizeof(crc) + 1;

        spi_transaction_t t_crc_rsp = {
            .length = size_crc_response * 8,
            .flags = SPI_TRANS_USE_TXDATA | SPI_TRANS_USE_RXDATA,
        };
        memset(t_crc_rsp.tx_data, 0xff, 4);
        memcpy(t_crc_rsp.tx_data, &crc, sizeof(crc));

        ret = spi_device_polling_transmit(slot->spi_handle, &t_crc_rsp);
        if (ret != ESP_OK) {
            record_read_fail(tx_opcode, tx_arg, total_blocks, blk_idx, "WR_CRC_SPI_TX",
                             cmd->r1, NULL, 0, write_start_us, ret);
            return ret;
        }

        uint8_t data_rsp = t_crc_rsp.rx_data[2];
        s_diag.last_write_data_rsp = data_rsp;
        if (!SD_SPI_DATA_RSP_VALID(data_rsp)) {
            record_read_fail(tx_opcode, tx_arg, total_blocks, blk_idx, "WR_DATA_RSP_BAD",
                             cmd->r1, &data_rsp, 1, write_start_us, ESP_ERR_INVALID_RESPONSE);
            return ESP_ERR_INVALID_RESPONSE;
        }
        switch (SD_SPI_DATA_RSP(data_rsp)) {
        case SD_SPI_DATA_ACCEPTED:
            break;
        case SD_SPI_DATA_CRC_ERROR:
            record_read_fail(tx_opcode, tx_arg, total_blocks, blk_idx, "WR_DATA_CRC",
                             cmd->r1, &data_rsp, 1, write_start_us, ESP_ERR_INVALID_CRC);
            return ESP_ERR_INVALID_CRC;
        case SD_SPI_DATA_WR_ERROR:
            record_read_fail(tx_opcode, tx_arg, total_blocks, blk_idx, "WR_DATA_ERR",
                             cmd->r1, &data_rsp, 1, write_start_us, ESP_FAIL);
            return ESP_FAIL;
        default:
            record_read_fail(tx_opcode, tx_arg, total_blocks, blk_idx, "WR_DATA_RSP_BAD",
                             cmd->r1, &data_rsp, 1, write_start_us, ESP_ERR_INVALID_RESPONSE);
            return ESP_ERR_INVALID_RESPONSE;
        }

        // Wait for the card to finish writing data
        sdspi_busy_info_t binfo = {0};
        ret = poll_busy_detail(slot, cmd->timeout_ms, no_use_polling, &binfo);
        s_diag.write_busy_zeros_last = binfo.zero_bytes;
        s_diag.write_busy_last_us = binfo.elapsed_us;
        if (binfo.elapsed_us > s_diag.write_busy_max_us) {
            s_diag.write_busy_max_us = binfo.elapsed_us;
        }
        s_diag.last_write_first_rx = binfo.first_rx;
        s_diag.last_write_last_rx = binfo.last_rx;
        if (ret != ESP_OK) {
            uint8_t wrx[2] = {binfo.first_rx, binfo.last_rx};
            record_read_fail(tx_opcode, tx_arg, total_blocks, blk_idx, "WR_BUSY_TIMEOUT",
                             cmd->r1, wrx, sizeof(wrx), write_start_us, ret);
            return ret;
        }

        tx_length -= will_send;
        data += will_send;
        ++blk_idx;
    }

    if (stop_trans) {
        uint8_t stop_token[2] = {
            TOKEN_BLOCK_STOP_WRITE_MULTI,
            SDSPI_MOSI_IDLE_VAL
        };
        spi_transaction_t t_stop_token = {
            .length = sizeof(stop_token) * 8,
            .tx_buffer = &stop_token,
        };
        ret = spi_device_polling_transmit(slot->spi_handle, &t_stop_token);
        if (ret != ESP_OK) {
            record_read_fail(tx_opcode, tx_arg, total_blocks, blk_idx, "WR_STOP_SPI_TX",
                             cmd->r1, NULL, 0, write_start_us, ret);
            return ret;
        }

        sdspi_busy_info_t sinfo = {0};
        ret = poll_busy_detail(slot, cmd->timeout_ms, use_polling, &sinfo);
        s_diag.write_busy_zeros_last = sinfo.zero_bytes;
        s_diag.write_busy_last_us = sinfo.elapsed_us;
        if (sinfo.elapsed_us > s_diag.write_busy_max_us) {
            s_diag.write_busy_max_us = sinfo.elapsed_us;
        }
        s_diag.last_write_first_rx = sinfo.first_rx;
        s_diag.last_write_last_rx = sinfo.last_rx;
        if (ret != ESP_OK) {
            uint8_t srx[2] = {sinfo.first_rx, sinfo.last_rx};
            record_read_fail(tx_opcode, tx_arg, total_blocks, blk_idx, "WR_STOP_BUSY",
                             cmd->r1, srx, sizeof(srx), write_start_us, ret);
            return ret;
        }
    }

    return ESP_OK;
}

esp_err_t sdspi_host_io_int_enable(sdspi_dev_handle_t handle)
{
    //the pin and its interrupt is already initialized, nothing to do here.
    return ESP_OK;
}

//the interrupt will give the semaphore and then disable itself
esp_err_t sdspi_host_io_int_wait(sdspi_dev_handle_t handle, TickType_t timeout_ticks)
{
    slot_info_t* slot = get_slot_info(handle);
    //skip the interrupt and semaphore if the gpio is already low.
    if (gpio_get_level(slot->gpio_int) == 0) {
        return ESP_OK;
    }

    //clear the semaphore before wait
    xSemaphoreTake(slot->semphr_int, 0);
    //enable the interrupt and wait for the semaphore
    gpio_intr_enable(slot->gpio_int);
    BaseType_t ret = xSemaphoreTake(slot->semphr_int, timeout_ticks);
    if (ret == pdFALSE) {
        gpio_intr_disable(slot->gpio_int);
        return ESP_ERR_TIMEOUT;
    }
    return ESP_OK;
}

esp_err_t sdspi_host_get_dma_info(int slot, esp_dma_mem_info_t *dma_mem_info)
{
    (void)slot;
    dma_mem_info->extra_heap_caps = MALLOC_CAP_DMA;
    dma_mem_info->dma_alignment_bytes = 4;
    return ESP_OK;
}

bool sdspi_host_check_buffer_alignment(int slot, const void *buf, size_t size)
{
    //for future-proof
    (void)slot;

    if (!buf || !size) {
        return ESP_FAIL;
    }

    //spi master driver will deal with the buffer alignment
    bool is_aligned = ((intptr_t)buf % 4 == 0) && (size % 4 == 0);

    return is_aligned;
}
