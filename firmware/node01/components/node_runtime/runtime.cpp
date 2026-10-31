#include "node/runtime.hpp"
#include "node/runtime_config.hpp"
#include "node/runtime_policy.hpp"
#include "node/acquisition_policy.hpp"
#include "node/deferred_imu_notice.hpp"
#include "node/logic.hpp"
#include "node/ports.hpp"
#include "node/board.hpp"
#include "node/i2c_bus.hpp"
#include "node/timeout_budget.hpp"
#include "node/acquisition.hpp"
#include "node/imu_irq_policy.hpp"
#include "node/diagnostic_log.hpp"
#include "node/storage_recovery.hpp"
#include "node/storage_pressure.hpp"
#include "node/storage_latency.hpp"
#include "node/i2c_lock_trace.hpp"
#include "esp_heap_caps.h"
#include "node/sd_card.hpp"
#include "node/network.hpp"
#include "esp_app_desc.h"
#include "sdkconfig.h"
#ifdef CONFIG_NODE01_I2C_LOCK_DIAG_TRACE
#include "node/i2c_finite_trace.hpp"
#include "node/i2c_trace_output.hpp"
#endif
#include <cerrno>
#include <array>
#include <atomic>
#include <cinttypes>
#include <type_traits>
#include <limits>
#ifdef CONFIG_NODE01_SANDBOX_EXPERIMENT
#include "node/experiment_control.hpp"
#include "node/experiment_metadata.hpp"
#include "esp_random.h"
#include <cstdio>
#include <cstring>
#include <fcntl.h>
#include <unistd.h>
#endif
#include "driver/gpio.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "esp_system.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "freertos/task.h"

