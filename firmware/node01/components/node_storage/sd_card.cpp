#include "node/sd_card.hpp"
#include "node/board.hpp"
#include "driver/spi_common.h"
#include "driver/sdspi_host.h"
#include "esp_vfs_fat.h"
#include "esp_log.h"
#include "sdkconfig.h"

namespace node::storage {
PortStatus SdCard::mount() {
    if (cleanup_error_ != ESP_OK) { error_ = cleanup_error_; return status_ = PortStatus::Error; }
    if (card_) return status_;
    if (spi_owned_) { error_ = ESP_ERR_INVALID_STATE; return status_ = PortStatus::Error; }
    spi_bus_config_t bus{};
    bus.mosi_io_num = board::pin::sd_mosi; bus.miso_io_num = board::pin::sd_miso;
    bus.sclk_io_num = board::pin::sd_sclk; bus.quadwp_io_num = bus.quadhd_io_num = -1;
    bus.max_transfer_sz = 4096;
    sdmmc_host_t host = SDSPI_HOST_DEFAULT();
    host.max_freq_khz = CONFIG_NODE01_SD_KHZ;
    host.command_timeout_ms = 1000; // per-command bound, not whole-filesystem latency guarantee
    error_ = spi_bus_initialize(static_cast<spi_host_device_t>(host.slot), &bus, SDSPI_DEFAULT_DMA);
    if (error_ != ESP_OK) return status_ = PortStatus::Error;
    spi_owned_ = true;
    sdspi_device_config_t slot = SDSPI_DEVICE_CONFIG_DEFAULT();
    slot.gpio_cs = static_cast<gpio_num_t>(board::pin::sd_cs);
    slot.host_id = static_cast<spi_host_device_t>(host.slot);
    esp_vfs_fat_sdmmc_mount_config_t mount{};
    mount.format_if_mount_failed = false; // never erase/format the user's card
    mount.max_files = 3;
    mount.allocation_unit_size = 16 * 1024;
    sdmmc_card_t* mounted = nullptr;
    error_ = esp_vfs_fat_sdspi_mount(mount_point, &host, &slot, &mount, &mounted);
    if (error_ != ESP_OK) {
        // IDF can set out_card before allocating its final context, then free it
        // on error. Never retain/dereference the failed call's output pointer.
        if (mounted) cleanup_error_ = error_; // possible late VFS cleanup ambiguity
        const auto cleanup = spi_bus_free(slot.host_id);
        if (cleanup == ESP_OK) spi_owned_ = false;
        else cleanup_error_ = cleanup;
        ESP_LOGE("node_sd", "SD_MOUNT %s (no format attempted)", esp_err_to_name(error_));
        return status_ = PortStatus::Error;
    }
    card_ = mounted;
    ESP_LOGI("node_sd", "SD_MOUNT ready clock_khz=%d; target_hz=%lu; power-loss reliability TBD_HARDWARE_TEST",
        CONFIG_NODE01_SD_KHZ, static_cast<unsigned long>(board::bus::sd_initial_hz));
    sdmmc_card_print_info(stdout, card_);
    return status_ = PortStatus::Ready;
}
esp_err_t SdCard::reset() {
    if (cleanup_error_ != ESP_OK) { error_ = cleanup_error_; status_ = PortStatus::Error; return error_; }
    esp_err_t first_error = ESP_OK;
    if (card_) {
        auto* retiring = card_;
        card_ = nullptr; // unmount may free it even when its final unregister fails
        first_error = esp_vfs_fat_sdcard_unmount(mount_point, retiring);
    }
    if (spi_owned_) {
        const sdmmc_host_t host = SDSPI_HOST_DEFAULT();
        const auto freed = spi_bus_free(static_cast<spi_host_device_t>(host.slot));
        if (freed == ESP_OK) spi_owned_ = false;
        else if (first_error == ESP_OK) first_error = freed;
    }
    error_ = first_error;
    if (first_error != ESP_OK) cleanup_error_ = first_error;
    status_ = first_error == ESP_OK ? PortStatus::Unavailable : PortStatus::Error;
    return error_;
}
}
