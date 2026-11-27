#pragma once
#include "node/acquisition.hpp"
#include <limits>
#include <type_traits>

namespace node::runtime::policy {
// The Runtime supplies the real FreeRTOS Take/Give and timed SDK callback.
// Keep this ownership boundary shared with Host fault injection: no SDK call
// or Give after a failed Take, and exactly one Give after any acquired result.
template<class Take, class Give, class Run, class Result>
Result locked_transaction(Take take, Give give, Run run, Result timeout) {
    if (!take()) return timeout;
    struct Release { Give& give; ~Release() { give(); } } release{give};
    return run();
}
inline bool fresh(std::optional<std::uint64_t> acquired, std::uint64_t now, std::uint64_t max_age) {
    return acquired && now >= *acquired && now - *acquired <= max_age;
}
// Lock must supply lock()/unlock(). Firmware uses a short portMUX section;
// host tests use a real mutex. No I/O is performed while this lock is held.
template<class Lock> class Guard {
public:
    explicit Guard(Lock& lock) : lock_(lock) { lock_.lock(); }
    ~Guard() { lock_.unlock(); }
    Guard(const Guard&) = delete;
    Guard& operator=(const Guard&) = delete;
private: Lock& lock_;
};
template<class Lock> class SnapshotStore {
public:
    void commit_imus(const std::array<sampling::ImuSample, 2>& group) {
        Guard<Lock> guard(lock_); snapshot_.imu = group;
    }
    void commit_soils(const std::array<sampling::SoilSample, 3>& group) {
        Guard<Lock> guard(lock_); snapshot_.soil = group;
    }
    sampling::SensorSnapshot read() const {
        Guard<Lock> guard(lock_); return snapshot_;
    }
private:
    mutable Lock lock_;
    sampling::SensorSnapshot snapshot_{};
};
template<class Lock> class DiagnosticSequence {
public:
    std::optional<std::uint64_t> next() {
        Guard<Lock> guard(lock_);
        if (exhausted_) return std::nullopt;
        const auto value = next_;
        if (next_ == std::numeric_limits<std::uint64_t>::max()) exhausted_ = true;
        else ++next_;
        return value;
    }
private: Lock lock_; std::uint64_t next_ = 0; bool exhausted_ = false;
};
enum class QueueResult { Accepted, QueueFull, IndexExhausted };
template<class Sequence, class Send>
QueueResult enqueue_record(sampling::AcquisitionRecord& record, Sequence& sequence, Send send) {
    const auto id = sequence.next();
    if (!id) return QueueResult::IndexExhausted;
    record.acquisition_index = *id; // reserve even on drop, so missing records are detectable
    return send(record) ? QueueResult::Accepted : QueueResult::QueueFull;
}
struct ConversionResult { PortStatus status; bool timed_out; };
template<class Now, class Wait>
ConversionResult wait_conversion(drivers::Ads1115& adc, sampling::SoilSample& sample,
        std::uint64_t timeout_us, unsigned max_polls, Now now, Wait wait) {
    const auto start = now();
    for (unsigned poll = 0; poll < max_polls; ++poll) {
        wait(); // never owns I2C mutex; count cap also handles a broken/frozen clock
        if (now() - start >= timeout_us) break;
        const auto state = adc.try_read_conversion(sample);
        if (state != PortStatus::Unavailable) return {state, false};
    }
    sample = {}; sample.validity = sampling::Validity::Error;
    return {PortStatus::Error, true};
}
enum class PeriodOutcome { Slept, Boundary, Late };
template<class Tick> PeriodOutcome period_outcome(bool delayed, Tick scheduled_wake, Tick now) {
    static_assert(std::is_integral_v<Tick> && std::is_unsigned_v<Tick>, "tick comparison requires unsigned ticks");
    if (delayed) return PeriodOutcome::Slept;
    // xTaskDelayUntil updates last_wake even when it returns FALSE. FALSE also
    // means exactly on the scheduled tick, which is not a missed tick deadline.
    // As with RTOS tick comparisons, observations must be < half the tick range
    // apart; the modular difference then also handles counter rollover.
    const Tick late_ticks = static_cast<Tick>(now - scheduled_wake);
    constexpr Tick half_range = Tick{1} << (std::numeric_limits<Tick>::digits - 1);
    return late_ticks != 0 && late_ticks < half_range ? PeriodOutcome::Late : PeriodOutcome::Boundary;
}
template<class Tick> void rebase_after_yield(Tick& last_wake, Tick now_after_yield) {
    // Rebasing before a one-tick delay leaves a one-tick-period task's next
    // deadline in the past forever, even after its workload becomes short.
    last_wake = now_after_yield;
}
class ProgressWatch {
public:
    explicit ProgressWatch(std::uint64_t start_ms) : last_ms_(start_ms) {}
    bool observe(std::uint32_t value, std::uint64_t now_ms, std::uint64_t timeout_ms, bool may_block) {
        if (value != previous_) { previous_ = value; last_ms_ = now_ms; }
        return !may_block && now_ms - last_ms_ > timeout_ms;
    }
private: std::uint32_t previous_ = 0; std::uint64_t last_ms_;
};
} // namespace node::runtime::policy
