#pragma once
#include "esp_err.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "node/sampling.hpp"
#include "node/logic.hpp"

namespace node::runtime {
// Internal RTOS bits, NOT LoRa flags or reason_mask wire assignments.
namespace event {
inline constexpr EventBits_t WIFI_UP = 1U << 0, MQTT_UP = 1U << 1, LORA_READY = 1U << 2;
inline constexpr EventBits_t SD_OK = 1U << 3, TIME_SYNCED = 1U << 4, EDGE_ONLINE = 1U << 5;
inline constexpr EventBits_t IMU_TOP_OK = 1U << 6, IMU_TOE_OK = 1U << 7, SOIL_OK = 1U << 8;
}
esp_err_t start();
EventBits_t system_events();
// ONE short transaction per callback; release mutex before ADS conversion wait.
using I2cTransaction = esp_err_t (*)(void*);
esp_err_t with_i2c_transaction(I2cTransaction transaction, void* context);
// Task-context copies; no I/O inside snapshot critical sections.
void publish_imu(sampling::ImuSite, const sampling::ImuSample&);
void publish_soil(unsigned channel, const sampling::SoilSample&);
sampling::SensorSnapshot sensor_snapshot();
risk_runtime::Snapshot risk_snapshot();
// Integration point only: not attached to real GPIO, no ISR driver installed.
void imu_notify_from_isr(void*);
} // namespace node::runtime
