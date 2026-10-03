#include "node/runtime.hpp"
#include "node/runtime_config.hpp"
#include "node/logic.hpp"
#include "node/ports.hpp"
#include <array>
#include <atomic>
#include <cinttypes>
#include <type_traits>
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "freertos/task.h"

namespace node::runtime {
namespace {
using config::TaskId;
constexpr unsigned count = static_cast<unsigned>(TaskId::Count);
constexpr EventBits_t runtime_ready = 1U << 9;
constexpr const char* tag = "node_runtime";
EventGroupHandle_t events = nullptr;
SemaphoreHandle_t i2c_mutex = nullptr;
QueueHandle_t alarm_queue = nullptr;
std::array<TaskHandle_t, count> handles{};
std::array<std::atomic<std::uint32_t>, count> progress{};
std::atomic<std::uint32_t> queue_overflows{0}, i2c_errors{0}, i2c_timeouts{0};
std::atomic<std::uint32_t> risk_deadline_misses{0};
portMUX_TYPE snapshot_lock = portMUX_INITIALIZER_UNLOCKED;
sampling::SensorSnapshot sensors{};
risk_runtime::Snapshot risk_state{};
bool started = false; // app_main is sole lifecycle owner
static_assert(std::is_trivially_copyable_v<risk_runtime::Snapshot>);
constexpr unsigned index(TaskId id) { return static_cast<unsigned>(id); }
void mark_progress(TaskId id) { progress[index(id)].fetch_add(1, std::memory_order_relaxed); }
void await_start() { xEventGroupWaitBits(events, runtime_ready, pdFALSE, pdTRUE, portMAX_DELAY); }
std::uint64_t uptime_ms() { return static_cast<std::uint64_t>(esp_timer_get_time()) / 1000; }

void imu_task(void*) {
    await_start();
    for (;;) {
        ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
        // Driver absent: notification is not a sample. Preserve unavailable data.
        mark_progress(TaskId::Imu);
    }
}
void risk_task(void*) {
    await_start();
    TickType_t last_wake = xTaskGetTickCount();
    risk_runtime::Snapshot last_enqueued{};
    bool have_enqueued = false;
    for (;;) {
        const auto result = risk_runtime::evaluate(features::evaluate(sensor_snapshot()));
        portENTER_CRITICAL(&snapshot_lock);
        risk_state = result;
        portEXIT_CRITICAL(&snapshot_lock);
        if (!have_enqueued || !risk_runtime::same_state(result, last_enqueued)) {
            if (xQueueSend(alarm_queue, &result, 0) == pdTRUE) {
                last_enqueued = result;
                have_enqueued = true;
            } else {
                queue_overflows.fetch_add(1, std::memory_order_relaxed);
                // Retry unchanged state next cycle, never block Risk on Alarm/network.
                // Critical-event retention must be tested before real Risk is enabled.
            }
        }
        mark_progress(TaskId::Risk);
        if (xTaskDelayUntil(&last_wake, pdMS_TO_TICKS(config::risk_period_ms)) != pdTRUE)
            risk_deadline_misses.fetch_add(1, std::memory_order_relaxed);
    }
}
void alarm_task(void*) {
    await_start();
    alarm::Controller controller;
    risk_runtime::Snapshot input;
    for (;;) {
        if (xQueueReceive(alarm_queue, &input, portMAX_DELAY) == pdTRUE) {
            controller.consume(input);
            mark_progress(TaskId::Alarm);
            // No GPIO drive until electrical interface/polarity is verified.
        }
    }
}
void comm_task(void*) {
    await_start();
    [[maybe_unused]] comm_supervisor::State state{};
    for (;;) {
        ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
        // Future observed-link events drive selection; no transports registered.
        mark_progress(TaskId::CommSupervisor);
    }
}
void health_task(void*) {
    await_start();
    for (;;) {
        mark_progress(TaskId::UiHealth);
        const auto observed_risk = risk_snapshot();
        ESP_LOGI(tag, "uptime_ms=%" PRIu64 " risk_cycles=%" PRIu32
                 " risk=%s calibration=%s event_bits=0x%lx", uptime_ms(),
                 progress[index(TaskId::Risk)].load(), observed_risk.risk.sensor_score ? "VALID" : "null",
                 observed_risk.calibration == risk_runtime::Calibration::Ready ? "READY" : "NOT_READY",
                 static_cast<unsigned long>(system_events()));
        ESP_LOGI(tag, "queue_depth=%u queue_overflows=%" PRIu32 " i2c_errors=%" PRIu32
                 " i2c_lock_timeouts=%" PRIu32 " risk_deadline_misses=%" PRIu32,
                 static_cast<unsigned>(uxQueueMessagesWaiting(alarm_queue)),
                 queue_overflows.load(), i2c_errors.load(), i2c_timeouts.load(), risk_deadline_misses.load());
        for (unsigned i = 0; i < count; ++i) if (handles[i]) {
            ESP_LOGI(tag, "task=%s progress=%" PRIu32 " stack_hwm_bytes=%u (TBD-15)",
                config::tasks[i].name, progress[i].load(),
                static_cast<unsigned>(uxTaskGetStackHighWaterMark(handles[i])));
        }
        // Blocking tasks may have zero progress legitimately; not a watchdog verdict.
        vTaskDelay(pdMS_TO_TICKS(config::health_period_ms));
    }
}
void cleanup_failed_start() {
    // Created tasks are still at startup gate, before resource access.
    for (auto& handle : handles) if (handle) { vTaskDelete(handle); handle = nullptr; }
    if (alarm_queue) { vQueueDelete(alarm_queue); alarm_queue = nullptr; }
    if (i2c_mutex) { vSemaphoreDelete(i2c_mutex); i2c_mutex = nullptr; }
    if (events) { vEventGroupDelete(events); events = nullptr; }
}
} // namespace

esp_err_t start() {
    if (started || events) return ESP_ERR_INVALID_STATE;
    events = xEventGroupCreate();
    i2c_mutex = xSemaphoreCreateMutex();
    alarm_queue = xQueueCreate(config::alarm_queue_length, sizeof(risk_runtime::Snapshot));
    if (!events || !i2c_mutex || !alarm_queue) { cleanup_failed_start(); return ESP_ERR_NO_MEM; }
    const std::array<TaskFunction_t, count> entries{
        imu_task, risk_task, alarm_task, nullptr, comm_task, nullptr, nullptr, health_task};
    for (unsigned i = 0; i < count; ++i) {
        const auto& spec = config::tasks[i];
        if (!spec.enabled) {
            ESP_LOGI(tag, "%s DISABLED: driver/transport not implemented", spec.name);
            continue;
        }
        if (!entries[i] || xTaskCreatePinnedToCore(entries[i], spec.name, spec.stack_bytes,
                nullptr, spec.priority, &handles[i], spec.core) != pdPASS) {
            ESP_LOGE(tag, "task creation failed: %s", spec.name);
            cleanup_failed_start();
            return ESP_ERR_NO_MEM;
        }
        ESP_LOGI(tag, "%s CREATED core=%d priority=%u stack_bytes=%" PRIu32 " PROVISIONAL/TBD-15",
                 spec.name, static_cast<int>(spec.core), static_cast<unsigned>(spec.priority), spec.stack_bytes);
    }
    started = true;
    xEventGroupSetBits(events, runtime_ready);
    return ESP_OK;
}
EventBits_t system_events() { return events ? (xEventGroupGetBits(events) & ~runtime_ready) : 0; }
esp_err_t with_i2c_transaction(I2cTransaction transaction, void* context) {
    if (!i2c_mutex) return ESP_ERR_INVALID_STATE;
    if (!transaction) return ESP_ERR_INVALID_ARG;
    if (xSemaphoreTake(i2c_mutex, pdMS_TO_TICKS(config::i2c_mutex_timeout_ms)) != pdTRUE) {
        i2c_timeouts.fetch_add(1);
        return ESP_ERR_TIMEOUT;
    }
    const auto result = transaction(context);
    xSemaphoreGive(i2c_mutex);
    if (result != ESP_OK) i2c_errors.fetch_add(1);
    return result;
}
void publish_imu(sampling::ImuSite site, const sampling::ImuSample& sample) {
    const auto i = static_cast<unsigned>(site);
    if (i >= sensors.imu.size()) return;
    portENTER_CRITICAL(&snapshot_lock);
    sensors.imu[i] = sample;
    portEXIT_CRITICAL(&snapshot_lock);
}
void publish_soil(unsigned channel, const sampling::SoilSample& sample) {
    if (channel >= sensors.soil.size()) return;
    portENTER_CRITICAL(&snapshot_lock);
    sensors.soil[channel] = sample;
    portEXIT_CRITICAL(&snapshot_lock);
}
sampling::SensorSnapshot sensor_snapshot() {
    portENTER_CRITICAL(&snapshot_lock);
    const auto copy = sensors;
    portEXIT_CRITICAL(&snapshot_lock);
    return copy;
}
risk_runtime::Snapshot risk_snapshot() {
    portENTER_CRITICAL(&snapshot_lock);
    const auto copy = risk_state;
    portEXIT_CRITICAL(&snapshot_lock);
    return copy;
}
void imu_notify_from_isr(void*) {
    // Attach only after start succeeds. No IRAM ISR service is installed here.
    const auto handle = handles[index(TaskId::Imu)];
    if (!handle) return;
    BaseType_t wake = pdFALSE;
    vTaskNotifyGiveFromISR(handle, &wake);
    portYIELD_FROM_ISR(wake);
}
} // namespace node::runtime
