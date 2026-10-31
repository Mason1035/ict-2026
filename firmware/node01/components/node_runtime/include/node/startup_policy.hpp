#pragma once

namespace node::runtime::startup {
enum class Plan { Concurrent, Probe, ImuFirst };
enum class InitState { Pending, Ready, Failed };
enum class Gate { Wait, Proceed, Blocked };

constexpr bool probes_enabled(Plan plan, bool sensor_only) {
    return sensor_only || plan == Plan::Probe;
}

// The caller supplies the three frozen board addresses. One pass, including
// failed probes; no register access, retry, delay or handle operation is hidden
// in this policy. Runtime owns the actual SDK callback and its error logging.
template<class Addresses, class Probe>
constexpr void run_probes(bool enabled, const Addresses& addresses, Probe probe) {
    if (enabled) for (const auto address : addresses) probe(address);
}

constexpr Gate slow_gate(Plan plan, InitState top, InitState toe) {
    // Keep original ADS/IMU concurrency in the baseline and Probe experiment.
    if (plan != Plan::ImuFirst) return Gate::Proceed;
    if (top == InitState::Failed || toe == InitState::Failed) return Gate::Blocked;
    return top == InitState::Pending || toe == InitState::Pending ? Gate::Wait : Gate::Proceed;
}

constexpr Gate storage_gate(Plan plan, InitState top, InitState toe, InitState ads) {
    // Keep original SD/sensor concurrency except in the declared order test.
    if (plan != Plan::ImuFirst) return Gate::Proceed;
    const auto imu = slow_gate(plan, top, toe);
    if (imu == Gate::Blocked || ads == InitState::Failed) return Gate::Blocked;
    return imu == Gate::Wait || ads == InitState::Pending ? Gate::Wait : Gate::Proceed;
}

constexpr Gate capture_gate(Plan plan, bool sensors, bool storage,
        InitState top, InitState toe, InitState ads, bool storage_ready) {
    if (sensors) {
        if (plan == Plan::ImuFirst && (top == InitState::Failed ||
                toe == InitState::Failed || ads == InitState::Failed)) return Gate::Blocked;
        if (top == InitState::Pending || toe == InitState::Pending ||
                ads == InitState::Pending) return Gate::Wait;
        // Concurrent/Probe may record explicit Error diagnostics for completed
        // failed sensors. This is not a claim of valid/full sensor coverage.
    }
    // The owner applies its bounded startup timeout and sticky abort. A late
    // SD ready event must never undo that abort or backdate a capture epoch.
    return storage && !storage_ready ? Gate::Wait : Gate::Proceed;
}

enum class AbortAction { None, FinishEmptyFile, ParkVerified, StopUnverified };
constexpr bool may_begin_capture(Gate gate, bool aborted) {
    return !aborted && gate == Gate::Proceed;
}
constexpr AbortAction abort_action(bool capture_started, bool aborted,
        bool writer_active, bool writer_verifying, bool writer_finished) {
    // Only pre-capture aborts belong here. After an epoch exists, use the
    // ordinary producer stop -> drain -> close/full verification path.
    // Caller guarantees pre-capture producers have enqueued no records.
    if (capture_started || !aborted) return AbortAction::None;
    if (writer_finished) return AbortAction::ParkVerified;
    // RecoveryWriter::active() is false during final deferred readback. It
    // must still finish that verifier before a startup file can be called closed.
    return writer_active || writer_verifying ? AbortAction::FinishEmptyFile : AbortAction::StopUnverified;
}
} // namespace node::runtime::startup
