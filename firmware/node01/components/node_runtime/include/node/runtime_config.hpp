#pragma once
#include <array>
#include <cstdint>
#include "freertos/FreeRTOS.h"

namespace node::runtime::config {
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
    {"ImuTask",            1, 7, 4096, true},  // notification wait; no ISR installed
    {"RiskTask",           1, 6, 4096, true},
    {"AlarmTask",          1, 6, 3072, true},
    {"SlowSensorTask",     1, 5, 3072, false}, // no ADS driver
    {"CommSupervisorTask", 0, 5, 3072, true},  // notification wait; no transports
    {"LoRaTask",           0, 4, 4096, false}, // TBD-11
    {"StorageTask",        0, 3, 4096, false}, // no SD driver
    {"UiHealthTask",       0, 2, 4096, true}
}};
inline constexpr UBaseType_t alarm_queue_length = 8; // PROVISIONAL / TBD-15
inline constexpr unsigned i2c_mutex_timeout_ms = 10; // PROVISIONAL / TBD-15
inline constexpr unsigned health_period_ms = 10000;
inline constexpr unsigned risk_period_ms = 50; // 20 Hz, existing baseline
static_assert(pdMS_TO_TICKS(risk_period_ms) > 0);
static_assert((risk_period_ms * configTICK_RATE_HZ) % 1000 == 0,
              "RTOS tick must represent a 50 ms period exactly");
static_assert(configNUMBER_OF_CORES == 2, "Baseline requires dual core FreeRTOS");
} // namespace node::runtime::config
