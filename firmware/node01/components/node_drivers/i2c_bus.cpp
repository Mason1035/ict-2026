#include "node/i2c_bus.hpp"
#include "node/board.hpp"
#include "node/timeout_budget.hpp"
#include "esp_timer.h"
#include "driver/gpio.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "sdkconfig.h"
#include <algorithm>
#include <cstring>
#include <limits>

namespace node::drivers {
namespace {
constexpr std::array<std::uint8_t, 3> addresses{board::bus::imu_top_address,
    board::bus::imu_toe_address, board::bus::ads1115_address};
constexpr unsigned requested_transfer_wait_ms = 10;
constexpr int transfer_timeout_ms = timing::guarded_timeout_ms(requested_transfer_wait_ms, configTICK_RATE_HZ);
static_assert(transfer_timeout_ms > 0);
struct Transfer {
    i2c_master_dev_handle_t dev;
    const std::uint8_t* tx; std::size_t tx_size;
    std::uint8_t* rx; std::size_t rx_size;
    bool executed = false;
    I2cLineLevels lines{};
};
esp_err_t transfer(void* p) {
    auto& t = *static_cast<Transfer*>(p);
    t.lines.before_sda = gpio_get_level(static_cast<gpio_num_t>(board::pin::i2c_sda));
    t.lines.before_scl = gpio_get_level(static_cast<gpio_num_t>(board::pin::i2c_scl));
    t.executed = true;
    const auto error = t.rx_size ? i2c_master_transmit_receive(t.dev, t.tx, t.tx_size,
        t.rx, t.rx_size, transfer_timeout_ms) :
        i2c_master_transmit(t.dev, t.tx, t.tx_size, transfer_timeout_ms);
    t.lines.after_sda = gpio_get_level(static_cast<gpio_num_t>(board::pin::i2c_sda));
    t.lines.after_scl = gpio_get_level(static_cast<gpio_num_t>(board::pin::i2c_scl));
    return error;
}
struct Probe {
    i2c_master_bus_handle_t bus;
    std::uint8_t address;
    bool executed = false;
};
esp_err_t perform_probe(void* p) {
    auto& probe = *static_cast<Probe*>(p);
    probe.executed = true;
    return i2c_master_probe(probe.bus, probe.address, transfer_timeout_ms);
}
}
esp_err_t I2cBus::initialize(Executor executor) {
    if (bus_ || !executor) return ESP_ERR_INVALID_STATE;
    execute_ = executor;
    i2c_master_bus_config_t cfg{};
    cfg.i2c_port = I2C_NUM_0;
    cfg.sda_io_num = static_cast<gpio_num_t>(board::pin::i2c_sda);
    cfg.scl_io_num = static_cast<gpio_num_t>(board::pin::i2c_scl);
    cfg.clk_source = I2C_CLK_SRC_DEFAULT;
    cfg.glitch_ignore_cnt = 7;
    // External pull-ups must be electrically verified; do not change module wiring.
    auto e = i2c_new_master_bus(&cfg, &bus_);
    if (e != ESP_OK) return e;
    for (unsigned i = 0; i < addresses.size(); ++i) {
        i2c_device_config_t d{};
        d.dev_addr_length = I2C_ADDR_BIT_LEN_7;
        d.device_address = addresses[i];
        d.scl_speed_hz = CONFIG_NODE01_I2C_HZ;
        e = i2c_master_bus_add_device(bus_, &d, &devices_[i]);
        if (e != ESP_OK) { close(); return e; }
    }
    ESP_LOGI("node_i2c", "I2C_INIT configured=%d Hz target=%lu Hz api_timeout_ms=%u min_wait_ms=%u tick_hz=%d; reliability NEED_HARDWARE_RETEST",
        CONFIG_NODE01_I2C_HZ, static_cast<unsigned long>(board::bus::i2c_hz),
        static_cast<unsigned>(transfer_timeout_ms), requested_transfer_wait_ms, configTICK_RATE_HZ);
    // No general/reserved address scan. Historical 0x7e remains unexplained.
    return ESP_OK;
}
esp_err_t I2cBus::probe(std::uint8_t address) {
    // Serialize through the same runtime executor; never rebuild live handles.
    Probe request{bus_, address};
    const auto error = !bus_ || !device(address) || !execute_ ? ESP_ERR_INVALID_STATE :
#ifdef CONFIG_NODE01_I2C_LOCK_DIAG_TRACE
        diagnostic_execute_ ? diagnostic_execute_(perform_probe, &request, {0,address,0,'P'}, &request.executed) :
#endif
        execute_(perform_probe, &request);
    diagnostics_.record_probe(address, request.executed, error);
    return error;
}
esp_err_t I2cBus::close() {
    // No further transfer is allowed once cleanup begins. Retain any handle
    // whose removal fails so a retry cannot create a second live bus/device.
    execute_ = nullptr;
#ifdef CONFIG_NODE01_I2C_LOCK_DIAG_TRACE
    diagnostic_execute_ = nullptr;
#endif
    esp_err_t error = ESP_OK;
    for (auto& d : devices_) if (d) {
        const auto e = i2c_master_bus_rm_device(d);
        if (e == ESP_OK) d = nullptr;
        else if (error == ESP_OK) error = e;
    }
    if (bus_ && error == ESP_OK) {
        error = i2c_del_master_bus(bus_);
        if (error == ESP_OK) bus_ = nullptr;
    }
    if (error != ESP_OK) ESP_LOGE("node_i2c", "I2C_CLOSE failed err=%s; handles retained", esp_err_to_name(error));
    return error;
}
i2c_master_dev_handle_t I2cBus::device(std::uint8_t address) const {
    for (unsigned i = 0; i < addresses.size(); ++i) if (address == addresses[i]) return devices_[i];
    return nullptr;
}
esp_err_t I2cBus::read(std::uint8_t a, std::uint8_t reg, std::uint8_t* out, std::size_t n) {
    const auto begin = now_us();
    const auto d = device(a);
    Transfer t{d, &reg, 1, out, n};
    const auto error = !d || !execute_ ? ESP_ERR_INVALID_STATE :
        (!out || !n ? ESP_ERR_INVALID_ARG :
#ifdef CONFIG_NODE01_I2C_LOCK_DIAG_TRACE
        diagnostic_execute_ ? diagnostic_execute_(transfer,&t,{static_cast<std::uint16_t>(std::min(n,std::size_t{65535})),a,reg,'R'},&t.executed) :
#endif
        execute_(transfer, &t));
    diagnostics_.record(a, reg, n, true, t.executed, error, now_us() - begin, t.lines);
    return error;
}
esp_err_t I2cBus::write(std::uint8_t a, std::uint8_t reg, const std::uint8_t* data, std::size_t n) {
    const auto begin = now_us();
    const auto d = device(a);
    std::uint8_t bytes[3]{reg, 0, 0};
    const bool valid_data = data && n && n <= 2;
    if (valid_data) std::memcpy(bytes + 1, data, n);
    Transfer t{d, bytes, n + 1, nullptr, 0};
    const auto error = !d || !execute_ ? ESP_ERR_INVALID_STATE :
        (!valid_data ? ESP_ERR_INVALID_ARG :
#ifdef CONFIG_NODE01_I2C_LOCK_DIAG_TRACE
        diagnostic_execute_ ? diagnostic_execute_(transfer,&t,{static_cast<std::uint16_t>(n),a,reg,'W'},&t.executed) :
#endif
        execute_(transfer, &t));
    diagnostics_.record(a, reg, n, false, t.executed, error, now_us() - begin, t.lines);
    return error;
}
void I2cBus::delay_ms(unsigned ms) {
    // Only the IMU's 2ms reset and 50ms power warmup call this backend.
    // At 100Hz, floor(ms/tick)+1 can make the 2ms request almost zero near a
    // tick edge. Ceil+guard gives 2 ticks; the 50ms request stays at 6 ticks.
    static_assert(std::numeric_limits<unsigned>::digits <= std::numeric_limits<std::uint32_t>::digits);
    constexpr auto maximum_ticks = timing::minimum_delay_ticks(std::numeric_limits<unsigned>::max(), configTICK_RATE_HZ);
    static_assert(maximum_ticks > 0, "Configured tick rate must represent every unsigned startup delay");
    static_assert(maximum_ticks <= std::numeric_limits<TickType_t>::max(), "Startup delay exceeds TickType_t");
    vTaskDelay(static_cast<TickType_t>(timing::minimum_delay_ticks(ms, configTICK_RATE_HZ)));
}
std::uint64_t I2cBus::now_us() const { return esp_timer_get_time(); }
}
