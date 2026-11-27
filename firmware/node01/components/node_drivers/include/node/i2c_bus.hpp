#pragma once
#include "node/sensors.hpp"
#include "node/board.hpp"
#include "node/i2c_diagnostics.hpp"
#include "driver/i2c_master.h"
#include "freertos/FreeRTOS.h"
#ifdef CONFIG_NODE01_I2C_LOCK_DIAG_TRACE
#include "node/i2c_trace_operation.hpp"
#endif

namespace node::drivers {
class I2cBus final : public RegisterBus {
public:
    using Executor = esp_err_t (*)(esp_err_t (*)(void*), void*);
    esp_err_t initialize(Executor);
#ifdef CONFIG_NODE01_I2C_LOCK_DIAG_TRACE
    using DiagnosticExecutor = esp_err_t (*)(esp_err_t (*)(void*), void*, const I2cTraceOperation&, const bool*);
    void set_diagnostic_executor(DiagnosticExecutor executor) { diagnostic_execute_=executor; }
#endif
    // Explicit isolation-mode startup diagnostic only: fixed configured
    // addresses, one probe per caller request, no scan/retry or sample repair.
    esp_err_t probe(std::uint8_t address);
    esp_err_t close(); // only before sampling tasks are released / after they stop
    esp_err_t read(std::uint8_t, std::uint8_t, std::uint8_t*, std::size_t) override;
    esp_err_t write(std::uint8_t, std::uint8_t, const std::uint8_t*, std::size_t) override;
    void delay_ms(unsigned) override;
    std::uint64_t now_us() const override;
    void copy_diagnostics(std::array<I2cDeviceDiagnostics, 3>& destination) const {
        diagnostics_.snapshot_into(destination);
    }
    std::array<I2cDeviceDiagnostics, 3> diagnostics() const { return diagnostics_.snapshot(); }
private:
    struct DiagnosticMutex {
        portMUX_TYPE mux = portMUX_INITIALIZER_UNLOCKED;
        void lock() { portENTER_CRITICAL(&mux); }
        void unlock() { portEXIT_CRITICAL(&mux); }
    };
    I2cDiagnosticRegistry<DiagnosticMutex> diagnostics_{
        {board::bus::imu_top_address, board::bus::imu_toe_address, board::bus::ads1115_address}};
    i2c_master_bus_handle_t bus_ = nullptr;
    std::array<i2c_master_dev_handle_t, 3> devices_{};
    Executor execute_ = nullptr;
#ifdef CONFIG_NODE01_I2C_LOCK_DIAG_TRACE
    DiagnosticExecutor diagnostic_execute_ = nullptr;
#endif
    i2c_master_dev_handle_t device(std::uint8_t) const;
};
}
