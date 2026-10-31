#pragma once
#include "esp_err.h"
#include <array>
#include <cstddef>
#include <cstdint>

namespace node::drivers {
// Pad snapshots are observations at API boundaries, not an oscilloscope trace.
// -1 means the SDK callback was not entered, so no pad observation exists.
struct I2cLineLevels {
    std::int8_t before_sda = -1, before_scl = -1, after_sda = -1, after_scl = -1;
};
struct I2cDeviceDiagnostics {
    std::uint8_t address = 0;
    // transfers counts logical API requests, including an outer lock timeout.
    // sdk_calls counts only requests that actually entered the SDK callback.
    std::uint64_t transfers = 0, sdk_calls = 0, reads = 0, writes = 0;
    std::uint64_t errors = 0, timeouts = 0, invalid_states = 0;
    // IDF 5.5.3 folds non-DONE synchronous outcomes (including NACK and
    // hardware timeout) into INVALID_STATE. Never label this as handle loss.
    std::uint64_t sdk_errors = 0, local_errors = 0;
    std::uint64_t sdk_invalid_states = 0, local_invalid_states = 0;
    std::uint64_t probes = 0, probe_sdk_calls = 0;
    esp_err_t last_probe_error = ESP_OK;
    std::uint64_t total_wall_us = 0, max_wall_us = 0, last_wall_us = 0;
    std::uint8_t last_reg = 0;
    std::size_t last_size = 0;
    bool last_read = false, last_executed = false;
    esp_err_t last_error = ESP_OK;
    // Sticky most-recent FAILURE context survives later successful requests.
    // Otherwise a low-rate Health read would usually only observe ESP_OK.
    std::uint8_t last_failed_reg = 0;
    std::size_t last_failed_size = 0;
    bool last_failed_read = false, last_failed_executed = false;
    esp_err_t last_failed_error = ESP_OK;
    std::uint64_t last_failed_wall_us = 0;
    I2cLineLevels last_failed_lines{};
};
// Same counter logic in firmware and host tests. The provided lock protects
// only fixed-size counters/copies, never a bus operation, delay or log output.
template<class Lock> class I2cDiagnosticRegistry {
public:
    explicit I2cDiagnosticRegistry(const std::array<std::uint8_t, 3>& addresses) {
        for (unsigned i = 0; i < data_.size(); ++i) data_[i].address = addresses[i];
    }
    void record(std::uint8_t address, std::uint8_t reg, std::size_t size, bool read,
                bool executed, esp_err_t error, std::uint64_t wall_us, I2cLineLevels lines = {}) {
        Guard guard(lock_);
        for (auto& d : data_) if (d.address == address) {
            ++d.transfers;
            if (executed) ++d.sdk_calls;
            if (read) ++d.reads; else ++d.writes;
            if (error != ESP_OK) {
                ++d.errors;
                if (executed) ++d.sdk_errors; else ++d.local_errors;
                if (error == ESP_ERR_INVALID_STATE) {
                    if (executed) ++d.sdk_invalid_states; else ++d.local_invalid_states;
                }
                d.last_failed_lines = lines;
                d.last_failed_reg = reg; d.last_failed_size = size;
                d.last_failed_read = read; d.last_failed_executed = executed;
                d.last_failed_error = error; d.last_failed_wall_us = wall_us;
            }
            if (error == ESP_ERR_TIMEOUT) ++d.timeouts;
            if (error == ESP_ERR_INVALID_STATE) ++d.invalid_states;
            d.total_wall_us += wall_us;
            if (wall_us > d.max_wall_us) d.max_wall_us = wall_us;
            d.last_wall_us = wall_us; d.last_reg = reg; d.last_size = size;
            d.last_read = read; d.last_executed = executed; d.last_error = error;
            break;
        }
    }
    // Startup-only targeted probes are not register transfers or observations.
    void record_probe(std::uint8_t address, bool executed, esp_err_t error) {
        Guard guard(lock_);
        for (auto& d : data_) if (d.address == address) {
            ++d.probes;
            if (executed) ++d.probe_sdk_calls;
            d.last_probe_error = error;
            break;
        }
    }
    void snapshot_into(std::array<I2cDeviceDiagnostics, 3>& destination) const {
        Guard guard(lock_); destination = data_;
    }
    std::array<I2cDeviceDiagnostics, 3> snapshot() const {
        std::array<I2cDeviceDiagnostics, 3> result{}; snapshot_into(result); return result;
    }
private:
    class Guard {
    public:
        explicit Guard(Lock& lock) : lock_(lock) { lock_.lock(); }
        ~Guard() { lock_.unlock(); }
        Guard(const Guard&) = delete;
        Guard& operator=(const Guard&) = delete;
    private: Lock& lock_;
    };
    mutable Lock lock_;
    std::array<I2cDeviceDiagnostics, 3> data_{};
};
} // namespace node::drivers
