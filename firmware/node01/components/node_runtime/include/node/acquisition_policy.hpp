#pragma once
#include <cstdint>

namespace node::runtime::policy {
enum class StorageServiceAction { Continue, CatchUp, Yield };
// Cooperative service quota, NOT a deadline for a blocking filesystem call.
// The owner resets it before a real queue wait: idle waiting must not consume
// the next burst's work budget. Operation wall time still includes preemption.
class StorageServiceBudget {
public:
    StorageServiceBudget(unsigned rows, std::uint64_t wall_us)
        : row_limit_(rows), wall_limit_(wall_us) {}
    void reset() { rows_ = 0; wall_us_ = 0; catchup_used_ = false; }
    void observe(std::uint64_t wall_us, bool appended) {
        wall_us_ += wall_us;
        if (appended) ++rows_;
    }
    bool yield_due() const { return rows_ >= row_limit_ || wall_us_ >= wall_limit_; }
    StorageServiceAction action(unsigned backlog, unsigned catchup_threshold) {
        if (!yield_due()) return StorageServiceAction::Continue;
        // A blocked call already consumed this wall budget. With backlog, allow
        // ONE extra quota to drain it before an explicit tick sleep. The next
        // quota must yield even if backlog stays high; no indefinite extension.
        if (backlog >= catchup_threshold && !catchup_used_) {
            rows_ = 0; wall_us_ = 0; catchup_used_ = true;
            return StorageServiceAction::CatchUp;
        }
        return StorageServiceAction::Yield;
    }
private:
    const unsigned row_limit_;
    const std::uint64_t wall_limit_;
    unsigned rows_ = 0;
    std::uint64_t wall_us_ = 0;
    bool catchup_used_ = false;
};
// Clock/queue independent capture control. Runtime serializes this small value
// with its snapshot lock; producers never wait for SD during acquisition.
struct CaptureObservation {
    bool started = false, stop_requested = false;
    std::uint32_t producers_done = 0;
    std::uint64_t started_us = 0, requested_stop_us = 0;
};
// Health snapshots include startup and post-stop idle. Keep that denominator
// explicit, and separately describe the overlap with actual capture activity.
constexpr std::uint64_t capture_overlap_us(std::uint64_t previous_us,
        std::uint64_t now_us, const CaptureObservation& capture) {
    if (!capture.started || !previous_us || now_us < previous_us) return 0;
    const auto begin = previous_us > capture.started_us ? previous_us : capture.started_us;
    const auto end = capture.stop_requested && capture.requested_stop_us < now_us
        ? capture.requested_stop_us : now_us;
    return end > begin ? end - begin : 0;
}
// Shared quota for IRQ and fallback. A frame attempts each site at most once,
// regardless of its success/empty/error result; the next frame uses real status
// again. This neither reconstructs missed samples nor changes the sensor ODR.
class ImuFrameBudget {
public:
    bool may_read(unsigned site) const { return site < 2 && !(serviced_ & (1U << site)); }
    bool claim(unsigned site) {
        if (!may_read(site)) return false;
        serviced_ |= 1U << site; return true;
    }
    bool awaiting(std::uint32_t irq_mask) const { return (irq_mask & 3U & ~serviced_) != 0; }
private:
    std::uint32_t serviced_ = 0;
};
class CaptureWindow {
public:
    explicit CaptureWindow(unsigned seconds) : duration_us_(seconds * 1000000ULL) {}
    bool configure_before_begin(unsigned seconds) {
        if (state_.started) return false;
        duration_us_ = seconds * 1000000ULL; return true;
    }
    bool request_stop(std::uint64_t now) {
        if (!state_.started || state_.stop_requested || now < state_.started_us) return false;
        state_.stop_requested = true; state_.requested_stop_us = now; return true;
    }
    void begin(std::uint64_t now) {
        if (!state_.started) { state_.started = true; state_.started_us = now; }
    }
    bool poll(std::uint64_t now) {
        if (state_.started && duration_us_ && now >= state_.started_us &&
                now - state_.started_us >= duration_us_ && !state_.stop_requested) {
            state_.stop_requested = true; state_.requested_stop_us = now;
        }
        return state_.stop_requested;
    }
    void producer_done(std::uint32_t bit) { state_.producers_done |= bit; }
    bool drained_producers(std::uint32_t expected) const {
        return state_.stop_requested && (state_.producers_done & expected) == expected;
    }
    CaptureObservation observation() const { return state_; }
private:
    std::uint64_t duration_us_;
    CaptureObservation state_{};
};
// IRQ edge coalescence is an observation, NOT an exact lost-sample counter.
// A latched pin cannot enumerate updates that occurred while it stayed high.
class EdgeCursor {
public:
    std::uint32_t pending(std::uint32_t edges) const {
        return static_cast<std::uint32_t>(edges - last_);
    }
    std::uint32_t consume(std::uint32_t edges) {
        const auto delta = pending(edges);
        last_ = edges; return delta;
    }
private:
    std::uint32_t last_ = 0;
};
class IrqFallback {
public:
    void observed_edge() { polling_ = false; }
    bool poll_needed(std::uint64_t now, std::uint64_t last_valid, std::uint64_t timeout) {
        if (!last_valid || (now >= last_valid && now - last_valid >= timeout)) polling_ = true;
        return polling_; // no IRQ wiring must retain 100Hz polling, not degrade to 50Hz
    }
private: bool polling_ = true;
};
template<class Tick> Tick remaining_ticks(Tick now, Tick due) {
    const auto delta = static_cast<Tick>(due - now);
    constexpr Tick half = Tick{1} << (sizeof(Tick) * 8 - 1);
    return delta < half ? delta : 0; // wrap-safe; frame is much less than half-range
}
}
