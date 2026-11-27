#include "node/runtime_policy.hpp"
#include <atomic>
#include <cassert>
#include <deque>
#include <mutex>
#include <thread>

// TEST_ONLY: same policy code used by Runtime, real host threads/mutex;
// this does not emulate FreeRTOS scheduling, I2C or hardware timing.
class NeverReady final : public node::drivers::Ads1115 {
public:
    node::PortStatus status() const override { return node::PortStatus::Ready; }
    node::PortStatus start_conversion(unsigned) override { return node::PortStatus::Ready; }
    node::PortStatus try_read_conversion(node::sampling::SoilSample&) override {
        ++polls; return node::PortStatus::Unavailable;
    }
    unsigned polls = 0;
};
namespace {
// TEST_ONLY model of the SDK's strict-future wake comparison, not a scheduler
// emulator. Exercise the *sequence* after recovery, not merely wake assignment.
struct TickModel {
    std::uint32_t wake = 0, now = 0, increment = 1;
    node::runtime::policy::PeriodOutcome finish(std::uint32_t work_ticks) {
        using node::runtime::policy::period_outcome;
        now += work_ticks;
        const auto due = static_cast<std::uint32_t>(wake + increment);
        const auto until = static_cast<std::uint32_t>(due - now);
        const bool delayed = until != 0 && until < (std::uint32_t{1} << 31);
        wake = due; // xTaskDelayUntil always advances the scheduled wake time
        if (delayed) now = due;
        return period_outcome(delayed, wake, now);
    }
    void yield_and_rebase() {
        ++now; // caller's bounded vTaskDelay(1)
        node::runtime::policy::rebase_after_yield(wake, now);
    }
};
void period_recovery_tests() {
    using namespace node::runtime::policy;
    assert(period_outcome(true, 10U, 10U) == PeriodOutcome::Slept);
    assert(period_outcome(false, 10U, 10U) == PeriodOutcome::Boundary);
    assert(period_outcome(false, 10U, 11U) == PeriodOutcome::Late);
    constexpr auto max_tick = std::numeric_limits<std::uint32_t>::max();
    assert(period_outcome(false, max_tick, std::uint32_t{0}) == PeriodOutcome::Late);
    assert(period_outcome(false, std::uint32_t{0}, std::uint32_t{0}) == PeriodOutcome::Boundary);

    TickModel recovered;
    unsigned late = 0, slept = 0;
    for (unsigned i = 0; i < 8; ++i) {
        const auto outcome = recovered.finish(i == 0 ? 2 : 0);
        if (outcome == PeriodOutcome::Late) { ++late; recovered.yield_and_rebase(); }
        if (outcome == PeriodOutcome::Slept) ++slept;
    }
    assert(late == 1 && slept == 7); // first miss must not latch every later cycle

    TickModel boundary;
    assert(boundary.finish(1) == PeriodOutcome::Boundary);
    assert(boundary.now == 1 && boundary.wake == 1); // no additional delay on boundary
    assert(boundary.finish(0) == PeriodOutcome::Slept);

    TickModel overloaded;
    for (unsigned i = 0; i < 8; ++i) {
        assert(overloaded.finish(2) == PeriodOutcome::Late);
        overloaded.yield_and_rebase();
        assert(overloaded.wake == overloaded.now); // no catch-up backlog; caller has yielded
    }

    TickModel wrapped;
    wrapped.wake = wrapped.now = max_tick - 1;
    assert(wrapped.finish(2) == PeriodOutcome::Late);
    wrapped.yield_and_rebase();
    assert(wrapped.now == 1 && wrapped.wake == 1);
    assert(wrapped.finish(0) == PeriodOutcome::Slept);

    TickModel risk;
    risk.increment = 5; // original 50ms at 100Hz RTOS tick
    assert(risk.finish(7) == PeriodOutcome::Late);
    risk.yield_and_rebase();
    assert(risk.finish(0) == PeriodOutcome::Slept);
}
// TEST_ONLY discrete queue/load model, not SD, RTOS or real sensor timing.
// Uses the production enqueue policy and preserves every failed index.
struct FlowModel { unsigned produced = 0, accepted = 0, dequeued = 0, dropped = 0, peak = 0; };
FlowModel queue_tail_model(unsigned capacity, unsigned consumer_hz, unsigned stall_ms) {
    using namespace node;
    runtime::policy::DiagnosticSequence<std::mutex> sequence;
    std::deque<std::uint64_t> queue;
    FlowModel flow;
    unsigned consumer_credit = 0;
    std::uint64_t last_index = 0;
    bool consumed = false;
    auto produce = [&] {
        sampling::AcquisitionRecord value;
        ++flow.produced;
        const auto result = runtime::policy::enqueue_record(value, sequence, [&](const auto& r) {
            if (queue.size() == capacity) return false;
            queue.push_back(r.acquisition_index); return true;
        });
        if (result == runtime::policy::QueueResult::Accepted) ++flow.accepted;
        else { assert(result == runtime::policy::QueueResult::QueueFull); ++flow.dropped; }
        if (queue.size() > flow.peak) flow.peak = static_cast<unsigned>(queue.size());
    };
    auto consume = [&] {
        if (queue.empty()) return;
        const auto index = queue.front(); queue.pop_front();
        if (consumed) assert(index > last_index); // no duplicate/reordered replay
        last_index = index; consumed = true; ++flow.dequeued;
    };
    for (unsigned ms = 0; ms < 120000; ++ms) {
        if (ms % 10 == 0) { produce(); produce(); }
        if (ms % 500 == 0) { produce(); produce(); produce(); }
        const bool stalled = ms >= 10000 && ms < 10000 + stall_ms;
        if (stalled) { consumer_credit = 0; continue; }
        consumer_credit += consumer_hz;
        while (consumer_credit >= 1000) { consumer_credit -= 1000; consume(); }
    }
    while (!queue.empty()) consume(); // producers stopped, explicit drain
    assert(flow.produced == 24720);
    assert(flow.accepted == flow.dequeued);
    assert(flow.produced == flow.accepted + flow.dropped);
    assert(flow.peak <= capacity);
    return flow;
}
void queue_tail_tests() {
    const auto old_queue = queue_tail_model(128, 1000, 842);
    const auto new_queue = queue_tail_model(256, 1000, 842);
    assert(old_queue.dropped > 0 && old_queue.peak == 128);
    assert(new_queue.dropped == 0 && new_queue.peak > 128); // ONE isolated tail
    assert(queue_tail_model(256, 1000, 1428).dropped > 0); // adjacent append+flush can exceed it
    assert(queue_tail_model(256, 165, 0).dropped > 0); // a larger queue cannot fix sustained deficit
    assert(queue_tail_model(256, 300, 0).dropped == 0); // genuine service margin in this model
}
}
int main() {
    using namespace node;
    using namespace runtime::policy;
    assert(fresh(100, 130, 30) && !fresh(100, 131, 30));
    assert(!fresh(std::nullopt, 100, 30) && !fresh(101, 100, 30));
    DiagnosticSequence<std::mutex> sequence;
    std::deque<sampling::AcquisitionRecord> queue;
    auto send = [&](const sampling::AcquisitionRecord& value) {
        if (queue.size() == 2) return false;
        queue.push_back(value); return true;
    };
    sampling::AcquisitionRecord record;
    assert(enqueue_record(record, sequence, send) == QueueResult::Accepted);
    assert(enqueue_record(record, sequence, send) == QueueResult::Accepted);
    assert(enqueue_record(record, sequence, send) == QueueResult::QueueFull);
    assert(record.acquisition_index == 2 && queue.size() == 2);
    queue.pop_front();
    assert(enqueue_record(record, sequence, send) == QueueResult::Accepted);
    assert(record.acquisition_index == 3); // gap 2 survives failed enqueue

    NeverReady adc;
    std::uint64_t clock = 0;
    sampling::SoilSample sample;
    sample.raw = 123; sample.validity = sampling::Validity::Valid;
    auto result = wait_conversion(adc, sample, drivers::ads_conversion_timeout_us, 5,
        [&] { return clock; }, [&] { clock += 10000; });
    assert(result.timed_out && result.status == PortStatus::Error);
    assert(clock == 40000 && adc.polls == 3 && !sample.raw && !sample.acquired_uptime_us);
    assert(sample.validity == sampling::Validity::Error);
    // Even a frozen clock cannot leave the caller in an infinite unavailable loop.
    adc.polls = 0;
    result = wait_conversion(adc, sample, drivers::ads_conversion_timeout_us, 5,
        [] { return std::uint64_t{0}; }, [] {});
    assert(result.timed_out && adc.polls == 5);

    SnapshotStore<std::mutex> snapshots;
    std::array<sampling::SoilSample, 3> staged{};
    staged[0].raw = 11;
    assert(!snapshots.read().soil[0].raw); // half-collected group stays private
    staged[1].raw = 11; staged[2].raw = 11;
    snapshots.commit_soils(staged);
    assert(snapshots.read().soil[2].raw == 11);
    std::atomic<bool> done{false};
    std::thread reader([&] {
        do {
            const auto s = snapshots.read();
            assert(s.soil[0].raw == s.soil[1].raw && s.soil[1].raw == s.soil[2].raw);
            assert(s.imu[0].validity == s.imu[1].validity);
            if (s.imu[0].acquired_uptime_us)
                assert(*s.imu[1].acquired_uptime_us == *s.imu[0].acquired_uptime_us + 1);
        } while (!done.load());
    });
    for (unsigned generation = 1; generation <= 10000; ++generation) {
        for (auto& soil : staged) { soil.raw = generation; std::this_thread::yield(); }
        snapshots.commit_soils(staged);
        std::array<sampling::ImuSample, 2> imus{};
        for (unsigned k = 0; k < 2; ++k) {
            imus[k].validity = sampling::Validity::Valid;
            imus[k].acquired_uptime_us = generation * 10 + k;
            std::this_thread::yield();
        }
        snapshots.commit_imus(imus);
    }
    done = true; reader.join();

    period_recovery_tests();
    queue_tail_tests();

    ProgressWatch periodic(900000); // late runtime startup must not imply a stall
    assert(!periodic.observe(0, 900000, 30000, false));
    assert(!periodic.observe(0, 930000, 30000, false));
    assert(periodic.observe(0, 930001, 30000, false));
    assert(!periodic.observe(1, 930002, 30000, false));
    assert(!periodic.observe(1, 999999, 30000, true)); // legitimate Alarm wait
}