namespace node::runtime {
namespace {
using config::TaskId;
constexpr unsigned count = static_cast<unsigned>(TaskId::Count);
constexpr EventBits_t runtime_ready = 1U << 9;
constexpr EventBits_t slow_initialized = 1U << 10, capture_ready = 1U << 11;
constexpr EventBits_t imu_initialized = 1U << 12, startup_aborted = 1U << 13;
constexpr EventBits_t private_runtime_bits = runtime_ready | slow_initialized | capture_ready | imu_initialized | startup_aborted;
constexpr std::uint32_t producer_imu = 1U, producer_slow = 2U;
constexpr std::uint32_t producer_mask = config::sensors_enabled ? producer_imu | producer_slow : producer_imu;
constexpr const char* tag = "node_runtime";
EventGroupHandle_t events = nullptr;
SemaphoreHandle_t i2c_mutex = nullptr;
QueueHandle_t alarm_queue = nullptr;
QueueHandle_t storage_queue = nullptr;
drivers::I2cBus sensor_bus;
drivers::DualIcm42688 imus(sensor_bus);
drivers::SoilAds1115 adc(sensor_bus);
std::array<std::atomic<std::uint32_t>, 2> imu_valid{}, imu_failed{}, imu_no_data{}, imu_max_gap_us{};
std::array<std::atomic<std::uint32_t>, 3> soil_valid{}, soil_failed{};
std::atomic<std::uint32_t> storage_queue_drops{0}, acquisition_exhausted{0}, imu_deadline_misses{0};
std::atomic<std::uint32_t> records_produced{0}, records_enqueued{0}, records_dequeued{0}, storage_internal_drops{0}, storage_queue_peak{0};
std::atomic<std::uint32_t> records_storage_disabled{0};
std::atomic<std::uint32_t> storage_service_yields{0}, storage_service_sleep_us{0}, storage_catchup_grants{0};
std::atomic<std::uint32_t> imu_tick_no_delay{0}, imu_boundary_hits{0}, imu_cycle_over_budget{0};
std::atomic<std::uint32_t> imu_cycle_max_us{0}, imu_start_period_max_us{0};
std::array<std::atomic<std::uint32_t>, 2> imu_read_max_us{};
std::array<drivers::ImuDiagnostic, 2> imu_diagnostic_observation{}; // ImuTask writes under snapshot_lock
struct IrqObservation {
    std::uint32_t edges = 0, startup_edges = 0, capture_edges = 0, suppressed_unarmed = 0;
    std::uint32_t notify_claims = 0, notify_coalesced = 0;
    std::uint64_t last_edge_us = 0;
    bool enabled = false;
};
portMUX_TYPE irq_lock = portMUX_INITIALIZER_UNLOCKED;
std::array<IrqObservation, 2> imu_irqs{};
std::array<drivers::ImuIrqGate, 2> imu_irq_gates{}; // protected by irq_lock, including in ISR
bool imu_irqs_ready = false, gpio_service_owned = false;
std::array<std::atomic<std::uint32_t>, 2> imu_irq_services{}, imu_irq_empty{}, imu_irq_fallbacks{}, imu_irq_coalesced{};
// ImuTask is the sole writer; Health prints the first observations using the existing snapshot lock.
// No synchronous UART in the post-BEGIN sensor service loop.
std::array<policy::DeferredImuNotice, 2> imu_first_fallback{}, imu_first_read_error{};
std::atomic<std::uint32_t> imu_event_wakes{0};
std::array<std::atomic<std::uint32_t>, 2> imu_irq_consumed{}, imu_irq_stale{}, imu_irq_deferred{};
std::atomic<std::uint32_t> i2c_busy_us{0}, i2c_max_transfer_us{0};
std::atomic<std::uint32_t> i2c_lock_wait_us{0}, i2c_lock_wait_max_us{0};
std::array<TaskHandle_t, count> handles{};
std::array<std::atomic<std::uint32_t>, count> progress{};
std::atomic<std::uint32_t> queue_overflows{0}, i2c_errors{0}, i2c_timeouts{0};
std::atomic<std::uint32_t> risk_deadline_misses{0};
portMUX_TYPE snapshot_lock = portMUX_INITIALIZER_UNLOCKED;
struct ImuNoticeCritical {
    void lock() { portENTER_CRITICAL(&snapshot_lock); }
    void unlock() { portEXIT_CRITICAL(&snapshot_lock); }
} imu_notice_critical;
struct SnapshotMutex {
    portMUX_TYPE mux = portMUX_INITIALIZER_UNLOCKED;
    void lock() { portENTER_CRITICAL(&mux); }
    void unlock() { portEXIT_CRITICAL(&mux); }
};
policy::SnapshotStore<SnapshotMutex> sensor_store;
policy::DiagnosticSequence<SnapshotMutex> acquisition_sequence;
policy::CaptureWindow capture_window(config::capture_seconds); // protected by snapshot_lock
struct StorageObservation {
    storage::RecoveryStats stats{};
    bool active = false, pending = false, verifying = false, finished = false;
    std::array<storage::LogTiming, static_cast<unsigned>(storage::LogPhase::Count)> phases{};
} storage_observation;
enum class StorageIo : unsigned { Recover, Open, Append, Flush, Close, VerifyChunk, QueueWait, Count };
struct IoTiming { std::uint64_t calls = 0, failures = 0, total_us = 0; std::uint32_t max_us = 0; };
struct StorageIoObservation {
    std::array<IoTiming, static_cast<unsigned>(StorageIo::Count)> timing{};
    StorageIo in_flight = StorageIo::Count;
    std::uint64_t started_us = 0;
    StorageIo last_long_operation = StorageIo::Count;
    std::uint64_t last_long_started_us = 0, last_long_finished_us = 0, last_long_wall_us = 0, long_calls = 0;
} storage_io;
policy::StoragePressure storage_pressure(config::storage_pressure_high_rows, config::storage_pressure_low_rows); // snapshot_lock
// Separate diagnostic locks never surround SDK, FILE, Take/Give or UART.
portMUX_TYPE storage_trace_lock = portMUX_INITIALIZER_UNLOCKED;
policy::StorageLatency storage_latency;
portMUX_TYPE i2c_trace_lock = portMUX_INITIALIZER_UNLOCKED;
policy::I2cLockTrace i2c_lock_trace;
#ifdef CONFIG_NODE01_I2C_LOCK_DIAG_TRACE
#include "i2c_diagnostic_runtime.inc"
#endif
risk_runtime::Snapshot risk_state{};
bool started = false; // app_main is sole lifecycle owner
std::array<std::atomic<startup::InitState>, 2> imu_startup{{startup::InitState::Pending, startup::InitState::Pending}};
std::atomic<startup::InitState> slow_startup{startup::InitState::Pending};
std::atomic<bool> startup_failure_reported{false};
std::atomic<std::uint32_t> startup_parked{0};
enum class StartupStage : unsigned { Top, Toe, Ads, SdMount, SdOpen, Count };
struct StartupTiming { std::uint64_t begin_us = 0, end_us = 0; int result = ESP_ERR_INVALID_STATE; };
std::array<StartupTiming, static_cast<unsigned>(StartupStage::Count)> startup_timing{}; // snapshot_lock
#ifdef CONFIG_NODE01_SANDBOX_EXPERIMENT
#include "experiment_runtime.inc"
#endif
void startup_phase_begin(StartupStage stage) {
    const auto now = static_cast<std::uint64_t>(esp_timer_get_time());
    portENTER_CRITICAL(&snapshot_lock);
    auto& phase = startup_timing[static_cast<unsigned>(stage)];
    if (!phase.begin_us) phase.begin_us = now;
    portEXIT_CRITICAL(&snapshot_lock);
}
void startup_phase_end(StartupStage stage, int result) {
    const auto now = static_cast<std::uint64_t>(esp_timer_get_time());
    portENTER_CRITICAL(&snapshot_lock);
    auto& phase = startup_timing[static_cast<unsigned>(stage)];
    if (!phase.end_us) { phase.end_us = now; phase.result = result; }
    portEXIT_CRITICAL(&snapshot_lock);
}
void print_startup_timing() {
    std::array<StartupTiming, static_cast<unsigned>(StartupStage::Count)> copy;
    portENTER_CRITICAL(&snapshot_lock); copy = startup_timing; portEXIT_CRITICAL(&snapshot_lock);
    constexpr const char* names[]{"IMU_TOP", "IMU_TOE", "ADS", "SD_MOUNT", "SD_OPEN"};
    for (unsigned i = 0; i < copy.size(); ++i)
        ESP_LOGI(tag, "STARTUP_PHASE name=%s first_begin_us=%" PRIu64 " first_end_us=%" PRIu64 " result=%d; zero time=NOT_ATTEMPTED, wall includes preemption",
            names[i], copy[i].begin_us, copy[i].end_us, copy[i].result);
}
void abort_startup(const char* reason) {
#ifdef CONFIG_NODE01_SANDBOX_EXPERIMENT
    portENTER_CRITICAL(&snapshot_lock); experiment_session.fail(); portEXIT_CRITICAL(&snapshot_lock);
    if (!startup_failure_reported.load()) ESP_LOGE(tag,"EXPERIMENT_INIT_FAILED reason=%s",reason);
#endif
    xEventGroupSetBits(events, startup_aborted); // sticky, never cleared by a waiter
    if (!startup_failure_reported.exchange(true))
        ESP_LOGE(tag, "CAPTURE_START_BLOCKED reason=%s actual_us=%" PRIu64 "; no epoch/no records promised; await storage cleanup status",
            reason, static_cast<std::uint64_t>(esp_timer_get_time()));
}
[[noreturn]] void park_startup(TaskId task, const char* reason) {
    startup_parked.fetch_or(1U << static_cast<unsigned>(task));
    ESP_LOGW(tag, "STARTUP_TASK_PARKED task=%s reason=%s; explicit terminal startup state",
        config::tasks[static_cast<unsigned>(task)].name, reason);
    for (;;) vTaskDelay(pdMS_TO_TICKS(1000)); // keep handle valid; no retry or acquisition
}
bool wait_startup_stage(EventBits_t done, const char* reason) {
    const auto bits = xEventGroupWaitBits(events, done | startup_aborted, pdFALSE, pdFALSE,
        drivers::timing::guarded_wait_ticks(config::startup_timeout_ms, configTICK_RATE_HZ));
    if (bits & startup_aborted) return false;
    if (!(bits & done)) { abort_startup(reason); return false; }
    return true;
}
static_assert(std::is_trivially_copyable_v<risk_runtime::Snapshot>);
constexpr unsigned index(TaskId id) { return static_cast<unsigned>(id); }
void mark_progress(TaskId id) { progress[index(id)].fetch_add(1, std::memory_order_relaxed); }
void await_start() { xEventGroupWaitBits(events, runtime_ready, pdFALSE, pdTRUE, portMAX_DELAY); }
std::uint64_t uptime_ms() { return static_cast<std::uint64_t>(esp_timer_get_time()) / 1000; }
policy::CaptureObservation capture_observation() {
    portENTER_CRITICAL(&snapshot_lock);
    const auto value = capture_window.observation();
    portEXIT_CRITICAL(&snapshot_lock); return value;
}
bool capture_should_stop() {
    const auto now = static_cast<std::uint64_t>(esp_timer_get_time());
    portENTER_CRITICAL(&snapshot_lock);
    const bool stop = capture_window.poll(now);
#ifdef CONFIG_NODE01_SANDBOX_EXPERIMENT
    const bool first = stop && experiment_session.stop(now,experiment::Reason::TimeLimit);
#endif
    portEXIT_CRITICAL(&snapshot_lock);
#ifdef CONFIG_NODE01_SANDBOX_EXPERIMENT
    if (first) experiment_stop_log(now,experiment::Reason::TimeLimit);
#endif
    return stop;
}
template<class Prepare> bool begin_capture(Prepare prepare) {
    // Fix the previous fail-open timeout: no capture epoch or producer release
    // without SD mount+open. Failure cleanup stays with the StorageTask owner.
    bool storage_ready = !config::storage_enabled;
    if constexpr (config::storage_enabled) {
        const auto ready = xEventGroupWaitBits(events, event::SD_OK | startup_aborted, pdFALSE, pdFALSE,
            drivers::timing::guarded_wait_ticks(config::startup_timeout_ms, configTICK_RATE_HZ));
        storage_ready = (ready & event::SD_OK) != 0;
        if (!storage_ready) { abort_startup("SD_NOT_READY"); print_startup_timing(); return false; }
    }
    const auto gate = startup::capture_gate(config::startup_plan, config::sensors_enabled, config::storage_enabled,
        imu_startup[0].load(), imu_startup[1].load(), slow_startup.load(), storage_ready);
    if (!startup::may_begin_capture(gate, (xEventGroupGetBits(events) & startup_aborted) != 0)) {
        abort_startup("PREREQUISITE_NOT_READY"); print_startup_timing(); return false;
    }
    print_startup_timing(); // only after initialization, never between TOP/TOE
#ifdef CONFIG_NODE01_SANDBOX_EXPERIMENT
    const auto console_wait_begin = esp_timer_get_time();
    while (!experiment_console_initialized.load() && esp_timer_get_time()-console_wait_begin < 5000000) vTaskDelay(1);
    if (!experiment_console_ok.load()) { abort_startup("CONSOLE_INPUT_UNAVAILABLE"); return false; }
    portENTER_CRITICAL(&snapshot_lock);
    const bool armed = experiment_session.ready(gate == startup::Gate::Proceed,storage_ready,experiment_console_ok.load());
    portEXIT_CRITICAL(&snapshot_lock);
    if (!armed) { abort_startup("EXPERIMENT_READY_FAILED"); return false; }
    ESP_LOGW(tag,"EXPERIMENT_READY id=%s csv=%s range_s=30..300 calibration=NOT_READY; zero sensor rows until EXP START, reserved CSV header only",experiment_id,experiment_csv);
    while (experiment_observation().state == experiment::State::Ready) vTaskDelay(pdMS_TO_TICKS(100));
    const auto start_wait_begin = esp_timer_get_time();
    while (experiment_observation().state == experiment::State::StartPending && !experiment_start_storage_ok.load() &&
            esp_timer_get_time()-start_wait_begin < 5000000) vTaskDelay(1);
    const auto selected = experiment_observation();
    if (selected.state != experiment::State::StartPending || !experiment_start_storage_ok.load()) { abort_startup("EXPERIMENT_STORAGE_START_NOT_VERIFIED"); return false; }
#endif
    prepare(); // e.g. clear stale DRDY/arm only ready sites BEFORE the capture epoch
#ifdef CONFIG_NODE01_SANDBOX_EXPERIMENT
    for (unsigned i = 0; i < 2; ++i) if (imus.diagnostic(static_cast<sampling::ImuSite>(i)).drdy_arm_error != ESP_OK) {
        portENTER_CRITICAL(&irq_lock); for (auto& irq : imu_irq_gates) irq.stop(); portEXIT_CRITICAL(&irq_lock);
        for (int pin : {board::pin::imu_top_int1,board::pin::imu_toe_int1}) gpio_intr_disable(static_cast<gpio_num_t>(pin));
        abort_startup("IMU_STARTUP_STATUS_CLEAR_FAILED"); return false;
    }
#endif
    const auto now = static_cast<std::uint64_t>(esp_timer_get_time());
    portENTER_CRITICAL(&snapshot_lock);
#ifdef CONFIG_NODE01_SANDBOX_EXPERIMENT
    capture_window.configure_before_begin(selected.seconds);
    experiment_session.begin(now);
#endif
    capture_window.begin(now);
    portEXIT_CRITICAL(&snapshot_lock);
#ifdef CONFIG_NODE01_SANDBOX_EXPERIMENT
    const unsigned actual_seconds = selected.seconds;
#else
    constexpr unsigned actual_seconds = config::capture_seconds;
#endif
    ESP_LOGW(tag, "CAPTURE_BEGIN monotonic_us=%" PRIu64 " duration_s=%u source=%s; pre-start warmup is outside capture; no durability claim",
        now, actual_seconds, diagnostic::source(config::diagnostic_mode));
#ifdef CONFIG_NODE01_I2C_LOCK_DIAG_TRACE
    finite_locked([&]{finite_i2c_trace.begin(now);});
#endif
    xEventGroupSetBits(events, capture_ready);
#ifdef CONFIG_NODE01_SANDBOX_EXPERIMENT
    ESP_LOGW(tag,"EXPERIMENT_BEGIN id=%s monotonic_us=%" PRIu64 " requested_seconds=%u calibration=NOT_READY; UART operator latency not hardware sync",experiment_id,now,selected.seconds);
#endif
    return true;
}
bool begin_capture() { return begin_capture([] {}); }
void producer_stopped(std::uint32_t bit) {
    portENTER_CRITICAL(&snapshot_lock);
    capture_window.producer_done(bit);
#ifdef CONFIG_NODE01_SANDBOX_EXPERIMENT
    experiment_producers_done_us = esp_timer_get_time();
#endif
    portEXIT_CRITICAL(&snapshot_lock);
    ESP_LOGW(tag, "CAPTURE_PRODUCER_STOP bit=%lu actual_us=%" PRIu64 "; no further records from this producer",
        static_cast<unsigned long>(bit), static_cast<std::uint64_t>(esp_timer_get_time()));
    for (;;) vTaskDelay(pdMS_TO_TICKS(1000)); // keep handle valid for Health stack diagnostics
}
IrqObservation irq_observation(unsigned site) {
    portENTER_CRITICAL(&irq_lock);
    auto copy = imu_irqs[site];
    copy.enabled = imu_irq_gates[site].may_notify();
    copy.startup_edges = imu_irq_gates[site].startup_edges();
    copy.capture_edges = imu_irq_gates[site].capture_edges(copy.edges);
    portEXIT_CRITICAL(&irq_lock); return copy;
}
void cleanup_imu_irqs() {
    portENTER_CRITICAL(&irq_lock);
    for (auto& gate : imu_irq_gates) gate.stop();
    portEXIT_CRITICAL(&irq_lock);
    for (int pin : {board::pin::imu_top_int1, board::pin::imu_toe_int1}) {
        gpio_intr_disable(static_cast<gpio_num_t>(pin));
        if (imu_irqs_ready) gpio_isr_handler_remove(static_cast<gpio_num_t>(pin));
    }
    imu_irqs_ready = false;
    if (gpio_service_owned) { gpio_uninstall_isr_service(); gpio_service_owned = false; }
}
esp_err_t setup_imu_irqs() {
    gpio_config_t pins{};
    pins.pin_bit_mask = (1ULL << board::pin::imu_top_int1) | (1ULL << board::pin::imu_toe_int1);
    // GPIO handler installation must not arm either sensor before its init,
    // register readback and pre-capture INT_STATUS clearing have succeeded.
    pins.mode = GPIO_MODE_INPUT; pins.intr_type = GPIO_INTR_DISABLE;
    pins.pull_up_en = GPIO_PULLUP_DISABLE; pins.pull_down_en = GPIO_PULLDOWN_DISABLE;
    auto result = gpio_config(&pins);
    if (result != ESP_OK) return result;
    result = gpio_install_isr_service(0); // SDK-managed ISR; callback never accesses I2C/SD
    if (result == ESP_OK) gpio_service_owned = true;
    else if (result != ESP_ERR_INVALID_STATE) return result;
    result = gpio_isr_handler_add(static_cast<gpio_num_t>(board::pin::imu_top_int1), imu_notify_from_isr, nullptr);
    if (result == ESP_OK) result = gpio_isr_handler_add(static_cast<gpio_num_t>(board::pin::imu_toe_int1),
        imu_notify_from_isr, reinterpret_cast<void*>(std::uintptr_t{1}));
    for (int pin : {board::pin::imu_top_int1, board::pin::imu_toe_int1})
        gpio_intr_disable(static_cast<gpio_num_t>(pin)); // handler_add may enable the GPIO mask
    if (result != ESP_OK) {
        gpio_isr_handler_remove(static_cast<gpio_num_t>(board::pin::imu_top_int1));
        gpio_isr_handler_remove(static_cast<gpio_num_t>(board::pin::imu_toe_int1));
        cleanup_imu_irqs(); return result;
    }
    imu_irqs_ready = true; return ESP_OK;
}
void set_observed(EventBits_t bit, bool ok) {
    if (ok) xEventGroupSetBits(events, bit); else xEventGroupClearBits(events, bit);
}
void update_max(std::atomic<std::uint32_t>& target, std::uint32_t value) {
    auto old = target.load();
    while (old < value && !target.compare_exchange_weak(old, value)) {}
}
std::uint32_t bounded_us(std::uint64_t value) {
    return value > UINT32_MAX ? UINT32_MAX : static_cast<std::uint32_t>(value);
}
policy::IoSpan begin_io(StorageIo operation) {
    const auto now = static_cast<std::uint64_t>(esp_timer_get_time());
    const auto depth = uxQueueMessagesWaiting(storage_queue);
    portENTER_CRITICAL(&storage_trace_lock);
    const auto span = storage_latency.begin(static_cast<unsigned>(operation), now, depth, storage_catchup_grants.load());
    portEXIT_CRITICAL(&storage_trace_lock);
    portENTER_CRITICAL(&snapshot_lock);
    storage_io.in_flight = operation; storage_io.started_us = now;
    portEXIT_CRITICAL(&snapshot_lock);
    return span;
}
void end_io(StorageIo operation, bool success, const policy::IoSpan& span, policy::StoragePhaseDelta phases = {}) {
    const auto finished_us = static_cast<std::uint64_t>(esp_timer_get_time());
    const auto elapsed = finished_us - span.started_us;
    const auto depth = uxQueueMessagesWaiting(storage_queue);
    const auto priority = elapsed >= config::storage_long_io_us ? uxTaskPriorityGet(nullptr) : 0;
    const auto core = static_cast<unsigned>(xPortGetCoreID());
    portENTER_CRITICAL(&storage_trace_lock);
    storage_latency.end(span, finished_us, depth, success, phases, priority, core);
    portEXIT_CRITICAL(&storage_trace_lock);
    portENTER_CRITICAL(&snapshot_lock);
    auto& value = storage_io.timing[static_cast<unsigned>(operation)];
    ++value.calls; if (!success) ++value.failures;
    value.total_us += elapsed;
    if (elapsed > value.max_us) value.max_us = bounded_us(elapsed);
    if (operation != StorageIo::QueueWait && elapsed >= config::storage_long_io_us) {
        ++storage_io.long_calls; storage_io.last_long_operation = operation;
        storage_io.last_long_started_us = span.started_us; storage_io.last_long_finished_us = finished_us;
        storage_io.last_long_wall_us = elapsed;
    }
    // recover() calls open_next(): restore the inclusive outer context instead
    // of clearing it while recovery is still executing/logging.
    storage_io.in_flight = static_cast<StorageIo>(span.previous_operation);
    storage_io.started_us = span.previous_started_us;
    portEXIT_CRITICAL(&snapshot_lock);
}
void observe_storage_queue(UBaseType_t depth, bool dropped, bool has_index, std::uint64_t acquisition_index = 0) {
    policy::StorageQueueSample sample;
    sample.acquisition_index = acquisition_index;
    sample.depth = depth; sample.dropped = dropped; sample.has_index = has_index;
    // Fixed-size bookkeeping only; no UART, SD, allocation or waiting here.
    portENTER_CRITICAL(&snapshot_lock);
    sample.observed_us = esp_timer_get_time(); // serialize diagnostic clock with state transitions
    sample.io_operation = static_cast<unsigned>(storage_io.in_flight);
    sample.io_started_us = storage_io.in_flight == StorageIo::Count ? 0 : storage_io.started_us;
    storage_pressure.observe(sample);
    portEXIT_CRITICAL(&snapshot_lock);
}
void enqueue_record(sampling::AcquisitionRecord& record) {
    records_produced.fetch_add(1);
    if constexpr (!config::storage_enabled) {
        records_storage_disabled.fetch_add(1); // TEST_ONLY intentional suppression, not a queue overflow
        return;
    }
    const auto result = policy::enqueue_record(record, acquisition_sequence, [](const auto& value) {
        return xQueueSend(storage_queue, &value, 0) == pdTRUE;
    });
    if (result == policy::QueueResult::Accepted) {
        records_enqueued.fetch_add(1);
        const auto depth = uxQueueMessagesWaiting(storage_queue);
        update_max(storage_queue_peak, depth);
        observe_storage_queue(depth, false, true, record.acquisition_index);
    }
    if (result == policy::QueueResult::QueueFull) {
        storage_queue_drops.fetch_add(1); update_max(storage_queue_peak, config::storage_queue_length);
        observe_storage_queue(uxQueueMessagesWaiting(storage_queue), true, true, record.acquisition_index);
    }
    if (result == policy::QueueResult::IndexExhausted) acquisition_exhausted.fetch_add(1);
}

void imu_task(void*) {
    await_start();
    std::array<bool, 2> initialized{};
    for (unsigned i = 0; i < 2; ++i) {
        const auto stage = i ? StartupStage::Toe : StartupStage::Top;
        startup_phase_begin(stage);
        const auto e = imus.initialize(static_cast<sampling::ImuSite>(i), drivers::imu_odr_hz, imu_irqs_ready);
        startup_phase_end(stage, e);
        initialized[i] = e == ESP_OK;
        imu_startup[i] = initialized[i] ? startup::InitState::Ready : startup::InitState::Failed;
        portENTER_CRITICAL(&irq_lock);
        imu_irq_gates[i].initialized(initialized[i]);
        portEXIT_CRITICAL(&irq_lock);
        const auto& init_diagnostic = imus.diagnostic(static_cast<sampling::ImuSite>(i));
        portENTER_CRITICAL(&snapshot_lock);
        imu_diagnostic_observation[i] = init_diagnostic;
        portEXIT_CRITICAL(&snapshot_lock);
        ESP_LOGI(tag, "IMU_%s_INIT %s addr=0x%02x WHO_AM_I_expected=0x47 odr=%uHz FS=16g/2000dps i2c_profile=TDK_12.3 init_cause=%s bank_restore=%s",
            i ? "TOE" : "TOP", esp_err_to_name(e),
            i ? board::bus::imu_toe_address : board::bus::imu_top_address, drivers::imu_odr_hz,
            esp_err_to_name(init_diagnostic.init_error), esp_err_to_name(init_diagnostic.bank_restore_error));
        const auto& rb = init_diagnostic.init_readback;
        ESP_LOGI(tag, "IMU_READBACK site=%s complete=%d drdy=%d gyro=0x%02x accel=0x%02x pwr=0x%02x clk=0x%02x int=0x%02x clear=0x%02x async=0x%02x source=0x%02x",
            i ? "TOE" : "TOP", rb.complete, rb.drdy_requested, rb.gyro_config0, rb.accel_config0,
            rb.pwr_mgmt0, rb.intf_config1, rb.int_config, rb.int_config0, rb.int_config1, rb.int_source0);
    }
    // Publish completion before waiting for ADS/SD; B must never form an
    // IMU->SD->ADS->IMU wait cycle. Per-device success is stored separately.
    xEventGroupSetBits(events, imu_initialized);
    if constexpr (config::startup_plan == startup::Plan::ImuFirst) {
        if (startup::slow_gate(config::startup_plan, imu_startup[0].load(), imu_startup[1].load()) != startup::Gate::Proceed)
            abort_startup("IMU_INIT_FAILED");
    }
    // Emit the extra UART evidence only AFTER both original init sequences:
    // do not insert a long trace print between TOP and TOE initialization.
    for (unsigned i = 0; i < 2; ++i) {
        // Fixed startup-only evidence; no extra I2C request, retry or capture
        // record. Trace data stays in the driver, out of 100Hz/Health copies.
        const auto& trace = imus.initialization_diagnostic(static_cast<sampling::ImuSite>(i));
        ESP_LOGI(tag, "IMU_INIT_TRACE site=%s phase=%s transfers=%lu who_observed=%d actual_who=0x%02x first_failure=%d bank_restore_attempted=%d; actual_who meaningful only if observed",
            i ? "TOE" : "TOP", drivers::imu_init_phase_name(trace.phase), static_cast<unsigned long>(trace.transfers),
            trace.who_observed, trace.actual_who, trace.first_failure_present, trace.bank_restore_attempted);
        auto print_init_access = [&](const char* label, const drivers::ImuInitAccess& access) {
            ESP_LOGI(tag, "%s site=%s phase=%s op=%c reg=0x%02x len=%u value=0x%02x value_observed=%d validation_error=%d error=%d start_us=%" PRIu64 " end_us=%" PRIu64 "; W value=requested, failed R has no observed value; RegisterBus boundary",
                label, i ? "TOE" : "TOP", drivers::imu_init_phase_name(access.phase), access.operation, access.reg,
                static_cast<unsigned>(access.length), access.value, access.value_observed, access.validation_error,
                access.error, access.started_us, access.finished_us);
        };
        for (unsigned entry = 0; entry < trace.critical_size; ++entry)
            print_init_access("IMU_INIT_ACCESS", trace.critical[entry]);
        if (trace.first_failure_present) print_init_access("IMU_INIT_FIRST_FAILURE", trace.first_failure);
    }
    if (!wait_startup_stage(slow_initialized, "ADS_INIT_NOT_COMPLETED")) {
        print_startup_timing(); park_startup(TaskId::Imu, "PREREQUISITE_BLOCKED");
    }
    const bool capture_started = begin_capture([&] {
        for (unsigned i = 0; i < 2; ++i) {
            const auto site = static_cast<sampling::ImuSite>(i);
            const auto pin = static_cast<gpio_num_t>(i ? board::pin::imu_toe_int1 : board::pin::imu_top_int1);
            auto armed = ESP_ERR_INVALID_STATE;
            if (imu_irqs_ready && initialized[i]) {
                armed = imus.prepare_drdy(site);
                if (armed == ESP_OK) {
                    portENTER_CRITICAL(&irq_lock);
                    imu_irq_gates[i].arm_result(true);
                    portEXIT_CRITICAL(&irq_lock);
                    armed = gpio_set_intr_type(pin, GPIO_INTR_POSEDGE);
                    if (armed == ESP_OK) armed = gpio_intr_enable(pin);
                }
                if (armed != ESP_OK) {
                    gpio_intr_disable(pin);
                    portENTER_CRITICAL(&irq_lock);
                    imu_irq_gates[i].arm_result(false);
                    portEXIT_CRITICAL(&irq_lock);
                }
            }
            portENTER_CRITICAL(&snapshot_lock);
            imu_diagnostic_observation[i] = imus.diagnostic(site);
            portEXIT_CRITICAL(&snapshot_lock);
            const auto& d = imus.diagnostic(site);
            if (imu_irqs_ready)
                ESP_LOGW(tag, "IMU_IRQ_ARM site=%s init_ok=%d result=%s startup_status_seen=%d status=0x%02x; failed sites stay IRQ-disabled with explicit 100Hz Error/polling diagnostics",
                    i ? "TOE" : "TOP", initialized[i], esp_err_to_name(armed),
                    d.startup_status_observed, d.startup_status);
        }
        // A startup notification is not a capture sample. Keep lifetime edge
        // evidence, but do not amplify an unready device or include warmup
        // edges in the capture coalescence/rate window.
        xTaskNotifyStateClear(nullptr);
        ulTaskNotifyValueClear(nullptr, 3U);
        portENTER_CRITICAL(&irq_lock);
        for (unsigned i = 0; i < 2; ++i) imu_irq_gates[i].begin_capture(imu_irqs[i].edges);
        portEXIT_CRITICAL(&irq_lock);
    });
    if (!capture_started) park_startup(TaskId::Imu, "CAPTURE_START_BLOCKED");
    std::array<std::uint64_t, 2> last_valid{};
    std::array<sampling::ImuSample, 2> staged{};
    std::array<policy::EdgeCursor, 2> edge_cursor{};
    for (unsigned i = 0; i < 2; ++i) edge_cursor[i].consume(irq_observation(i).startup_edges);
    std::array<policy::IrqFallback, 2> fallback_policy{};
    auto read_site = [&](unsigned i, bool from_irq) {
        const auto site = static_cast<sampling::ImuSite>(i);
        sampling::AcquisitionRecord record;
        record.channel = i; record.attempted_uptime_us = esp_timer_get_time();
        const auto result = imus.read(site, record.imu);
        portENTER_CRITICAL(&snapshot_lock);
        imu_diagnostic_observation[i] = imus.diagnostic(site);
        portEXIT_CRITICAL(&snapshot_lock);
        update_max(imu_read_max_us[i], bounded_us(esp_timer_get_time() - record.attempted_uptime_us));
        if (result == PortStatus::Unavailable) {
            imu_no_data[i].fetch_add(1);
            if (from_irq) imu_irq_empty[i].fetch_add(1);
            if (record.attempted_uptime_us - last_valid[i] > config::imu_liveness_us) staged[i] = {};
            return; // a notification/edge is never promoted to an invented sample
        }
        record.error = imus.diagnostic(site).error;
        if (result == PortStatus::Ready) {
            record.imu_raw = imus.diagnostic(site).raw;
            const auto now = *record.imu.acquired_uptime_us;
            if (last_valid[i]) update_max(imu_max_gap_us[i], bounded_us(now - last_valid[i]));
            last_valid[i] = now; imu_valid[i].fetch_add(1);
        } else if (imu_failed[i].fetch_add(1) == 0) {
            imu_first_read_error[i].record(imu_notice_critical, record.attempted_uptime_us, record.error, initialized[i]);
        }
        staged[i] = record.imu; enqueue_record(record);
    };
    TickType_t last_wake = xTaskGetTickCount();
    std::uint64_t previous_start = 0;
    for (;;) {
        if (capture_should_stop()) {
            portENTER_CRITICAL(&irq_lock);
            for (auto& gate : imu_irq_gates) gate.stop();
            portEXIT_CRITICAL(&irq_lock);
            for (int pin : {board::pin::imu_top_int1, board::pin::imu_toe_int1})
                if (imu_irqs_ready) gpio_intr_disable(static_cast<gpio_num_t>(pin));
            producer_stopped(producer_imu);
        }
        const auto cycle_start = static_cast<std::uint64_t>(esp_timer_get_time());
        if (previous_start) update_max(imu_start_period_max_us, bounded_us(cycle_start - previous_start));
        previous_start = cycle_start;
        std::uint64_t notification_wait_us = 0;
        policy::ImuFrameBudget frame_budget;
        if (imu_irqs_ready) {
            std::uint32_t irq_mask = 0;
            portENTER_CRITICAL(&irq_lock);
            for (unsigned i = 0; i < 2; ++i) {
                imu_irq_gates[i].begin_service_frame();
                if (initialized[i] && imu_irq_gates[i].may_notify()) irq_mask |= 1U << i;
            }
            portEXIT_CRITICAL(&irq_lock);
            auto service_irq = [&](unsigned i) {
                if (capture_should_stop()) return;
                const auto irq = irq_observation(i);
                if (!irq.enabled || !initialized[i]) return;
                if (!frame_budget.may_read(i)) {
                    imu_irq_deferred[i].fetch_add(1); // cursor retains edges for next frame
                    return;
                }
                const auto delta = edge_cursor[i].consume(irq.edges);
                if (!delta) { imu_irq_stale[i].fetch_add(1); return; }
                frame_budget.claim(i);
                imu_irq_consumed[i].fetch_add(delta);
                fallback_policy[i].observed_edge();
                if (delta > 1) imu_irq_coalesced[i].fetch_add(delta - 1);
                imu_irq_services[i].fetch_add(1); read_site(i, true);
            };
            // A latched DRDY may have arrived after last frame's read and been
            // notification-coalesced. It need not produce another physical edge.
            // Preserve that raw pending hint across frames, then check real status.
            for (unsigned i = 0; i < 2; ++i)
                if ((irq_mask & (1U << i)) && edge_cursor[i].pending(irq_observation(i).edges)) service_irq(i);
            const TickType_t due = last_wake + pdMS_TO_TICKS(config::imu_period_ms);
            for (;;) {
                const auto left = policy::remaining_ticks(xTaskGetTickCount(), due);
                if (!left || !frame_budget.awaiting(irq_mask) || capture_should_stop()) break;
                std::uint32_t bits = 0;
                const auto wait_start = static_cast<std::uint64_t>(esp_timer_get_time());
                const auto notified = xTaskNotifyWait(0, 3U, &bits, left);
                notification_wait_us += esp_timer_get_time() - wait_start;
                if (notified != pdTRUE) break;
                imu_event_wakes.fetch_add(1);
                for (unsigned i = 0; i < 2; ++i) if (bits & (1U << i)) service_irq(i);
            }
            // Missing/miswired INT1 cannot silently masquerade as a working
            // event path. Poll the latest real status after an explicit age
            // timeout; no duplicated values or reconstructed timestamps.
            const auto now = static_cast<std::uint64_t>(esp_timer_get_time());
            for (unsigned i = 0; i < 2; ++i) if (!capture_should_stop() && frame_budget.may_read(i) &&
                    fallback_policy[i].poll_needed(now, last_valid[i], config::imu_irq_fallback_age_us)) {
                if (imu_irq_fallbacks[i].fetch_add(1) == 0)
                    imu_first_fallback[i].record(imu_notice_critical, esp_timer_get_time(), ESP_OK, initialized[i]);
                frame_budget.claim(i); // fallback and IRQ share the one-attempt quota
                read_site(i, false);
            }
        } else for (unsigned i = 0; i < 2 && !capture_should_stop(); ++i) read_site(i, false);
        publish_imus(staged); // both sites committed together, preserving their actual times
        for (unsigned i = 0; i < 2; ++i)
            set_observed(i ? event::IMU_TOE_OK : event::IMU_TOP_OK, staged[i].validity == sampling::Validity::Valid);
        mark_progress(TaskId::Imu);
        const auto work_us = static_cast<std::uint64_t>(esp_timer_get_time()) - cycle_start - notification_wait_us;
        update_max(imu_cycle_max_us, bounded_us(work_us));
        if (work_us > config::imu_period_ms * 1000ULL) imu_cycle_over_budget.fetch_add(1);
        const bool delayed = xTaskDelayUntil(&last_wake, pdMS_TO_TICKS(config::imu_period_ms)) == pdTRUE;
        if (!delayed) imu_tick_no_delay.fetch_add(1); // raw SDK return, not synonymous with a deadline miss
        const auto outcome = policy::period_outcome(delayed, last_wake, xTaskGetTickCount());
        if (outcome == policy::PeriodOutcome::Boundary) imu_boundary_hits.fetch_add(1);
        if (outcome == policy::PeriodOutcome::Late) {
            imu_deadline_misses.fetch_add(1);
            vTaskDelay(1);
            policy::rebase_after_yield(last_wake, xTaskGetTickCount());
        }
    }
}
void storage_test_producer(void*) {
    await_start();
    if (!begin_capture()) park_startup(TaskId::Imu, "CAPTURE_START_BLOCKED");
    ESP_LOGW(tag, "STORAGE_TEST source=SYNTHETIC TEST_ONLY target_records_per_s=206; no sensor I/O, no algorithm input");
    TickType_t last_wake = xTaskGetTickCount();
    std::uint32_t cycle = 0;
    for (;;) {
        if (capture_should_stop()) producer_stopped(producer_imu);
        for (unsigned channel = 0; channel < 2; ++channel) {
            sampling::AcquisitionRecord record;
            record.channel = channel;
            record.attempted_uptime_us = esp_timer_get_time();
            record.imu.validity = sampling::Validity::Valid; // SYNTHETIC, never a real observation
            record.imu.acquired_uptime_us = record.attempted_uptime_us;
            // Nonzero, wide numeric fields avoid an artificially cheap all-zero
            // CSV load. These deterministic values are NOT physical sensor data.
            for (unsigned axis = 0; axis < 6; ++axis)
                record.imu_raw[axis] = static_cast<std::int16_t>((axis % 2 ? -1 : 1) *
                    static_cast<int>(12000 + (cycle + axis * 97) % 16000));
            for (unsigned axis = 0; axis < 3; ++axis) {
                record.imu.acceleration_mps2[axis] = record.imu_raw[axis] * drivers::standard_gravity / drivers::accel_lsb_per_g;
                record.imu.angular_rate_dps[axis] = record.imu_raw[axis + 3] / drivers::gyro_lsb_per_dps;
            }
            enqueue_record(record);
        }
        for (unsigned channel = 0; channel < diagnostic::probe_soil_records(cycle); ++channel) {
            sampling::AcquisitionRecord record;
            record.kind = sampling::RecordKind::Soil;
            record.channel = channel;
            record.attempted_uptime_us = esp_timer_get_time();
            record.soil.validity = sampling::Validity::Valid; // SYNTHETIC, file header marks every segment
            record.soil.acquired_uptime_us = record.attempted_uptime_us;
            record.soil.raw = static_cast<std::int16_t>(15000 + cycle % 16000);
            enqueue_record(record);
        }
        ++cycle;
        mark_progress(TaskId::Imu); // same task slot; logs explicitly label synthetic timing
        const bool delayed = xTaskDelayUntil(&last_wake, pdMS_TO_TICKS(config::imu_period_ms)) == pdTRUE;
        if (policy::period_outcome(delayed, last_wake, xTaskGetTickCount()) == policy::PeriodOutcome::Late) {
            imu_deadline_misses.fetch_add(1);
            vTaskDelay(1); policy::rebase_after_yield(last_wake, xTaskGetTickCount());
        }
    }
}
void slow_task(void*) {
    await_start();
    if constexpr (config::startup_plan == startup::Plan::ImuFirst) {
        if (!wait_startup_stage(imu_initialized, "IMU_INIT_NOT_COMPLETED") ||
            startup::slow_gate(config::startup_plan, imu_startup[0].load(), imu_startup[1].load()) != startup::Gate::Proceed) {
            abort_startup("IMU_PREREQUISITE_FAILED"); park_startup(TaskId::SlowSensor, "IMU_PREREQUISITE_FAILED");
        }
    }
    startup_phase_begin(StartupStage::Ads);
    const auto init = adc.initialize();
    startup_phase_end(StartupStage::Ads, init);
    slow_startup = init == ESP_OK ? startup::InitState::Ready : startup::InitState::Failed;
    ESP_LOGI(tag, "ADS1115_INIT %s PGA=+/-%umV SPS=%u calibration=TODO_CALIBRATION",
        esp_err_to_name(init), drivers::ads_pga_mv, drivers::ads_sps);
    xEventGroupSetBits(events, slow_initialized);
    if constexpr (config::startup_plan == startup::Plan::ImuFirst)
        if (init != ESP_OK) abort_startup("ADS_INIT_FAILED");
    const auto released = xEventGroupWaitBits(events, capture_ready | startup_aborted, pdFALSE, pdFALSE, portMAX_DELAY);
    if (released & startup_aborted) park_startup(TaskId::SlowSensor, "CAPTURE_START_BLOCKED");
    TickType_t last_wake = xTaskGetTickCount();
    auto next_init_us = static_cast<std::uint64_t>(esp_timer_get_time()) + config::sensor_retry_ms * 1000ULL;
    for (;;) {
        if (capture_should_stop()) producer_stopped(producer_slow);
        if (adc.status() != PortStatus::Ready && static_cast<std::uint64_t>(esp_timer_get_time()) >= next_init_us) {
            const auto error = adc.initialize();
            ESP_LOGW(tag, "ADS1115_REINIT %s", esp_err_to_name(error));
            next_init_us = esp_timer_get_time() + config::sensor_retry_ms * 1000ULL;
        }
        bool all_ok = true;
        std::array<sampling::SoilSample, 3> staged{};
        for (unsigned channel = 0; channel < 3; ++channel) {
            if (capture_should_stop()) break; // complete an in-flight conversion, never start a new one after cutoff
            sampling::AcquisitionRecord record;
            record.kind = sampling::RecordKind::Soil;
            record.channel = channel;
            record.attempted_uptime_us = esp_timer_get_time();
            const bool initialized = adc.status() == PortStatus::Ready;
#ifdef CONFIG_NODE01_I2C_LOCK_DIAG_TRACE
            finite_ads_begin(channel);
#endif
            auto state = initialized ? adc.start_conversion(channel) : PortStatus::Error;
            const char* failure_stage = initialized ? "start_conversion" : "init_unready";
            if (state == PortStatus::Ready) {
                failure_stage = "poll_or_result"; // API error can be bus/lock, not just ADC deadline
#ifdef CONFIG_NODE01_I2C_LOCK_DIAG_TRACE
                finite_ads_stage=2;
#endif
                const auto conversion = policy::wait_conversion(adc, record.soil,
                    drivers::ads_conversion_timeout_us, config::ads_max_polls,
                    [] { return static_cast<std::uint64_t>(esp_timer_get_time()); }, [] { vTaskDelay(1); });
                state = conversion.status;
                if (conversion.timed_out) { failure_stage = "conversion_deadline"; adc.cancel_conversion(ESP_ERR_TIMEOUT); }
            }
            if (state != PortStatus::Ready) {
                record.soil = {}; record.soil.validity = sampling::Validity::Error;
                all_ok = false;
                if (soil_failed[channel].fetch_add(1) == 0)
                    ESP_LOGE(tag, "SOIL_READ channel=%u stage=%s error=%s", channel,
                        failure_stage,
                        esp_err_to_name(initialized ? adc.last_error() : adc.last_init_error()));
            } else soil_valid[channel].fetch_add(1);
            record.error = initialized ? adc.last_error() : adc.last_init_error();
#ifdef CONFIG_NODE01_I2C_LOCK_DIAG_TRACE
            finite_ads_end(record.error,state);
#endif
            staged[channel] = record.soil;
            enqueue_record(record);
        }
        publish_soils(staged); // three-channel sweep is a logical group, not simultaneous acquisition
        set_observed(event::SOIL_OK, all_ok);
        mark_progress(TaskId::SlowSensor);
        const bool delayed = xTaskDelayUntil(&last_wake, pdMS_TO_TICKS(config::soil_period_ms)) == pdTRUE;
        if (policy::period_outcome(delayed, last_wake, xTaskGetTickCount()) == policy::PeriodOutcome::Late) {
            vTaskDelay(1); policy::rebase_after_yield(last_wake, xTaskGetTickCount());
        }
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
        const bool delayed = xTaskDelayUntil(&last_wake, pdMS_TO_TICKS(config::risk_period_ms)) == pdTRUE;
        if (policy::period_outcome(delayed, last_wake, xTaskGetTickCount()) == policy::PeriodOutcome::Late) {
            risk_deadline_misses.fetch_add(1, std::memory_order_relaxed);
            vTaskDelay(1); // no CPU burst while trying to catch up missed 20 Hz deadlines
            policy::rebase_after_yield(last_wake, xTaskGetTickCount());
        }
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
#ifdef CONFIG_NODE01_NETWORK_ENABLE
void comm_task(void*) {
    await_start();
    static comm::Network network;
    const auto init = network.start();
    if (init != ESP_OK) ESP_LOGE(tag, "COMM_BLOCKED %s; provisioning/identity required; sampling continues", esp_err_to_name(init));
    unsigned cycles = 0;
    for (;;) {
        network.poll(sensor_snapshot(), (system_events() & event::SD_OK) != 0);
        set_observed(event::WIFI_UP, network.wifi_up());
        set_observed(event::MQTT_UP, network.mqtt_up());
        if (++cycles % 40 == 0) ESP_LOGI(tag, "COMM wifi=%d mqtt=%d enqueued=%lu rejected=%lu edge_online=false; no durable receipt",
            network.wifi_up(), network.mqtt_up(), static_cast<unsigned long>(network.enqueued()),
            static_cast<unsigned long>(network.rejected()));
        mark_progress(TaskId::CommSupervisor);
        vTaskDelay(pdMS_TO_TICKS(250));
    }
}
#endif
void storage_task(void*) {
    await_start();
    if constexpr (config::startup_plan == startup::Plan::ImuFirst) {
        if (!wait_startup_stage(slow_initialized, "SENSORS_INIT_NOT_COMPLETED") ||
            startup::storage_gate(config::startup_plan, imu_startup[0].load(), imu_startup[1].load(), slow_startup.load()) != startup::Gate::Proceed) {
            abort_startup("SENSOR_PREREQUISITE_FAILED");
            ESP_LOGW(tag, "STARTUP_ABORT_NO_SD_IO; SD mount/open never started, capture not begun");
            park_startup(TaskId::Storage, "SENSOR_PREREQUISITE_FAILED");
        }
    }
    // Fixed batch writer/reader buffers stay off the task stack.
    static storage::SdCard card;
    static storage::DiagnosticLog log([]() -> std::uint64_t { return esp_timer_get_time(); });
    static char metadata[1280];
    char elf_hash[65]{};
    const auto* app = esp_app_get_description();
    for (unsigned i = 0; i < sizeof(app->app_elf_sha256); ++i)
        std::snprintf(elf_hash + 2*i, 3, "%02x", app->app_elf_sha256[i]);
    const int metadata_size = std::snprintf(metadata, sizeof(metadata),
#ifdef CONFIG_NODE01_SANDBOX_EXPERIMENT
        "# diagnostic_default_seconds=%u; actual_experiment_duration=SEE_BEG_END_SIDECARS; verification=%s; imu_acquisition=%s; sd_clock_hardware=NEED_HARDWARE_RETEST\n"
#else
        "# capture_seconds=%u; verification=%s; imu_acquisition=%s; sd_clock_hardware=NEED_HARDWARE_RETEST\n"
#endif
        "# mode=%s; source=%s; purpose=ENGINEERING_DIAGNOSTIC_TEST_ONLY; app_elf_sha256=%s\n"
        "# flush_rows=%u; segment_rows=%u; write_buffer_bytes=%u; read_quantum_bytes=%u; queue_rows=%u; power_loss_safety=NOT_VERIFIED\n"
        "# firmware=%s; idf=%s; device=NODE-01; boot_id=unavailable; coordinate=sensor_axes_unmapped\n"
        "# i2c_hz=%d; sd_khz=%d; imu_odr_hz=%u; accel_fs_g=16; gyro_fs_dps=2000; gravity=9.80665; gyro_lsb_per_dps=16.4\n"
        "# gyro_config1=0x16; gyro_accel_config0=0x11; accel_config1=0x0d; factory_AAF; filter_not_calibrated\n"
        "# ads_pga_mv=%u; ads_sps=%u; soil_period_ms=%u; per_channel_time=%s; utc=unavailable\n",
        config::capture_seconds, config::capture_seconds ? "POST_CAPTURE_SINGLE_FILE" : "INTERLEAVED_SEGMENTS",
        config::imu_drdy_enabled ? "DRDY_WITH_EXPLICIT_FALLBACK" : "POLLING_OR_SYNTHETIC",
        diagnostic::name(config::diagnostic_mode), diagnostic::source(config::diagnostic_mode), elf_hash,
        config::storage_flush_rows, config::effective_storage_segment_rows,
        static_cast<unsigned>(storage::DiagnosticLog::write_buffer_bytes), static_cast<unsigned>(storage::IncrementalVerifier::read_quantum),
        static_cast<unsigned>(config::storage_queue_length),
        app->version, app->idf_ver, CONFIG_NODE01_I2C_HZ, CONFIG_NODE01_SD_KHZ,
        drivers::imu_odr_hz, drivers::ads_pga_mv, drivers::ads_sps, config::soil_period_ms,
        diagnostic::time_source(config::diagnostic_mode));
    if (metadata_size < 0 || static_cast<std::size_t>(metadata_size) >= sizeof(metadata)) {
        ESP_LOGE(tag, "STORAGE_BLOCKED diagnostic metadata overflow; no unlabelled file created");
#ifdef CONFIG_NODE01_SANDBOX_EXPERIMENT
        abort_startup("CSV_HEADER_METADATA_OVERFLOW");
        park_startup(TaskId::Storage,"CSV_HEADER_METADATA_OVERFLOW"); // valid task handle for Health
#else
        vTaskDelete(nullptr); return;
#endif
    }
    class SdBackend final : public storage::Backend {
    public:
        SdBackend(storage::SdCard& card, storage::DiagnosticLog& log, const char* metadata)
            : card_(card), log_(log), metadata_(metadata) {}
        bool recover() override {
            const auto started = begin_io(StorageIo::Recover);
            abort_verification();
            log_.abandon();
            const auto reset = card_.reset();
            if (reset != ESP_OK) {
                error_ = reset; error_domain_ = "esp_err_t"; error_path_ = storage::SdCard::mount_point;
                end_io(StorageIo::Recover, false, started); return false;
            }
            startup_phase_begin(StartupStage::SdMount);
            const auto mount = card_.mount();
            startup_phase_end(StartupStage::SdMount, card_.last_error());
            if (mount != PortStatus::Ready) {
                error_ = card_.last_error(); error_domain_ = "esp_err_t"; error_path_ = storage::SdCard::mount_point;
                end_io(StorageIo::Recover, false, started); return false;
            }
            const bool opened = open_next();
            end_io(StorageIo::Recover, opened, started); return opened;
        }
        bool open_next() override {
            const auto started = begin_io(StorageIo::Open);
            startup_phase_begin(StartupStage::SdOpen);
            const bool opened = log_.open_new(storage::SdCard::mount_point, metadata_);
            startup_phase_end(StartupStage::SdOpen, log_.last_error());
            error_ = log_.last_error();
            error_domain_ = "errno";
            error_path_ = log_.path();
            end_io(StorageIo::Open, opened, started);
            if (opened) ESP_LOGI(tag, "SD_FILE %s engineering diagnostic; replay may retain acquisition_index", log_.path());
            return opened;
        }
        bool append(const sampling::AcquisitionRecord& value) override {
            const auto started = begin_io(StorageIo::Append);
            const auto format_before = log_.timings()[static_cast<unsigned>(storage::LogPhase::Format)].total_us;
            const auto write_before = log_.timings()[static_cast<unsigned>(storage::LogPhase::Write)];
            const bool ok = observe(log_.append(value));
            const auto& timing = log_.timings();
            policy::StoragePhaseDelta phases;
            phases.available = true;
            phases.format_us = timing[static_cast<unsigned>(storage::LogPhase::Format)].total_us - format_before;
            phases.fwrite_us = timing[static_cast<unsigned>(storage::LogPhase::Write)].total_us - write_before.total_us;
            phases.accepted_bytes = timing[static_cast<unsigned>(storage::LogPhase::Write)].bytes - write_before.bytes;
            end_io(StorageIo::Append, ok, started, phases); return ok;
        }
        bool flush() override {
            const auto started = begin_io(StorageIo::Flush);
            const auto flush_before = log_.timings()[static_cast<unsigned>(storage::LogPhase::Flush)].total_us;
            const auto sync_before = log_.timings()[static_cast<unsigned>(storage::LogPhase::Sync)].total_us;
            const bool ok = observe(log_.flush());
            policy::StoragePhaseDelta phases;
            phases.available = true;
            phases.fflush_us = log_.timings()[static_cast<unsigned>(storage::LogPhase::Flush)].total_us - flush_before;
            phases.fsync_us = log_.timings()[static_cast<unsigned>(storage::LogPhase::Sync)].total_us - sync_before;
            end_io(StorageIo::Flush, ok, started, phases); return ok;
        }
        bool close_and_verify() override { // compatibility path; production selects deferred verification below
            const auto started = begin_io(StorageIo::Close);
            const bool ok = observe(log_.close_and_verify()); end_io(StorageIo::Close, ok, started); return ok;
        }
        bool deferred_verification() const override { return true; }
        bool begin_verify() override {
            const auto started = begin_io(StorageIo::Close);
            bool ok = observe(log_.close_for_verification(checking_));
            if (ok) {
                ok = verifier_.begin(checking_);
                error_ = ok ? 0 : (verifier_.last_error() ? verifier_.last_error() : errno);
                error_path_ = checking_.path;
            }
            end_io(StorageIo::Close, ok, started);
            if (ok) ESP_LOGI(tag, "SD_VERIFY_BEGIN path=%s rows=%u bytes=%u crc32=%08lx quantum=%u; not VERIFIED yet",
                checking_.path, checking_.rows, static_cast<unsigned>(checking_.bytes), static_cast<unsigned long>(checking_.crc32),
                static_cast<unsigned>(storage::IncrementalVerifier::read_quantum));
            return ok;
        }
        storage::VerifyResult verify_step() override {
            const auto started = begin_io(StorageIo::VerifyChunk);
            const auto result = verifier_.step();
            error_ = verifier_.last_error(); error_domain_ = "errno";
            error_path_ = checking_.path;
            end_io(StorageIo::VerifyChunk, result != storage::VerifyResult::Failed, started);
            if (result == storage::VerifyResult::Passed) verified_ = checking_;
            return result;
        }
        const storage::ClosedSegment& last_verified_segment() const { return verified_; }
        void abort_verification() override { verifier_.cancel(); }
        void abandon() override { verifier_.cancel(); log_.abandon(); }
        bool last_write_uncertain() const override { return log_.last_write_uncertain(); }
        int last_error() const override { return error_; }
        const char* error_domain() const { return error_domain_; }
        const char* error_path() const { return error_path_; }
        std::uint64_t completed_at_ms(std::uint64_t) const override { return uptime_ms(); }
    private:
        bool observe(bool value) {
            error_ = log_.last_error(); error_domain_ = "errno"; error_path_ = log_.path(); return value;
        }
        storage::SdCard& card_; storage::DiagnosticLog& log_; const char* metadata_;
        storage::IncrementalVerifier verifier_;
        storage::ClosedSegment checking_{}, verified_{};
        int error_ = 0; // SDK esp_err_t for mount/reset; errno for file operations, operation is logged
        const char* error_domain_ = "none";
        const char* error_path_ = storage::SdCard::mount_point;
    };
    static SdBackend backend(card, log, metadata); // fixed reader buffer does not consume the task stack
    storage::RecoveryWriter writer(backend, config::storage_flush_rows, config::effective_storage_segment_rows);
    sampling::AcquisitionRecord record;
    policy::StorageServiceBudget service_budget(config::storage_append_yield_rows, config::storage_work_budget_us);
    bool completion_reported = false;
#ifdef CONFIG_NODE01_SANDBOX_EXPERIMENT
    static storage::ExperimentMetadata experiment_metadata;
    static storage::ExperimentRecord experiment_record;
    bool experiment_sd_prepared = false, experiment_begin_written = false, experiment_begin_ok = false;
    experiment_record.elf_sha256 = elf_hash;
    experiment_record.experiment_id = experiment_id;
    experiment_record.csv_path = experiment_csv;
#endif
    std::uint64_t startup_abort_seen_us = 0;
    for (;;) {
        // Never drain the queue during Recovery. At most one dequeued record
        // belongs to the writer; on failure it precedes all later queued records.
        const auto capture = capture_observation();
#ifdef CONFIG_NODE01_SANDBOX_EXPERIMENT
        if (!capture.started && !experiment_begin_written && experiment_observation().state == experiment::State::StartPending) {
            const auto session = experiment_observation();
            experiment_record.requested_seconds = session.seconds;
            experiment_record.start_us = 0; // durable START_INTENT, never fabricate an epoch
            experiment_begin_ok = experiment_metadata.save(experiment_record,false);
            experiment_begin_written = true;
            if (experiment_begin_ok)
                ESP_LOGI(tag,"EXPERIMENT_METADATA_VERIFIED stage=START_INTENT path=%s bytes=%u crc32=%08lx",experiment_metadata.path(),static_cast<unsigned>(experiment_metadata.bytes()),static_cast<unsigned long>(experiment_metadata.crc32()));
            else {
                ESP_LOGE(tag,"EXPERIMENT_METADATA_FAILED stage=START_INTENT error=%d; no epoch/no samples",experiment_metadata.last_error());
                abort_startup("EXPERIMENT_START_METADATA_FAILED");
            }
            if (experiment_begin_ok && !(xEventGroupGetBits(events)&startup_aborted)) experiment_start_storage_ok = true;
        }
#endif
        const auto abort_action = capture.started ? startup::AbortAction::None : startup::abort_action(false,
            (xEventGroupGetBits(events) & startup_aborted) != 0, writer.active(), writer.verification_active(), writer.finished());
        if (abort_action != startup::AbortAction::None) {
            // Startup only: never touch a running capture or steal FILE ownership.
            // A late successful mount/open closes and verifies its zero-row file
            // through the unchanged writer. Failed cleanup is never called PASS.
            set_observed(event::SD_OK, false);
            if (!startup_abort_seen_us) startup_abort_seen_us = esp_timer_get_time();
            if (abort_action == startup::AbortAction::FinishEmptyFile &&
                    static_cast<std::uint64_t>(esp_timer_get_time()) - startup_abort_seen_us < 120000000ULL) {
                writer.request_finish();
                writer.step(uptime_ms());
                portENTER_CRITICAL(&snapshot_lock);
                storage_observation = {writer.stats(), writer.active(), writer.has_pending(), writer.verification_active(), writer.finished(), log.timings()};
                portEXIT_CRITICAL(&snapshot_lock);
                vTaskDelay(1); continue;
            }
            const bool verified = abort_action == startup::AbortAction::ParkVerified;
            if (!verified) backend.abandon();
            const auto cleanup = card.reset();
            if (verified && cleanup == ESP_OK)
                ESP_LOGW(tag, "STARTUP_ABORT_FINALIZED verified_rows=%" PRIu64 " verified_files=%" PRIu64 "; no capture epoch, no sensor data; closed/unmounted",
                    writer.stats().verified_rows, writer.stats().verified_files);
            else ESP_LOGE(tag, "CAPTURE_FINALIZE_BLOCKED reason=STARTUP_ABORT cleanup=%s file_verified=%d; no acquisition started, retain log/card; no further SD retries",
                    esp_err_to_name(cleanup), verified);
            park_startup(TaskId::Storage, "STARTUP_ABORT_CLEANUP_COMPLETE_OR_BLOCKED");
        }
        if (capture.stop_requested && uptime_ms() - capture.requested_stop_us / 1000 > 120000 && !writer.finished()) {
#ifdef CONFIG_NODE01_SANDBOX_EXPERIMENT
            experiment_fail("FINALIZE_TIMEOUT_CSV_NOT_VERIFIED");
#endif
            ESP_LOGE(tag, "CAPTURE_FINALIZE_BLOCKED timeout=120s q=%u pending=%d accepted=%" PRIu64 " verified=%" PRIu64 "; tail NOT_VERIFIED; retain log/card",
                static_cast<unsigned>(uxQueueMessagesWaiting(storage_queue)), writer.has_pending(), writer.stats().append_accepted, writer.stats().verified_rows);
            set_observed(event::SD_OK, false);
            for (;;) vTaskDelay(pdMS_TO_TICKS(1000));
        }
        bool received = false, queue_waited = false;
        if (writer.can_take_record()) {
            received = xQueueReceive(storage_queue, &record, 0) == pdTRUE;
            if (!received && !writer.verification_active()) {
                // A blocking queue wait already gives the CPU to other tasks.
                // Do not charge idle time to the next operation's service quota.
                service_budget.reset(); queue_waited = true;
                const auto wait_start = begin_io(StorageIo::QueueWait);
                received = xQueueReceive(storage_queue, &record, pdMS_TO_TICKS(100)) == pdTRUE;
                end_io(StorageIo::QueueWait, true, wait_start); // timeout is normal idle, not an I/O failure
            }
        }
        const auto service_start = static_cast<std::uint64_t>(esp_timer_get_time());
        if (received) {
            records_dequeued.fetch_add(1);
            if (!writer.take_record(record)) {
                storage_internal_drops.fetch_add(1);
                ESP_LOGE(tag, "STORAGE_INTERNAL_DROP unexpected rejected dequeued record index=%" PRIu64, record.acquisition_index);
            }
        }
        if (capture.stop_requested && (capture.producers_done & producer_mask) == producer_mask &&
                uxQueueMessagesWaiting(storage_queue) == 0 && !writer.has_pending()) {
            writer.request_finish();
#ifdef CONFIG_NODE01_SANDBOX_EXPERIMENT
            portENTER_CRITICAL(&snapshot_lock); experiment_session.finalizing(true,true,false); portEXIT_CRITICAL(&snapshot_lock);
#endif
        }
        const auto prior_errors = writer.stats().errors;
        writer.step(uptime_ms());
#ifdef CONFIG_NODE01_SANDBOX_EXPERIMENT
        if (!experiment_sd_prepared && writer.active()) {
            // Startup only, before publishing SD_OK or releasing producers.
            // This is not a change to the in-capture 256-row sync policy.
            if (writer.stats().errors || !log.flush()) {
                abort_startup("EXPERIMENT_INITIAL_CSV_SYNC_FAILED");
            } else {
                const int path_len = std::snprintf(experiment_csv,sizeof(experiment_csv),"%s",log.path());
                const int id_len = std::snprintf(experiment_id,sizeof(experiment_id),"NODE01-%08lx%08lx-%s",static_cast<unsigned long>(esp_random()),static_cast<unsigned long>(esp_random()),log.path()+std::strlen(storage::SdCard::mount_point)+1);
                if (path_len < 0 || static_cast<unsigned>(path_len) >= sizeof(experiment_csv) || id_len < 0 || static_cast<unsigned>(id_len) >= sizeof(experiment_id))
                    abort_startup("EXPERIMENT_ID_PATH_OVERFLOW");
                else experiment_sd_prepared = true;
            }
        }
        set_observed(event::SD_OK,writer.active() && experiment_sd_prepared && !(xEventGroupGetBits(events)&startup_aborted));
#else
        set_observed(event::SD_OK, writer.active());
#endif
        if (writer.stats().errors != prior_errors) {
            ESP_LOGE(tag, "SD_RECOVERY operation=%d error=%d domain=%s error_path=%s current_writer=%s pending=%d acquisition_index=%" PRIu64 " retry_ms=%" PRIu64 "; partial file retained; potential replay != proven loss",
                static_cast<int>(writer.last_operation()), backend.last_error(), backend.error_domain(), backend.error_path(), log.path(),
                writer.has_pending(), record.acquisition_index, writer.next_retry_ms());
        }
        if (writer.last_operation() == storage::Operation::FileVerified) {
            const auto& verified = backend.last_verified_segment();
            ESP_LOGI(tag, "SD_READBACK verified path=%s rows=%u bytes=%u crc32=%08lx checks=length,actual_rows,crc,eof (verified != power-loss proof)",
                verified.path, verified.rows, static_cast<unsigned>(verified.bytes), static_cast<unsigned long>(verified.crc32));
        }
        portENTER_CRITICAL(&snapshot_lock);
        storage_observation = {writer.stats(), writer.active(), writer.has_pending(), writer.verification_active(), writer.finished(), log.timings()};
        portEXIT_CRITICAL(&snapshot_lock);
        observe_storage_queue(uxQueueMessagesWaiting(storage_queue), false, false);
        mark_progress(TaskId::Storage);
        if (writer.finished()) {
            if (!completion_reported) {
                const auto& s = writer.stats();
                const bool clean = !storage_queue_drops.load() && !storage_internal_drops.load() && !acquisition_exhausted.load() &&
                    !s.errors && !s.uncertain_records && !s.replayed_records && !s.retried_records && !s.verification_abandoned &&
                    !writer.has_pending() && uxQueueMessagesWaiting(storage_queue) == 0 &&
                    records_dequeued.load() == records_enqueued.load() && s.verified_rows == s.append_accepted &&
                    s.append_accepted == records_enqueued.load() && records_enqueued.load() == records_produced.load();
                ESP_LOGW(tag,
#ifdef CONFIG_NODE01_SANDBOX_EXPERIMENT
                    "CAPTURE_CSV_VERIFIED source=%s storage_quality=%s produced=%lu queue_drop=%lu accepted=%" PRIu64 " verified_rows=%" PRIu64 " errors=%" PRIu64 " uncertain=%" PRIu64 " replay=%" PRIu64 "; metadata pending, WAIT EXPERIMENT_FINALIZED/EXPERIMENT_FINALIZE_FAILED",
#else
                    "CAPTURE_FINALIZED source=%s storage_quality=%s produced=%lu queue_drop=%lu accepted=%" PRIu64 " verified_rows=%" PRIu64 " errors=%" PRIu64 " uncertain=%" PRIu64 " replay=%" PRIu64 "; storage completion != hardware/integration PASS",
#endif
                    diagnostic::source(config::diagnostic_mode), clean ? "NO_RECORDED_STORAGE_LOSS" : "QUALITY_LIMITED",
                    static_cast<unsigned long>(records_produced.load()), static_cast<unsigned long>(storage_queue_drops.load()),
                    s.append_accepted, s.verified_rows, s.errors, s.uncertain_records, s.replayed_records);
                completion_reported = true;
#ifdef CONFIG_NODE01_SANDBOX_EXPERIMENT
                const auto session = experiment_observation();
                const auto& verified = backend.last_verified_segment();
                experiment_record.start_us = session.start_us;
                experiment_record.stop_us = session.stop_us;
                portENTER_CRITICAL(&snapshot_lock); experiment_record.last_producer_ack_us = experiment_producers_done_us; portEXIT_CRITICAL(&snapshot_lock);
                experiment_record.stop_reason = experiment::reason(session.stopped_by);
                experiment_record.produced = records_produced.load(); experiment_record.enqueued = records_enqueued.load();
                experiment_record.dequeued = records_dequeued.load(); experiment_record.accepted = s.append_accepted; experiment_record.verified_rows = s.verified_rows;
                experiment_record.queue_drop = storage_queue_drops.load(); experiment_record.internal_drop = storage_internal_drops.load();
                experiment_record.errors = s.errors; experiment_record.uncertain = s.uncertain_records; experiment_record.replay = s.replayed_records;
                experiment_record.csv_verified = s.verified_files == 1 && !s.verify_failures && verified.rows == s.verified_rows && !std::strcmp(verified.path,experiment_csv);
                experiment_record.csv_bytes = experiment_record.csv_verified ? verified.bytes : 0;
                experiment_record.csv_crc = experiment_record.csv_verified ? verified.crc32 : 0;
                experiment_record.storage_clean = clean;
                experiment_record.i2c_errors = i2c_errors.load(); experiment_record.lock_timeouts = i2c_timeouts.load();
                experiment_record.top_valid = imu_valid[0].load(); experiment_record.toe_valid = imu_valid[1].load();
                experiment_record.sensor_errors = static_cast<std::uint64_t>(imu_failed[0].load())+imu_failed[1].load();
                for (unsigned i = 0; i < 3; ++i) { experiment_record.soil_valid[i] = soil_valid[i].load(); experiment_record.sensor_errors += soil_failed[i].load(); }
                const auto metadata_start = static_cast<std::uint64_t>(esp_timer_get_time());
                const bool metadata_ok = experiment_metadata.save(experiment_record,true);
                // Metadata is extra file I/O, included in the same finite stop budget.
                const bool within_budget = static_cast<std::uint64_t>(esp_timer_get_time())-capture.requested_stop_us <= 120000000ULL;
                const bool sensors_clean = !i2c_errors.load() && !i2c_timeouts.load() && !imu_failed[0].load() && !imu_failed[1].load() &&
                    !soil_failed[0].load() && !soil_failed[1].load() && !soil_failed[2].load() && imu_valid[0].load() && imu_valid[1].load() &&
                    soil_valid[0].load() && soil_valid[1].load() && soil_valid[2].load();
                portENTER_CRITICAL(&snapshot_lock);
                const bool transitioned = experiment_session.complete(clean && sensors_clean,experiment_begin_ok && metadata_ok && within_budget);
                portEXIT_CRITICAL(&snapshot_lock);
                const bool accepted = transitioned && clean && sensors_clean && experiment_begin_ok && metadata_ok && within_budget;
                ESP_LOGW(tag,"EXPERIMENT_%s id=%s reason=%s requested_s=%u actual_duration_us=%" PRIu64 " last_producer_ack_us=%" PRIu64 " csv_verified=%d metadata_verified=%d metadata_path=%s metadata_error=%d metadata_bytes=%u metadata_crc32=%08lx metadata_wall_us=%" PRIu64 " within_stop_budget=%d storage_clean=%d sensors_clean=%d; no hardware/calibration PASS",
                    accepted ? "FINALIZED" : "FINALIZE_FAILED",experiment_id,experiment::reason(session.stopped_by),session.seconds,session.stop_us-session.start_us,
                    experiment_record.last_producer_ack_us,experiment_record.csv_verified,metadata_ok && experiment_begin_ok,experiment_metadata.path(),experiment_metadata.last_error(),
                    static_cast<unsigned>(experiment_metadata.bytes()),static_cast<unsigned long>(experiment_metadata.crc32()),static_cast<std::uint64_t>(esp_timer_get_time())-metadata_start,within_budget,clean,sensors_clean);
#endif
            }
            vTaskDelay(pdMS_TO_TICKS(1000)); continue;
        }
        service_budget.observe(static_cast<std::uint64_t>(esp_timer_get_time()) - service_start,
            writer.last_operation() == storage::Operation::AppendAccepted);
        if (writer.recovering()) {
            service_budget.reset(); vTaskDelay(pdMS_TO_TICKS(50));
        } else {
            const auto action = writer.last_operation() == storage::Operation::None && !queue_waited
                ? policy::StorageServiceAction::Yield
                : service_budget.action(uxQueueMessagesWaiting(storage_queue), config::storage_catchup_queue_rows);
            portENTER_CRITICAL(&storage_trace_lock);
            storage_latency.attach_action(1U + static_cast<unsigned>(action));
            portEXIT_CRITICAL(&storage_trace_lock);
            if (action == policy::StorageServiceAction::CatchUp) storage_catchup_grants.fetch_add(1);
            if (action == policy::StorageServiceAction::Yield) {
                service_budget.reset();
                const auto sleep_start = static_cast<std::uint64_t>(esp_timer_get_time());
                vTaskDelay(1); // real blocked yield remains, even during sustained backlog
                storage_service_yields.fetch_add(1);
                storage_service_sleep_us.fetch_add(bounded_us(esp_timer_get_time() - sleep_start));
            }
        }
    }
}
void health_task(void*) {
    await_start();
    const auto observation_start = uptime_ms();
    std::array<policy::ProgressWatch, count> watches{
        policy::ProgressWatch(observation_start), policy::ProgressWatch(observation_start),
        policy::ProgressWatch(observation_start), policy::ProgressWatch(observation_start),
        policy::ProgressWatch(observation_start), policy::ProgressWatch(observation_start),
        policy::ProgressWatch(observation_start), policy::ProgressWatch(observation_start)};
    std::array<std::uint32_t, 2> previous_valid{};
    std::array<bool, 2> fallback_notice_printed{}, error_notice_printed{};
    std::uint32_t previous_loops = 0, previous_produced = 0, previous_enqueued = 0, previous_dequeued = 0, previous_queue_drop = 0, previous_event_wakes = 0;
    std::array<std::uint32_t, 2> previous_edges{};
    std::uint64_t previous_us = 0, previous_appended = 0;
    // Single HealthTask owns these fixed snapshots. Keep the larger diagnostic
    // copies off its stack; no I/O is performed while snapshot_lock is held.
    static StorageObservation observed_storage;
    static StorageIoObservation io;
    static policy::StoragePressureSnapshot pressure;
    static policy::StorageLatency latency;
    static policy::I2cLockTrace lock_trace;
    std::uint64_t printed_io_event = 0, printed_lock_timeouts = 0;
    std::uint64_t printed_pressure_entries = 0, printed_pressure_drops = 0, printed_long_io = 0;
    static std::array<drivers::I2cDeviceDiagnostics, 3> device;
    static std::array<drivers::ImuDiagnostic, 2> imu_debug;
    static std::array<IrqObservation, 2> irq_debug;
#ifdef CONFIG_NODE01_I2C_LOCK_DIAG_TRACE
    std::uint64_t next_health_us = 0;
#endif
    for (;;) {
#ifdef CONFIG_NODE01_I2C_LOCK_DIAG_TRACE
        const auto service_now = static_cast<std::uint64_t>(esp_timer_get_time());
        if (finite_trace_printed && next_health_us && service_now < next_health_us) {
            if (finite_output.pending()) {
                service_finite_i2c_trace(); // <=4 complete lines, <=20ms between-line budget
                vTaskDelay(1); // real Blocked state allows IDLE0; taskYIELD is insufficient
            } else {
                const auto left_ms = static_cast<unsigned>((next_health_us-service_now+999)/1000);
                vTaskDelay(drivers::timing::guarded_wait_ticks(left_ms, configTICK_RATE_HZ));
            }
            continue;
        }
#endif
        mark_progress(TaskId::UiHealth);
        // Capture counters BEFORE UART output. The old print-by-print reads
        // drifted across hundreds of milliseconds of logging. This is a short
        // diagnostic observation window, not an atomic transaction with producers.
        const auto now_us = static_cast<std::uint64_t>(esp_timer_get_time());
        const auto interval = previous_us ? now_us - previous_us : 0;
        const auto observed_risk = risk_snapshot();
        const auto observed_sensors = sensor_snapshot();
        const auto capture = capture_observation();
        const auto event_wakes = imu_event_wakes.load();
        std::array<std::uint32_t, 2> consumed{}, stale{}, deferred{}, services{}, irq_empty{}, fallbacks{}, coalesced{};
        for (unsigned i = 0; i < 2; ++i) {
            // Copy before UART output. Read consumed before raw edges so the
            // pending subtraction cannot underflow if acquisition advances.
            consumed[i] = imu_irq_consumed[i].load(); stale[i] = imu_irq_stale[i].load();
            deferred[i] = imu_irq_deferred[i].load(); services[i] = imu_irq_services[i].load();
            irq_empty[i] = imu_irq_empty[i].load(); fallbacks[i] = imu_irq_fallbacks[i].load();
            coalesced[i] = imu_irq_coalesced[i].load(); irq_debug[i] = irq_observation(i);
        }
        sensor_bus.copy_diagnostics(device); // fixed static destination, no large by-value stack temporary
        std::array<std::uint32_t, 2> valid{}, errors{}, empty{}, gap{}, read_max{};
        std::array<std::uint32_t, 3> soil_good{}, soil_bad{};
        std::array<std::uint32_t, count> cycles{};
        std::array<unsigned, count> stack{};
        for (unsigned i = 0; i < 2; ++i) {
            valid[i] = imu_valid[i].load(); errors[i] = imu_failed[i].load(); empty[i] = imu_no_data[i].load();
            gap[i] = imu_max_gap_us[i].load(); read_max[i] = imu_read_max_us[i].load();
        }
        for (unsigned i = 0; i < 3; ++i) { soil_good[i] = soil_valid[i].load(); soil_bad[i] = soil_failed[i].load(); }
        for (unsigned i = 0; i < count; ++i) if (handles[i]) {
            cycles[i] = progress[i].load(); stack[i] = uxTaskGetStackHighWaterMark(handles[i]);
        }
        const auto produced = records_produced.load(), enqueued = records_enqueued.load(), dequeued = records_dequeued.load();
        const auto drops = storage_queue_drops.load(), internal_drops = storage_internal_drops.load();
        const auto storage_disabled = records_storage_disabled.load();
        const auto service_yields = storage_service_yields.load(), service_sleep = storage_service_sleep_us.load();
        const auto exhausted = acquisition_exhausted.load();
        const auto queue_depth = uxQueueMessagesWaiting(storage_queue);
        const auto queue_peak = storage_queue_peak.load();
        const auto lock_wait = i2c_lock_wait_us.exchange(0), lock_wait_max = i2c_lock_wait_max_us.load();
        const auto held = i2c_busy_us.exchange(0), held_max = i2c_max_transfer_us.load();
        const auto bus_errors = i2c_errors.load(), lock_timeouts = i2c_timeouts.load();
        const auto tick_no_delay = imu_tick_no_delay.load(), boundaries = imu_boundary_hits.load();
        const auto misses = imu_deadline_misses.load(), over_budget = imu_cycle_over_budget.load();
        const auto risk_misses = risk_deadline_misses.load(), alarm_drops = queue_overflows.load();
        const auto cycle_max = imu_cycle_max_us.load(), period_max = imu_start_period_max_us.load();
        portENTER_CRITICAL(&snapshot_lock);
        observed_storage = storage_observation;
        io = storage_io;
        storage_pressure.copy_snapshot(pressure, esp_timer_get_time());
        imu_debug = imu_diagnostic_observation;
        portEXIT_CRITICAL(&snapshot_lock);
        portENTER_CRITICAL(&storage_trace_lock);
        storage_latency.copy_into(latency);
        portEXIT_CRITICAL(&storage_trace_lock);
        portENTER_CRITICAL(&i2c_trace_lock);
        i2c_lock_trace.copy_into(lock_trace);
        portEXIT_CRITICAL(&i2c_trace_lock);
        auto rate = [&](std::uint64_t delta) { return interval ? delta * 1000000.0 / interval : 0.0; };
        const auto active_us = policy::capture_overlap_us(previous_us, now_us, capture);
        auto active_rate = [&](std::uint64_t delta) { return active_us ? delta * 1000000.0 / active_us : 0.0; };
        for (unsigned i = 0; i < 2; ++i) {
            const auto& sample = observed_sensors.imu[i];
            if (sample.validity != sampling::Validity::Valid ||
                !policy::fresh(sample.acquired_uptime_us, now_us, config::imu_liveness_us))
                set_observed(i ? event::IMU_TOE_OK : event::IMU_TOP_OK, false);
        }
        for (const auto& sample : observed_sensors.soil)
            if (sample.validity != sampling::Validity::Valid ||
                !policy::fresh(sample.acquired_uptime_us, now_us, config::soil_liveness_us)) set_observed(event::SOIL_OK, false);

        ESP_LOGI(tag, "DIAG_V6 mode=%s source=%s observed_us=%" PRIu64 " window_us=%" PRIu64 " risk=%s calibration=NOT_READY event_bits=0x%lx heap_free=%lu",
            diagnostic::name(config::diagnostic_mode), diagnostic::source(config::diagnostic_mode),
            now_us, interval, observed_risk.risk.sensor_score ? "VALID" : "null",
            static_cast<unsigned long>(system_events()), static_cast<unsigned long>(esp_get_free_heap_size()));
#ifdef CONFIG_NODE01_SANDBOX_EXPERIMENT
        const unsigned reported_seconds = experiment_observation().seconds;
#else
        constexpr unsigned reported_seconds = config::capture_seconds;
#endif
        ESP_LOGI(tag, "CAPTURE started=%d stop_requested=%d producers_done=0x%lx start_us=%" PRIu64 " requested_stop_us=%" PRIu64 " duration_s=%u storage_finished=%d; do not disconnect before finalized/explicit blocked",
            capture.started, capture.stop_requested, static_cast<unsigned long>(capture.producers_done), capture.started_us,
            capture.requested_stop_us, reported_seconds, observed_storage.finished);
        for (unsigned i = 0; i < 2; ++i)
            ESP_LOGI(tag, "IMU_%s valid=%lu error=%lu no_new_data=%lu observed_hz=%.2f max_gap_us=%lu read_max_us=%lu rate_basis=HEALTH_INTERVAL",
                i ? "TOE" : "TOP", static_cast<unsigned long>(valid[i]), static_cast<unsigned long>(errors[i]),
                static_cast<unsigned long>(empty[i]), rate(static_cast<std::uint32_t>(valid[i] - previous_valid[i])),
                static_cast<unsigned long>(gap[i]), static_cast<unsigned long>(read_max[i]));
        for (unsigned i = 0; i < 2; ++i) {
            const auto& d = imu_debug[i];
            ESP_LOGI(tag, "IMU_READ_STAGE site=%s latest=%s status_seen=%d status=0x%02x attempts=%" PRIu64 " status_fail=%" PRIu64 " ready_raw_fail=%" PRIu64 " invalid_raw=%" PRIu64 " empty=%" PRIu64,
                i ? "TOE" : "TOP", drivers::imu_stage_name(d.stage), d.status_observed, d.status,
                d.attempts, d.status_failures, d.ready_data_read_failures, d.invalid_raw_codes, d.empty_polls);
            ESP_LOGI(tag, "IMU_IRQ site=%s enabled=%d observed_edges=%lu startup_edges=%lu capture_edges=%lu suppressed_unarmed=%lu edge_hz=%.2f serviced=%lu irq_empty=%lu fallback=%lu coalesced_edges=%lu last_edge_us=%" PRIu64 "; disabled GPIO edges unobservable; latched edges cannot count hidden overruns",
                i ? "TOE" : "TOP", irq_debug[i].enabled, static_cast<unsigned long>(irq_debug[i].edges),
                static_cast<unsigned long>(irq_debug[i].startup_edges), static_cast<unsigned long>(irq_debug[i].capture_edges),
                static_cast<unsigned long>(irq_debug[i].suppressed_unarmed),
                rate(static_cast<std::uint32_t>(irq_debug[i].capture_edges - previous_edges[i])),
                static_cast<unsigned long>(services[i]), static_cast<unsigned long>(irq_empty[i]),
                static_cast<unsigned long>(fallbacks[i]), static_cast<unsigned long>(coalesced[i]), irq_debug[i].last_edge_us);
            ESP_LOGI(tag, "IMU_IRQ_BUDGET site=%s notify_claims=%lu notify_coalesced=%lu stale_notifications=%lu deferred_notifications=%lu consumed_edges=%lu pending_edges=%lu; raw ISR edges retained, one read/site/frame including fallback",
                i ? "TOE" : "TOP", static_cast<unsigned long>(irq_debug[i].notify_claims),
                static_cast<unsigned long>(irq_debug[i].notify_coalesced), static_cast<unsigned long>(stale[i]),
                static_cast<unsigned long>(deferred[i]), static_cast<unsigned long>(consumed[i]),
                static_cast<unsigned long>(static_cast<std::uint32_t>(irq_debug[i].capture_edges - consumed[i])));
            ESP_LOGI(tag, "IMU_CAPTURE_RATE site=%s active_overlap_us=%" PRIu64 " health_interval_us=%" PRIu64 " valid_count_hz=%.2f irq_count_hz=%.2f; count/window estimate, zero active denominator means unavailable",
                i ? "TOE" : "TOP", active_us, interval,
                active_rate(static_cast<std::uint32_t>(valid[i] - previous_valid[i])),
                active_rate(static_cast<std::uint32_t>(irq_debug[i].capture_edges - previous_edges[i])));
        }
        for (unsigned i = 0; i < 2; ++i) {
            policy::ImuNotice notice;
            if (!fallback_notice_printed[i] && imu_first_fallback[i].read(imu_notice_critical, notice)) {
                fallback_notice_printed[i] = true;
                ESP_LOGW(tag, "IMU_IRQ_FALLBACK site=%s init_ok=%d observed_us=%" PRIu64 " deferred=UiHealthTask; inspect init/status/IRQ evidence; polling is not event acceptance",
                    i ? "TOE" : "TOP", notice.initialized, notice.observed_us);
            }
            if (!error_notice_printed[i] && imu_first_read_error[i].read(imu_notice_critical, notice)) {
                error_notice_printed[i] = true;
                ESP_LOGE(tag, "IMU_%s_READ %s init_ok=%d attempt_us=%" PRIu64 " deferred=UiHealthTask; see stage/SDK diagnostics",
                    i ? "TOE" : "TOP", esp_err_to_name(notice.error), notice.initialized, notice.observed_us);
            }
        }
        ESP_LOGI(tag, "IMU_SERVICE event_wakes=%lu wake_hz=%.2f rate_basis=HEALTH_INTERVAL; loops below are 100Hz supervisory frames, not task wake count; cycle work excludes notification wait",
            static_cast<unsigned long>(event_wakes), rate(static_cast<std::uint32_t>(event_wakes - previous_event_wakes)));
        ESP_LOGI(tag, "%s loops=%lu loop_hz=%.2f tick_no_delay=%lu boundary=%lu imu_deadline_misses=%lu work_over_10ms=%lu cycle_max_us=%lu start_period_max_us=%lu",
            config::sensors_enabled ? "IMU_TIMING" : "STORAGE_TEST_TIMING_SYNTHETIC",
            static_cast<unsigned long>(cycles[index(TaskId::Imu)]),
            rate(static_cast<std::uint32_t>(cycles[index(TaskId::Imu)] - previous_loops)),
            static_cast<unsigned long>(tick_no_delay), static_cast<unsigned long>(boundaries),
            static_cast<unsigned long>(misses), static_cast<unsigned long>(over_budget),
            static_cast<unsigned long>(cycle_max), static_cast<unsigned long>(period_max));
        ESP_LOGI(tag, "IMU_FRAME_CAPTURE_RATE active_overlap_us=%" PRIu64 " loop_count_hz=%.2f; not an ODR or deadline guarantee",
            active_us, active_rate(static_cast<std::uint32_t>(cycles[index(TaskId::Imu)] - previous_loops)));
        ESP_LOGI(tag, "SOIL valid=%lu/%lu/%lu error=%lu/%lu/%lu",
            static_cast<unsigned long>(soil_good[0]), static_cast<unsigned long>(soil_good[1]), static_cast<unsigned long>(soil_good[2]),
            static_cast<unsigned long>(soil_bad[0]), static_cast<unsigned long>(soil_bad[1]), static_cast<unsigned long>(soil_bad[2]));
        ESP_LOGI(tag, "I2C errors=%lu lock_timeout=%lu wait_interval_us=%lu wait_max_us=%lu held_interval_us=%lu held_max_us=%lu",
            static_cast<unsigned long>(bus_errors), static_cast<unsigned long>(lock_timeouts),
            static_cast<unsigned long>(lock_wait), static_cast<unsigned long>(lock_wait_max),
            static_cast<unsigned long>(held), static_cast<unsigned long>(held_max));
        for (const auto& d : device)
            ESP_LOGI(tag, "I2C_DEVICE addr=0x%02x req=%" PRIu64 " sdk=%" PRIu64 " err=%" PRIu64 " timeout=%" PRIu64 " state=%" PRIu64
                " max_call_us=%" PRIu64 " last_fail=%s/0x%02x/%u err=%d sdk_entered=%d fail_us=%" PRIu64,
                d.address, d.transfers, d.sdk_calls, d.errors, d.timeouts, d.invalid_states, d.max_wall_us,
                d.last_failed_read ? "R" : "W", d.last_failed_reg, static_cast<unsigned>(d.last_failed_size),
                d.last_failed_error, d.last_failed_executed, d.last_failed_wall_us);
        for (const auto& d : device)
            ESP_LOGI(tag, "I2C_CAUSE addr=0x%02x sdk_err=%" PRIu64 " local_err=%" PRIu64 " sdk_state=%" PRIu64 " local_state=%" PRIu64 " pads_before=%d/%d pads_after=%d/%d probe=%" PRIu64 " probe_error=%d; pads are not a waveform",
                d.address, d.sdk_errors, d.local_errors, d.sdk_invalid_states, d.local_invalid_states,
                d.last_failed_lines.before_sda, d.last_failed_lines.before_scl,
                d.last_failed_lines.after_sda, d.last_failed_lines.after_scl, d.probes, d.last_probe_error);
        const auto& st = observed_storage.stats;
#ifdef CONFIG_NODE01_I2C_LOCK_DIAG_TRACE
        if(capture.started && capture.stop_requested && (capture.producers_done & producer_mask)==producer_mask && observed_storage.finished)
            start_finite_i2c_trace();
#endif
        ESP_LOGI(tag, "FLOW produced=%lu enqueued=%lu dequeued=%lu queue_drop=%lu index_exhausted=%lu internal_drop=%lu storage_disabled=%lu q=%u peak=%lu rate_produced=%.2f rate_enqueued=%.2f rate_dequeued=%.2f rate_appended=%.2f",
            static_cast<unsigned long>(produced), static_cast<unsigned long>(enqueued), static_cast<unsigned long>(dequeued),
            static_cast<unsigned long>(drops), static_cast<unsigned long>(exhausted), static_cast<unsigned long>(internal_drops),
            static_cast<unsigned long>(storage_disabled), static_cast<unsigned>(queue_depth),
            static_cast<unsigned long>(queue_peak), rate(static_cast<std::uint32_t>(produced-previous_produced)),
            rate(static_cast<std::uint32_t>(enqueued-previous_enqueued)),
            rate(static_cast<std::uint32_t>(dequeued-previous_dequeued)), rate(st.append_accepted-previous_appended));
        if (drops != previous_queue_drop)
            ESP_LOGE(tag, "STORAGE_QUEUE_OVERFLOW drop_delta=%lu total=%lu; RAM buffer exhausted; samples remain nonblocking",
                static_cast<unsigned long>(drops-previous_queue_drop), static_cast<unsigned long>(drops));
        ESP_LOGI(tag, "SD active=%d pending=%d verifying=%d append_accepted=%" PRIu64 " flush_accepted=%" PRIu64 " files_verified=%" PRIu64
            " errors=%" PRIu64 " uncertain=%" PRIu64 " replay=%" PRIu64 " verify_backpressure=%" PRIu64 " (verified != power-loss proof)",
            observed_storage.active, observed_storage.pending, observed_storage.verifying,
            st.append_accepted, st.flush_accepted, st.verified_files, st.errors, st.uncertain_records, st.replayed_records,
            st.verification_backpressure_steps);
        ESP_LOGI(tag, "SD_FAILURE write=%" PRIu64 " flush=%" PRIu64 " verify=%" PRIu64 " open=%" PRIu64 " recovery=%" PRIu64 " unavailable_drop=0",
            st.write_failures, st.flush_failures, st.verify_failures, st.open_failures, st.recovery_failures);
        ESP_LOGI(tag, "STORAGE_SCHED explicit_yields=%lu sleep_us=%lu append_budget=%u wall_budget_us=%u flush_rows=%u segment_rows=%u queue_capacity=%u; budget excludes queue wait, checked AFTER each I/O",
            static_cast<unsigned long>(service_yields), static_cast<unsigned long>(service_sleep),
            config::storage_append_yield_rows, config::storage_work_budget_us, config::storage_flush_rows, config::effective_storage_segment_rows,
            static_cast<unsigned>(config::storage_queue_length));
        constexpr const char* io_names[]{"recover_inclusive", "open", "append", "flush", "close_begin", "verify_4KiB", "queue_wait"};
        // Fixed histograms provide intervals, not invented exact percentiles.
        auto print_histogram = [&](const char* operation, const policy::LatencyHistogram& histogram) {
            if (!histogram.samples()) return;
            const auto p50 = histogram.quantile(50), p95 = histogram.quantile(95), p99 = histogram.quantile(99);
            ESP_LOGI(tag, "SD_LATENCY op=%s n=%" PRIu64 " p50_us=%" PRIu64 "..%" PRIu64 " p95_us=%" PRIu64 "..%" PRIu64 " p99_us=%" PRIu64 "..%" PRIu64 " unbounded50_95_99=%d/%d/%d max_us=%" PRIu64 " over100ms=%" PRIu64 " over300ms=%" PRIu64 " over500ms=%" PRIu64 "; histogram intervals; CPU time unavailable",
                operation, histogram.samples(), p50.lower_us, p50.upper_us, p95.lower_us, p95.upper_us,
                p99.lower_us, p99.upper_us, p50.unbounded, p95.unbounded, p99.unbounded, histogram.maximum(), histogram.over100(), histogram.over300(), histogram.over500());
        };
        print_histogram("append", latency.append()); print_histogram("flush_periodic", latency.flush());
        const auto oldest_event = latency.total_events() > policy::StorageLatency::capacity ? latency.total_events() - policy::StorageLatency::capacity + 1 : 1;
        if (printed_io_event + 1 < oldest_event) {
            ESP_LOGW(tag, "SD_LONG_EVENT_GAP unseen=%" PRIu64 " oldest_retained=%" PRIu64 "; bounded ring, retain max/histograms", oldest_event-printed_io_event-1, oldest_event);
            printed_io_event = oldest_event-1;
        }
        // At most four events per Health interval; no per-record UART output.
        for (unsigned emitted=0; emitted<4 && printed_io_event<latency.total_events(); ++emitted) {
            const auto* event = latency.event(++printed_io_event);
            if (!event) continue;
            ESP_LOGW(tag, "SD_LONG_EVENT seq=%" PRIu64 " op=%s start_us=%" PRIu64 " end_us=%" PRIu64 " wall_us=%" PRIu64 " q_before=%u q_after=%u rows=%u bytes=%" PRIu64 " phase_seen=%d format_us=%" PRIu64 " fwrite_us=%" PRIu64 " fflush_us=%" PRIu64 " fsync_us=%" PRIu64 " catchups_before=%" PRIu64 " next_action=%u core=%u priority=%u ok=%d cpu_time_available=0; queue endpoints sampled, nested recover overlaps open",
                event->sequence, io_names[event->operation], event->started_us, event->finished_us, event->wall_us,
                event->queue_before, event->queue_after, event->rows, event->phases.accepted_bytes, event->phases.available,
                event->phases.format_us, event->phases.fwrite_us, event->phases.fflush_us, event->phases.fsync_us,
                event->catchups, event->action, event->core, event->priority, event->success);
        }
        if (latency.total_events()) ESP_LOGI(tag, "SD_EVENT_RING total=%" PRIu64 " historical_evictions=%" PRIu64 " context_errors=%" PRIu64 " capacity=16; eviction != unseen gap", latency.total_events(), latency.overwritten_history(), latency.context_errors());
        if (capture.started && lock_trace.acquisitions()) ESP_LOGI(tag, "I2C_LOCK_OWNERSHIP takes=%" PRIu64 " gives=%" PRIu64 " local_timeouts=%" PRIu64 " observed_acquire_to_before_give_max_us=%" PRIu64 " give_failures=%" PRIu64 " metadata_errors=%" PRIu64 "; legacy held_max is SDK callback wall, not whole ownership; FreeRTOS priority inheritance enabled, runtime effect requires trace",
            lock_trace.acquisitions(), lock_trace.releases(), lock_trace.timeouts(), lock_trace.max_observed_hold_us(), lock_trace.give_failures(), lock_trace.metadata_errors());
        auto task_name = [&](std::uintptr_t token) {
            if (!token) return "NONE";
            for (unsigned i=0;i<count;++i) if (reinterpret_cast<std::uintptr_t>(handles[i])==token) return config::tasks[i].name;
            return "OTHER";
        };
        auto print_lock_failure = [&](const char* which, const policy::LockFailure& failure) {
            const auto& waiter=failure.wait;
            ESP_LOGE(tag, "I2C_LOCK_TIMEOUT which=%s start_us=%" PRIu64 " observed_end_us=%" PRIu64 " waiter=%s waiter_priority=%u owner_before=%s owner_priority=%u owner_acquired_us=%" PRIu64 " owner_after=%s kernel_holder_after=%s last_give_task=%s last_give_us=%" PRIu64 "; SDK_NOT_ENTERED; holder observations are not an atomic wait history",
                which, waiter.started_us, failure.finished_us, task_name(waiter.waiter), waiter.priority,
                task_name(waiter.owner_before.task), waiter.owner_before.priority, waiter.owner_before.acquired_us,
                task_name(failure.owner_after.task), task_name(failure.kernel_holder_after),
                task_name(failure.last_give_attempt.task), failure.last_give_attempt.before_give_us);
        };
        if (lock_trace.timeouts()!=printed_lock_timeouts) {
            if (!printed_lock_timeouts) print_lock_failure("first",lock_trace.first());
            if (lock_trace.timeouts()>1) print_lock_failure("last",lock_trace.last());
            printed_lock_timeouts=lock_trace.timeouts();
        }
        ESP_LOGI(tag, "STORAGE_PRESSURE sampled_high=%d threshold=%u resume=%u entries=%" PRIu64 " recoveries=%" PRIu64 " high_total_us=%" PRIu64 " high_max_us=%" PRIu64 " drops=%" PRIu64 " late_samples=%" PRIu64 " catchup_grants=%lu catchup_at=%u; at most one extra 32-row/50ms quota before blocked tick yield",
            pressure.high, config::storage_pressure_high_rows, config::storage_pressure_low_rows,
            pressure.high_entries, pressure.recoveries, pressure.high_total_us, pressure.high_max_us, pressure.drops, pressure.late_samples,
            static_cast<unsigned long>(storage_catchup_grants.load()), config::storage_catchup_queue_rows);
        auto print_pressure_event = [&](const char* which, const policy::StorageQueueSample& value) {
            const char* op = value.io_operation < static_cast<unsigned>(StorageIo::Count) ? io_names[value.io_operation] : "none";
            ESP_LOGW(tag, "STORAGE_Q_EVENT which=%s observed_us=%" PRIu64 " depth_after_op=%lu has_index=%d acquisition_index=%" PRIu64 " dropped=%d io=%s io_start_us=%" PRIu64 " io_age_us=%" PRIu64 "; sampled after queue op, not atomic queue history",
                which, value.observed_us, static_cast<unsigned long>(value.depth), value.has_index, value.acquisition_index,
                value.dropped, op, value.io_started_us,
                value.io_started_us && value.observed_us >= value.io_started_us ? value.observed_us - value.io_started_us : 0);
        };
        if (pressure.high_entries != printed_pressure_entries) print_pressure_event("last_high", pressure.last_high);
        if (pressure.drops != printed_pressure_drops) {
            if (!printed_pressure_drops) print_pressure_event("first_drop", pressure.first_drop);
            if (pressure.last_drop.acquisition_index != pressure.first_drop.acquisition_index) print_pressure_event("last_drop", pressure.last_drop);
        }
        printed_pressure_entries = pressure.high_entries; printed_pressure_drops = pressure.drops;
        if (io.long_calls != printed_long_io) {
            ESP_LOGW(tag, "SD_LAST_LONG_IO calls=%" PRIu64 " op=%s started_us=%" PRIu64 " finished_us=%" PRIu64 " wall_us=%" PRIu64 "; last completed >=100ms, includes scheduling/wait; not full I/O history",
                io.long_calls, io_names[static_cast<unsigned>(io.last_long_operation)], io.last_long_started_us,
                io.last_long_finished_us, io.last_long_wall_us);
            printed_long_io = io.long_calls;
        }

        for (unsigned i = 0; i < io.timing.size(); ++i) {
            const auto& t = io.timing[i];
            ESP_LOGI(tag, "SD_IO op=%s calls=%" PRIu64 " fail=%" PRIu64 " total_us=%" PRIu64 " max_us=%lu",
                io_names[i], t.calls, t.failures, t.total_us, static_cast<unsigned long>(t.max_us));
        }
        if (io.in_flight != StorageIo::Count)
            ESP_LOGW(tag, "SD_IO_IN_FLIGHT op=%s age_us=%" PRIu64, io_names[static_cast<unsigned>(io.in_flight)],
                now_us >= io.started_us ? now_us-io.started_us : 0);
        constexpr const char* phase_names[]{"format", "fwrite", "crc", "fflush", "fsync"};
        for (unsigned i = 0; i < observed_storage.phases.size(); ++i) {
            const auto& t = observed_storage.phases[i];
            ESP_LOGI(tag, "SD_PHASE op=%s calls=%" PRIu64 " fail=%" PRIu64 " total_us=%" PRIu64 " max_us=%" PRIu64 " bytes=%" PRIu64 "; wall includes preemption/wait, not pure card or CPU time",
                phase_names[i], t.calls, t.failures, t.total_us, t.max_us, t.bytes);
        }
        ESP_LOGI(tag, "TASK_PROGRESS imu=%lu risk=%lu alarm=%lu slow=%lu comm=%lu storage=%lu health=%lu risk_miss=%lu alarm_qdrop=%lu",
            static_cast<unsigned long>(cycles[index(TaskId::Imu)]), static_cast<unsigned long>(cycles[index(TaskId::Risk)]),
            static_cast<unsigned long>(cycles[index(TaskId::Alarm)]), static_cast<unsigned long>(cycles[index(TaskId::SlowSensor)]),
            static_cast<unsigned long>(cycles[index(TaskId::CommSupervisor)]), static_cast<unsigned long>(cycles[index(TaskId::Storage)]),
            static_cast<unsigned long>(cycles[index(TaskId::UiHealth)]), static_cast<unsigned long>(risk_misses),
            static_cast<unsigned long>(alarm_drops));
        ESP_LOGI(tag, "STACK_HWM_BYTES imu=%u risk=%u alarm=%u slow=%u comm=%u storage=%u health=%u (TBD-15)",
            stack[index(TaskId::Imu)], stack[index(TaskId::Risk)], stack[index(TaskId::Alarm)], stack[index(TaskId::SlowSensor)],
            stack[index(TaskId::CommSupervisor)], stack[index(TaskId::Storage)], stack[index(TaskId::UiHealth)]);
        for (unsigned i = 0; i < count; ++i) if (handles[i] && !(startup_parked.load() & (1U << i)) &&
#ifdef CONFIG_NODE01_SANDBOX_EXPERIMENT
            (capture.started || (i != index(TaskId::Imu) && i != index(TaskId::SlowSensor))) &&
#endif
            !(i == index(TaskId::Imu) && (capture.producers_done & producer_imu)) &&
            !(i == index(TaskId::SlowSensor) && (capture.producers_done & producer_slow)) &&
            watches[i].observe(cycles[i], now_us/1000, config::progress_stall_ms, i == index(TaskId::Alarm)))
                ESP_LOGE(tag, "TASK_NO_PROGRESS task=%s; liveness only, no unconditional watchdog feed", config::tasks[i].name);
        previous_valid = valid; previous_loops = cycles[index(TaskId::Imu)];
        previous_produced = produced; previous_enqueued = enqueued; previous_dequeued = dequeued; previous_appended = st.append_accepted;
        previous_queue_drop = drops; previous_us = now_us;
        previous_event_wakes = event_wakes;
        for (unsigned i = 0; i < 2; ++i) previous_edges[i] = irq_debug[i].capture_edges;
#ifdef CONFIG_NODE01_I2C_LOCK_DIAG_TRACE
        if (finite_trace_printed) { // post-finalization only; capture-time Health cadence unchanged
            next_health_us = static_cast<std::uint64_t>(esp_timer_get_time()) + config::health_period_ms*1000ULL;
            if (finite_output.pending()) { vTaskDelay(1); continue; }
        }
#endif
        vTaskDelay(pdMS_TO_TICKS(config::health_period_ms));
    }
}
void cleanup_failed_start() {
#ifdef CONFIG_NODE01_SANDBOX_EXPERIMENT
    if (experiment_console_handle) { vTaskDelete(experiment_console_handle); experiment_console_handle = nullptr; }
#endif
    if (imu_irqs_ready || gpio_service_owned) cleanup_imu_irqs();
    // Created tasks are still at startup gate, before resource access.
    for (auto& handle : handles) if (handle) { vTaskDelete(handle); handle = nullptr; }
    if (alarm_queue) { vQueueDelete(alarm_queue); alarm_queue = nullptr; }
    if (storage_queue) { vQueueDelete(storage_queue); storage_queue = nullptr; }
    sensor_bus.close();
    if (i2c_mutex) { vSemaphoreDelete(i2c_mutex); i2c_mutex = nullptr; }
    if (events) { vEventGroupDelete(events); events = nullptr; }
}
} // namespace

esp_err_t start() {
    if (started || events) return ESP_ERR_INVALID_STATE;
    events = xEventGroupCreate();
    i2c_mutex = xSemaphoreCreateMutex();
    alarm_queue = xQueueCreate(config::alarm_queue_length, sizeof(risk_runtime::Snapshot));
    const auto queue_internal_before = heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    const auto queue_largest_before = heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    storage_queue = xQueueCreate(config::storage_queue_length, sizeof(sampling::AcquisitionRecord));
    ESP_LOGI(tag, "STORAGE_QUEUE_ALLOC rows=%u record_bytes=%u payload_bytes=%u internal_free_before=%u internal_largest_before=%u internal_free_after=%u internal_largest_after=%u allocated=%d; INTERNAL RAM, not PSRAM, payload excludes queue/allocator overhead",
        static_cast<unsigned>(config::storage_queue_length), static_cast<unsigned>(sizeof(sampling::AcquisitionRecord)),
        static_cast<unsigned>(config::storage_queue_length * sizeof(sampling::AcquisitionRecord)),
        static_cast<unsigned>(queue_internal_before), static_cast<unsigned>(queue_largest_before),
        static_cast<unsigned>(heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT)),
        static_cast<unsigned>(heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT)), storage_queue != nullptr);
    if (!events || !i2c_mutex || !alarm_queue || !storage_queue) { cleanup_failed_start(); return ESP_ERR_NO_MEM; }
    ESP_LOGW(tag, "DIAGNOSTIC_MODE mode=%s source=%s sensors=%d storage=%d; not experiment/algorithm data",
        diagnostic::name(config::diagnostic_mode), diagnostic::source(config::diagnostic_mode), config::sensors_enabled, config::storage_enabled);
    if constexpr (config::diagnostic_mode == diagnostic::Mode::SensorsOnly) {
        // The SDK's I2C_ENABLE_DEBUG_LOG compiles its NACK details and has its
        // own log-level constructor. Restrict this tag to DEBUG, not VERBOSE.
        esp_log_level_set("i2c.master", ESP_LOG_DEBUG);
        ESP_LOGW(tag, "I2C_ISOLATION SDK NACK details enabled; extra error-log overhead is TEST_ONLY");
    }
    constexpr const char* startup_name = config::startup_plan == startup::Plan::Probe ? "A_PROBE" :
        config::startup_plan == startup::Plan::ImuFirst ? "B_IMU_FIRST" : "CONCURRENT";
    ESP_LOGW(tag, "STARTUP_EXPERIMENT plan=%s probes=%d duration_s=%u; TEST_ONLY, no root-cause claim",
        startup_name, config::startup_probe, config::capture_seconds);
    ESP_LOGW(tag, "IMU_SERVICE_POLICY revision=R9 read_limit_per_site_per_frame=1 notification_claims_per_site_per_frame=1; raw GPIO ISR counts retained, pending latched edges carried to next frame; physical storm cause NOT_CONFIRMED");
    const auto bus_error = config::sensors_enabled ? sensor_bus.initialize(with_i2c_transaction) : ESP_OK;
#ifdef CONFIG_NODE01_I2C_LOCK_DIAG_TRACE
    if(bus_error==ESP_OK) sensor_bus.set_diagnostic_executor(finite_i2c_executor);
#endif
    if (bus_error != ESP_OK) ESP_LOGE(tag, "I2C_BUS_UNAVAILABLE %s; readings fail explicitly; no concurrent bus rebuild; local diagnostics/storage continue", esp_err_to_name(bus_error));
    if constexpr (config::startup_probe) {
        if (bus_error == ESP_OK) {
            // Bounded probes run before ANY sensor task starts, avoiding extra
            // traffic during sampling. The three addresses are frozen, no scan.
            constexpr std::array<std::uint8_t, 3> addresses{board::bus::imu_top_address, board::bus::imu_toe_address, board::bus::ads1115_address};
            startup::run_probes(true, addresses, [](std::uint8_t address) {
                ESP_LOGI(tag, "I2C_ISOLATION_PROBE addr=0x%02x result=%s TEST_ONLY; not a sample",
                    address, esp_err_to_name(sensor_bus.probe(address)));
            });
        }
    }
    const std::array<TaskFunction_t, count> entries{
        config::sensors_enabled ? imu_task : storage_test_producer, risk_task, alarm_task, slow_task,
#ifdef CONFIG_NODE01_NETWORK_ENABLE
        comm_task,
#else
        nullptr,
#endif
        nullptr, storage_task, health_task};
    for (unsigned i = 0; i < count; ++i) {
        const auto& spec = config::tasks[i];
        if (!spec.enabled) {
            ESP_LOGI(tag, "%s DISABLED by capability/configuration/diagnostic mode (LoRa NOT_IMPLEMENTED)", spec.name);
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
#ifdef CONFIG_NODE01_SANDBOX_EXPERIMENT
    if (xTaskCreatePinnedToCore(experiment_console_task,"ExperimentConsole",4096,nullptr,2,&experiment_console_handle,0) != pdPASS) {
        cleanup_failed_start(); return ESP_ERR_NO_MEM;
    }
    ESP_LOGW(tag,"SANDBOX_EXPERIMENT_CAPTURE mode_enabled=1 auto_start=0 range_s=30..300 one_per_boot=1 calibration=NOT_READY");
#endif
    if constexpr (config::imu_drdy_enabled) {
        const auto irq_result = setup_imu_irqs();
        ESP_LOGW(tag, "IMU_DRDY_SETUP %s GPIO_TOP=%d GPIO_TOE=%d; ODR100; registered pins remain disabled until per-site init/readback/status clear; IRQ rate != sample rate; fallback=%s",
            esp_err_to_name(irq_result), board::pin::imu_top_int1, board::pin::imu_toe_int1, imu_irqs_ready ? "timeout_counted" : "POLLING_ONLY");
    }
    started = true;
    xEventGroupSetBits(events, runtime_ready);
    return ESP_OK;
}
EventBits_t system_events() { return events ? (xEventGroupGetBits(events) & ~private_runtime_bits) : 0; }
static esp_err_t i2c_transaction_impl(I2cTransaction transaction, void* context
#ifdef CONFIG_NODE01_I2C_LOCK_DIAG_TRACE
    , const drivers::I2cTraceOperation* operation=nullptr, const bool* sdk_entered=nullptr
#endif
) {
    if (!i2c_mutex) return ESP_ERR_INVALID_STATE;
    if (!transaction) return ESP_ERR_INVALID_ARG;
    static_assert(configUSE_MUTEXES == 1 && INCLUDE_uxTaskPriorityGet == 1 && INCLUDE_xSemaphoreGetMutexHolder == 1);
    const auto task = reinterpret_cast<std::uintptr_t>(xTaskGetCurrentTaskHandle());
    const auto initial_priority = uxTaskPriorityGet(nullptr);
    bool acquired = false;
    std::uint64_t generation = 0;
    policy::LockWait wait;
#ifdef CONFIG_NODE01_I2C_LOCK_DIAG_TRACE
    lock_diagnostic::Request finite_request;
#endif
    const auto result = policy::locked_transaction([&] {
        portENTER_CRITICAL(&i2c_trace_lock);
        wait = i2c_lock_trace.before_wait(esp_timer_get_time(), task, initial_priority);
        portEXIT_CRITICAL(&i2c_trace_lock);
        const auto wait_started = esp_timer_get_time();
        wait.started_us = wait_started;
#ifdef CONFIG_NODE01_I2C_LOCK_DIAG_TRACE
        if(operation) {
            const auto stamp=finite_stamp();
            // 1=start-conversion, 2=poll/result; reg/op further identify phase.
            const auto stage=stamp.task==static_cast<std::uint8_t>(TaskId::SlowSensor)?finite_ads_stage:0;
            finite_locked([&]{finite_request=finite_i2c_trace.request(stamp,*operation,
                drivers::timing::guarded_wait_ticks(config::i2c_mutex_timeout_ms,configTICK_RATE_HZ),stage);});
        }
#endif
        acquired = xSemaphoreTake(i2c_mutex,
            drivers::timing::guarded_wait_ticks(config::i2c_mutex_timeout_ms, configTICK_RATE_HZ)) == pdTRUE;
#ifdef CONFIG_NODE01_I2C_LOCK_DIAG_TRACE
        if(operation) {
            const auto stamp=finite_stamp();finite_locked([&]{finite_i2c_trace.returned(finite_request,stamp,acquired);});
        }
#endif
        const auto waited = bounded_us(esp_timer_get_time() - wait_started);
        i2c_lock_wait_us.fetch_add(waited); update_max(i2c_lock_wait_max_us, waited);
        if (!acquired) {
            i2c_timeouts.fetch_add(1);
            const auto holder = reinterpret_cast<std::uintptr_t>(xSemaphoreGetMutexHolder(i2c_mutex));
            portENTER_CRITICAL(&i2c_trace_lock);
            i2c_lock_trace.timeout(wait, esp_timer_get_time(), holder);
            portEXIT_CRITICAL(&i2c_trace_lock);
        } else {
            const auto priority = uxTaskPriorityGet(nullptr);
            portENTER_CRITICAL(&i2c_trace_lock);
            generation = i2c_lock_trace.acquired(esp_timer_get_time(), task, priority);
            portEXIT_CRITICAL(&i2c_trace_lock);
        }
        return acquired;
    }, [&] {
        const auto priority = uxTaskPriorityGet(nullptr);
        portENTER_CRITICAL(&i2c_trace_lock);
        i2c_lock_trace.before_give(generation, esp_timer_get_time(), priority);
        portEXIT_CRITICAL(&i2c_trace_lock);
#ifdef CONFIG_NODE01_I2C_LOCK_DIAG_TRACE
        if(operation) {
            const auto stamp=finite_stamp();finite_locked([&]{finite_i2c_trace.give_begin(finite_request,stamp);});
        }
#endif
        const bool gave = xSemaphoreGive(i2c_mutex) == pdTRUE;
#ifdef CONFIG_NODE01_I2C_LOCK_DIAG_TRACE
        if(operation) {
            const auto stamp=finite_stamp();finite_locked([&]{finite_i2c_trace.give_end(finite_request,stamp,gave);});
        }
#endif
        portENTER_CRITICAL(&i2c_trace_lock);
        i2c_lock_trace.released(generation, gave);
        portEXIT_CRITICAL(&i2c_trace_lock);
    }, [&] {
        const auto begin = esp_timer_get_time();
        const auto sdk_result = transaction(context);
#ifdef CONFIG_NODE01_I2C_LOCK_DIAG_TRACE
        if(operation) {
            const auto stamp=finite_stamp();finite_locked([&]{finite_i2c_trace.sdk_return(finite_request,stamp,sdk_result,sdk_entered && *sdk_entered);});
        }
#endif
        const auto elapsed = static_cast<std::uint32_t>(esp_timer_get_time() - begin);
        i2c_busy_us.fetch_add(elapsed); update_max(i2c_max_transfer_us, elapsed);
        return sdk_result;
    }, ESP_ERR_TIMEOUT);
    if (acquired && result != ESP_OK) i2c_errors.fetch_add(1);
    return result;
}
esp_err_t with_i2c_transaction(I2cTransaction transaction, void* context) {
    return i2c_transaction_impl(transaction,context);
}
#ifdef CONFIG_NODE01_I2C_LOCK_DIAG_TRACE
namespace {
esp_err_t finite_i2c_executor(I2cTransaction transaction,void* context,const drivers::I2cTraceOperation& operation,const bool* entered) {
    return i2c_transaction_impl(transaction,context,&operation,entered);
}
}
#endif
void publish_imus(const std::array<sampling::ImuSample, 2>& group) {
    sensor_store.commit_imus(group);
}
void publish_soils(const std::array<sampling::SoilSample, 3>& group) {
    sensor_store.commit_soils(group);
}
sampling::SensorSnapshot sensor_snapshot() {
    return sensor_store.read();
}
risk_runtime::Snapshot risk_snapshot() {
    portENTER_CRITICAL(&snapshot_lock);
    const auto copy = risk_state;
    portEXIT_CRITICAL(&snapshot_lock);
    return copy;
}
void imu_notify_from_isr(void* context) {
    const auto site = reinterpret_cast<std::uintptr_t>(context);
    if (site > 1) return;
    const auto now = static_cast<std::uint64_t>(esp_timer_get_time());
    portENTER_CRITICAL_ISR(&irq_lock);
    ++imu_irqs[site].edges; imu_irqs[site].last_edge_us = now;
    const bool armed = imu_irq_gates[site].may_notify();
    const bool notify = imu_irq_gates[site].claim_notification();
    if (!armed) ++imu_irqs[site].suppressed_unarmed;
    else if (!notify) ++imu_irqs[site].notify_coalesced;
    else ++imu_irqs[site].notify_claims;
    portEXIT_CRITICAL_ISR(&irq_lock);
    if (!notify) return; // every raw edge counted; notifications explicitly coalesced per frame
    const auto handle = handles[index(TaskId::Imu)];
    if (!handle) return;
    BaseType_t wake = pdFALSE;
    xTaskNotifyFromISR(handle, 1U << site, eSetBits, &wake);
    portYIELD_FROM_ISR(wake);
}
} // namespace node::runtime
