#pragma once
#include <array>
#include <cstdint>
#include <limits>
#include "freertos/FreeRTOS.h"
#include "sdkconfig.h"
#include "node/sensors.hpp"
#include "node/diagnostic_mode.hpp"
#include "node/startup_policy.hpp"

namespace node::runtime::config {
#if defined(CONFIG_NODE01_SANDBOX_EXPERIMENT)
inline constexpr auto diagnostic_mode = diagnostic::Mode::SandboxExperiment;
#elif defined(CONFIG_NODE01_DIAG_SENSORS_ONLY)
inline constexpr auto diagnostic_mode = diagnostic::Mode::SensorsOnly;
#elif defined(CONFIG_NODE01_DIAG_STORAGE_ONLY)
inline constexpr auto diagnostic_mode = diagnostic::Mode::StorageOnly;
#else
inline constexpr auto diagnostic_mode = diagnostic::Mode::Acquisition;
#endif
inline constexpr bool sensors_enabled = diagnostic::sensors_enabled(diagnostic_mode);
inline constexpr bool storage_enabled = diagnostic::storage_enabled(diagnostic_mode);
inline constexpr bool isolation_mode = diagnostic::isolated(diagnostic_mode);
#if defined(CONFIG_NODE01_STARTUP_PROBE)
inline constexpr auto startup_plan = startup::Plan::Probe;
#elif defined(CONFIG_NODE01_STARTUP_IMU_FIRST)
inline constexpr auto startup_plan = startup::Plan::ImuFirst;
#else
inline constexpr auto startup_plan = startup::Plan::Concurrent;
#endif
inline constexpr bool startup_probe = sensors_enabled && startup::probes_enabled(startup_plan,
    diagnostic_mode == diagnostic::Mode::SensorsOnly);
inline constexpr unsigned startup_timeout_ms = 5000;

#ifdef CONFIG_NODE01_IMU_DRDY
inline constexpr bool imu_drdy_enabled = sensors_enabled;
#else
inline constexpr bool imu_drdy_enabled = false;
#endif
#ifdef CONFIG_NODE01_CAPTURE_SECONDS
inline constexpr unsigned capture_seconds = CONFIG_NODE01_CAPTURE_SECONDS;
#else
inline constexpr unsigned capture_seconds = 0;
#endif
enum class TaskId : unsigned { Imu, Risk, Alarm, SlowSensor, CommSupervisor, LoRa, Storage, UiHealth, Count };
struct TaskSpec {
    const char* name;
    BaseType_t core;
    UBaseType_t priority;
    std::uint32_t stack_bytes;
    bool enabled;
};
// PROVISIONAL / TBD-15: all stack/queue budgets are centralized here.
// IDF stack units are BYTES. No stack/queue/PSRAM/latency stress validation yet.
inline constexpr std::array<TaskSpec, static_cast<unsigned>(TaskId::Count)> tasks{{
    {sensors_enabled ? "ImuTask" : "StorageTestProducer", 1, 7, 4096, true},
    {"RiskTask",           1, 6, 4096, !isolation_mode},
    {"AlarmTask",          1, 6, 3072, !isolation_mode},
    {"SlowSensorTask",     1, 5, 4096, sensors_enabled},
#ifdef CONFIG_NODE01_NETWORK_ENABLE
    {"CommSupervisorTask", 0, 5, 6144, !isolation_mode},
#else
    {"CommSupervisorTask", 0, 5, 6144, false}, // no empty task when network is disabled
#endif
    {"LoRaTask",           0, 4, 4096, false}, // TBD-11
    {"StorageTask",        0, 3, 6144, storage_enabled},
    // R14: prior 120s runs left 704/832 B. Add 1 KiB only to this log-heavy
    // task; worst-path margin still requires real-board retest (HARDWARE_NOT_RUN).
    {"UiHealthTask",       0, 2, 5120, true}
}};
inline constexpr UBaseType_t alarm_queue_length = 8; // PROVISIONAL / TBD-15
// Target ABI: 120 bytes/record. 512 entries add 30 KiB INTERNAL RAM over
// 256, for ~2.49s at the measured 205.42/s only when empty. Still finite;
// long/repeated I/O stalls and existing backlog can exhaust it. Log real heap.
inline constexpr UBaseType_t storage_queue_length = 512;
inline constexpr unsigned storage_catchup_queue_rows = 128;
inline constexpr unsigned storage_pressure_high_rows = storage_queue_length * 3 / 4;
inline constexpr unsigned storage_pressure_low_rows = storage_pressure_high_rows / 2;
inline constexpr unsigned storage_long_io_us = 100000;
inline constexpr unsigned imu_period_ms = 10, soil_period_ms = 500;
inline constexpr unsigned imu_liveness_us = 30000; // 3 ODR periods; driver freshness, not B policy
inline constexpr unsigned soil_liveness_us = 1500000; // 3 sweeps; same diagnostic age bound as telemetry
inline constexpr unsigned progress_stall_ms = 30000; // diagnostic only, not watchdog feeding
inline constexpr unsigned i2c_mutex_timeout_ms = 10; // PROVISIONAL / TBD-15
inline constexpr unsigned health_period_ms = 10000;
// 100Hz RTOS tick means each explicit vTaskDelay(1) costs up to 10ms.
// Do not pay that after every eight rows (25.75 such delays/s at 206 rows/s).
inline constexpr unsigned storage_work_budget_us = 50000;
inline constexpr unsigned storage_append_yield_rows = 32;
inline constexpr unsigned storage_flush_rows = 256, storage_segment_rows = 4000;
inline constexpr unsigned effective_storage_segment_rows = capture_seconds ? std::numeric_limits<unsigned>::max() : storage_segment_rows;
inline constexpr unsigned imu_irq_fallback_age_us = 15000; // diagnostic timeout, not a fabricated observation
// Larger sync interval is explicit risk exposure, not a power-loss guarantee.
inline constexpr unsigned sensor_retry_ms = 5000; // ADS init failures only; bounded per-device retries
inline constexpr unsigned ads_max_polls = (drivers::ads_conversion_timeout_us + portTICK_PERIOD_MS * 1000 - 1)
    / (portTICK_PERIOD_MS * 1000) + 1;
inline constexpr unsigned risk_period_ms = 50; // 20 Hz, existing baseline
static_assert(pdMS_TO_TICKS(risk_period_ms) > 0);
static_assert((risk_period_ms * configTICK_RATE_HZ) % 1000 == 0,
              "RTOS tick must represent a 50 ms period exactly");
static_assert(configNUMBER_OF_CORES == 2, "Baseline requires dual core FreeRTOS");
} // namespace node::runtime::config
