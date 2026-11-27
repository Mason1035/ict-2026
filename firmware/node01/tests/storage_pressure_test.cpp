#include "node/storage_recovery.hpp"
#include "node/runtime_policy.hpp"
#include "node/acquisition_policy.hpp"
#include "node/storage_pressure.hpp"
#include <algorithm>
#include <array>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <deque>
#include <limits>
#include <string>
#include <vector>

// TEST_ONLY deterministic scheduling model. All generated inputs are SYNTHETIC.
// This executes the production writer, index allocator and service policy, but
// not FreeRTOS, real sensor clocks, FATFS/card busy time or physical SD I/O.
// Normal I/O latencies below are explicit arbitrary model parameters, not SD
// measurements. Tail durations are controlled injections, not a reconstruction
// of the unavailable per-operation history of either real hardware run.
namespace {
using node::sampling::AcquisitionRecord;
using node::storage::Operation;
using node::storage::RecoveryWriter;
using node::storage::VerifyResult;
namespace policy = node::runtime::policy;
struct NoLock { void lock() {} void unlock() {} }; // one deterministic thread

enum class InjectAt { Append, Flush };
struct Tail { InjectAt operation; unsigned ordinal; std::uint64_t duration_us; };
struct Plan { const char* name; std::vector<Tail> tails; };
struct ModelBackend final : node::storage::Backend {
    std::uint64_t us = 0;
    bool priming = true;
    unsigned append_calls = 0, flush_calls = 0, verify_steps = 0, closes = 0;
    std::vector<AcquisitionRecord> accepted;
    const Plan& plan;
    explicit ModelBackend(const Plan& p) : plan(p) {}
    std::uint64_t latency(InjectAt at, unsigned ordinal, std::uint64_t normal) const {
        if (priming) return 0;
        for (const auto& tail : plan.tails)
            if (tail.operation == at && tail.ordinal == ordinal) return tail.duration_us;
        return normal;
    }
    bool recover() override { return true; }
    bool append(const AcquisitionRecord& r) override {
        accepted.push_back(r);
        us += latency(InjectAt::Append, ++append_calls, 1000);
        return true;
    }
    bool flush() override { us += latency(InjectAt::Flush, ++flush_calls, 500); return true; }
    bool close_and_verify() override { assert(false); return false; }
    bool open_next() override { assert(false); return false; }
    void abandon() override { assert(false); }
    bool deferred_verification() const override { return true; }
    bool begin_verify() override { ++closes; us += 1000; return true; }
    VerifyResult verify_step() override {
        us += 500;
        return ++verify_steps < 10 ? VerifyResult::Pending : VerifyResult::Passed;
    }
};

struct Result {
    unsigned capacity = 0, initial = 0, produced = 0, live_produced = 0;
    unsigned enqueued = 0, dequeued = 0, dropped = 0, peak = 0;
    unsigned explicit_yields = 0, catchups = 0;
    std::uint64_t capture_us = 0, elapsed_us = 0, last_tail_us = 0, recovered_us = 0;
    bool bounded_catchup = false;
};

struct Simulation {
    const unsigned capacity;
    const bool catchup;
    const std::uint64_t duration_us;
    ModelBackend backend;
    RecoveryWriter writer;
    policy::StorageServiceBudget budget{32, 50000};
    policy::DiagnosticSequence<NoLock> sequence;
    std::deque<AcquisitionRecord> queue;
    std::vector<AcquisitionRecord> generated;
    std::vector<std::uint64_t> failed_ids;
    std::uint64_t next_imu_us = 10000, next_soil_us = 500000;
    Result result;
    unsigned guard = 0;

    Simulation(unsigned cap, unsigned initial, bool use_catchup, const Plan& plan,
            std::uint64_t duration = 5000000)
        : capacity(cap), catchup(use_catchup), duration_us(duration), backend(plan),
          writer(backend, 256, std::numeric_limits<unsigned>::max()) {
        assert(initial <= capacity);
        result.capacity = cap; result.initial = initial; result.bounded_catchup = catchup;
        result.capture_us = duration_us;
        writer.step(0);
        // Explicit precondition: 255 previously produced/accepted rows. The
        // next real writer step is append 256 then flush 1, so adjacent injected
        // append/flush tails exercise the unchanged 256-row sync policy.
        // These are accounted historical model rows, not new 206/s events.
        for (unsigned i = 0; i < 255; ++i) {
            produce(node::sampling::RecordKind::Imu, i % 2, 0, false);
            consume_one(); writer.step(0);
        }
        assert(writer.stats().append_accepted == 255 && queue.empty() && !writer.has_pending());
        for (unsigned i = 0; i < initial; ++i)
            produce(node::sampling::RecordKind::Imu, i % 2, 0, false);
        backend.priming = false;
    }
    void produce(node::sampling::RecordKind kind, unsigned channel, std::uint64_t when, bool live) {
        AcquisitionRecord r;
        r.kind = kind; r.channel = channel; r.attempted_uptime_us = when;
        r.imu.validity = node::sampling::Validity::Valid;
        r.imu.acquired_uptime_us = when;
        r.soil.validity = node::sampling::Validity::Valid;
        r.soil.acquired_uptime_us = when;
        r.soil.raw = static_cast<std::int16_t>(100 + generated.size() % 30000);
        for (unsigned axis = 0; axis < 6; ++axis)
            r.imu_raw[axis] = static_cast<std::int16_t>(100 + (generated.size() + axis * 13) % 30000);
        const auto outcome = policy::enqueue_record(r, sequence, [&](const auto& value) {
            if (queue.size() == capacity) return false;
            queue.push_back(value);
            result.peak = std::max(result.peak, static_cast<unsigned>(queue.size()));
            return true;
        });
        assert(outcome != policy::QueueResult::IndexExhausted);
        assert(r.acquisition_index == generated.size());
        generated.push_back(r); ++result.produced;
        if (live) ++result.live_produced;
        if (outcome == policy::QueueResult::Accepted) ++result.enqueued;
        else { ++result.dropped; failed_ids.push_back(r.acquisition_index); }
    }
    bool producers_done() const { return next_imu_us > duration_us && next_soil_us > duration_us; }
    void produce_until(std::uint64_t now) {
        // Ties are explicitly producer-first, TOP then TOE then Soil0/1/2.
        // Production continues DURING a blocked backend step at its original
        // deterministic event times; no consumer runs while that call blocks.
        while (std::min(next_imu_us, next_soil_us) <= std::min(now, duration_us)) {
            const auto when = std::min(next_imu_us, next_soil_us);
            if (next_imu_us == when) {
                produce(node::sampling::RecordKind::Imu, 0, when, true);
                produce(node::sampling::RecordKind::Imu, 1, when, true);
                next_imu_us += 10000;
            }
            if (next_soil_us == when) {
                for (unsigned ch = 0; ch < 3; ++ch)
                    produce(node::sampling::RecordKind::Soil, ch, when, true);
                next_soil_us += 500000;
            }
        }
    }
    void consume_one() {
        assert(writer.can_take_record() && !queue.empty());
        assert(writer.take_record(queue.front())); queue.pop_front(); ++result.dequeued;
    }
    Result run() {
        while (!writer.finished() && ++guard < 100000) {
            produce_until(backend.us);
            if (writer.can_take_record() && queue.empty() && !producers_done() && !writer.verification_active()) {
                // Model the actual blocking queue wait, not an arbitrary busy
                // loop: idle time resets the cooperative work quota.
                budget.reset();
                backend.us = std::max(backend.us, std::min(next_imu_us, next_soil_us));
                produce_until(backend.us);
            }
            if (writer.can_take_record() && !queue.empty()) consume_one();
            if (producers_done() && queue.empty() && !writer.has_pending()) writer.request_finish();
            const auto started = backend.us;
            writer.step(backend.us / 1000);
            const auto elapsed = backend.us - started;
            produce_until(backend.us);
            if (elapsed >= 200000) {
                result.last_tail_us = backend.us;
                result.recovered_us = 0; // recovery belongs to this latest tail
            }
            if (result.last_tail_us && !result.recovered_us && queue.empty() && !writer.has_pending())
                result.recovered_us = backend.us;
            budget.observe(elapsed, writer.last_operation() == Operation::AppendAccepted);
            if (!writer.finished()) {
                const auto action = catchup ? budget.action(static_cast<unsigned>(queue.size()), 128) :
                    (budget.yield_due() ? policy::StorageServiceAction::Yield : policy::StorageServiceAction::Continue);
                if (action == policy::StorageServiceAction::CatchUp) ++result.catchups;
                if (action == policy::StorageServiceAction::Yield) {
                    ++result.explicit_yields; budget.reset(); backend.us += 10000;
                    produce_until(backend.us);
                }
            }
            assert(queue.size() <= capacity);
        }
        assert(guard < 100000 && writer.finished() && queue.empty() && !writer.has_pending());
        const auto expected_live = 2 * (duration_us / 10000) + 3 * (duration_us / 500000);
        assert(result.live_produced == expected_live); // exact event count, not a measured hardware rate
        assert(result.produced == 255 + result.initial + result.live_produced);
        assert(result.enqueued + result.dropped == result.produced);
        assert(result.enqueued == result.dequeued && result.dequeued == backend.accepted.size());
        assert(writer.stats().append_accepted == result.dequeued);
        assert(writer.stats().flush_accepted == result.dequeued);
        assert(writer.stats().verified_rows == result.dequeued && writer.stats().verified_files == 1);
        assert(writer.stats().errors == 0); // queue loss can occur without API errors
        assert(backend.closes == 1);
        std::vector<std::uint64_t> saved_ids;
        for (const auto& r : backend.accepted) {
            assert(r.acquisition_index < generated.size());
            const auto& expected = generated[static_cast<std::size_t>(r.acquisition_index)];
            assert(r.kind == expected.kind && r.channel == expected.channel);
            assert(r.attempted_uptime_us == expected.attempted_uptime_us && r.error == expected.error);
            assert(r.imu_raw == expected.imu_raw && r.imu.validity == expected.imu.validity);
            assert(r.soil.raw == expected.soil.raw && r.soil.validity == expected.soil.validity);
            assert(r.imu.acquired_uptime_us == expected.imu.acquired_uptime_us);
            assert(r.soil.acquired_uptime_us == expected.soil.acquired_uptime_us);
            if (!saved_ids.empty()) assert(saved_ids.back() < r.acquisition_index);
            saved_ids.push_back(r.acquisition_index);
        }
        std::vector<std::uint64_t> missing;
        for (std::uint64_t id = 0; id < generated.size(); ++id)
            if (!std::binary_search(saved_ids.begin(), saved_ids.end(), id)) missing.push_back(id);
        assert(missing == failed_ids); // never renumber or replay a dropped row
        result.elapsed_us = backend.us;
        return result;
    }
};

void sampled_pressure_observation() {
    policy::StoragePressure pressure(192, 128);
    policy::StorageQueueSample sample;
    sample.depth = 191; sample.observed_us = 10;
    pressure.observe(sample); assert(!pressure.snapshot(20).high);
    sample.depth = 192; sample.observed_us = 100; sample.acquisition_index = 3820;
    sample.has_index = true; sample.io_operation = 3; sample.io_started_us = 50;
    pressure.observe(sample);
    sample.depth = 150; sample.observed_us = 200;
    pressure.observe(sample); assert(pressure.snapshot(250).high); // hysteresis
    sample.depth = 256; sample.observed_us = 300; sample.acquisition_index = 3823; sample.dropped = true;
    pressure.observe(sample);
    sample.observed_us = 310; sample.acquisition_index = 3831; pressure.observe(sample);
    auto state = pressure.snapshot(400);
    assert(state.high_entries == 1 && state.drops == 2 && state.peak == 256);
    assert(state.first_high.acquisition_index == 3820 && state.first_drop.acquisition_index == 3823);
    assert(state.last_drop.acquisition_index == 3831 && state.last_drop.io_operation == 3);
    assert(state.first_drop.io_started_us == 50 && state.high_total_us == 300 && state.high_max_us == 300);
    // snapshot is non-mutating and does not overcount repeated observations.
    assert(pressure.snapshot(400).high_total_us == 300);
    assert(pressure.snapshot(99).high_total_us == 0); // backwards, no underflow
    sample.depth = 128; sample.observed_us = 500; sample.dropped = false;
    pressure.observe(sample); state = pressure.snapshot(1000);
    assert(!state.high && state.recoveries == 1 && state.high_total_us == 400 && state.recovered_us == 500);
    sample.depth = 192; sample.observed_us = 1200; sample.acquisition_index = 6950; pressure.observe(sample);
    sample.depth = 256; sample.observed_us = 1300; sample.acquisition_index = 6953; sample.dropped = true; pressure.observe(sample);
    state = pressure.snapshot(1400);
    assert(state.high_entries == 2 && state.high_total_us == 600 && state.high_max_us == 400);
    assert(state.first_high.acquisition_index == 3820 && state.last_high.acquisition_index == 6950);
    assert(state.first_drop.acquisition_index == 3823 && state.last_drop.acquisition_index == 6953 && state.drops == 3);
    sample.depth = 0; sample.observed_us = 1199; sample.dropped = false; pressure.observe(sample);
    state = pressure.snapshot(1500);
    assert(state.high && state.late_samples == 1 && state.high_total_us == 700); // stale recovery cannot close current interval
    policy::StoragePressure delayed(192, 128);
    policy::StorageQueueSample event;
    event.depth = 192; event.observed_us = 100; delayed.observe(event);
    event.depth = 0; event.observed_us = 200; delayed.observe(event);
    event.depth = 192; event.observed_us = 150; delayed.observe(event);
    state = delayed.snapshot(300);
    assert(!state.high && state.late_samples == 1 && state.high_total_us == 100); // no overlapping interval
    event.depth = 512; event.dropped = true; event.has_index = true; event.acquisition_index = 42;
    delayed.observe(event);
    delayed.copy_snapshot(state, 300);
    assert(state.drops == 1 && state.peak == 512 && state.first_drop.acquisition_index == 42);
    assert(state.first_drop.observed_us == 150 && state.late_samples == 2 && state.high_total_us == 100);
}

void print_case(const Plan& plan, const Result& r) {
    std::printf("STORAGE_PRESSURE_CASE {\"scenario\":\"%s\",\"queue_capacity\":%u,\"initial_backlog\":%u,\"bounded_catchup\":%s,\"produced\":%u,\"live_produced\":%u,\"dequeued\":%u,\"drop\":%u,\"peak\":%u,\"yields\":%u,\"catchups\":%u,\"capture_us\":%llu,\"elapsed_us\":%llu,\"last_tail_us\":%llu,\"first_recovered_after_last_tail_us\":%llu}\n",
        plan.name, r.capacity, r.initial, r.bounded_catchup ? "true" : "false", r.produced, r.live_produced,
        r.dequeued, r.dropped, r.peak, r.explicit_yields, r.catchups,
        static_cast<unsigned long long>(r.capture_us), static_cast<unsigned long long>(r.elapsed_us), static_cast<unsigned long long>(r.last_tail_us),
        static_cast<unsigned long long>(r.recovered_us));
}
} // namespace

int main() {
    const std::vector<Plan> plans{
        {"normal", {}},
        {"append200ms", {{InjectAt::Append,256,200000}}},
        {"append500ms", {{InjectAt::Append,256,500000}}},
        {"append700ms", {{InjectAt::Append,256,700000}}},
        {"append821ms", {{InjectAt::Append,256,821102}}},
        {"append1000ms", {{InjectAt::Append,256,1000000}}},
        {"append500_flush500ms", {{InjectAt::Append,256,500000},{InjectAt::Flush,1,500000}}},
        {"append700_flush500ms", {{InjectAt::Append,256,700000},{InjectAt::Flush,1,500000}}},
        {"append821_flush695ms", {{InjectAt::Append,256,821102},{InjectAt::Flush,1,694826}}},
        {"three_flush700ms", {{InjectAt::Flush,1,700000},{InjectAt::Flush,2,700000},{InjectAt::Flush,3,700000}}}
    };
    unsigned cases = 0;
    for (unsigned capacity : {256U,512U,1024U}) {
        std::vector<unsigned> initials{0,50,100,128,150,200,256,capacity/2,capacity-1,capacity};
        std::sort(initials.begin(), initials.end()); initials.erase(std::unique(initials.begin(),initials.end()),initials.end());
        for (bool bounded : {false,true}) for (const auto& plan : plans) for (unsigned initial : initials) {
            if (initial > capacity) continue;
            const auto result = Simulation(capacity,initial,bounded,plan).run();
            if (std::string(plan.name) == "normal") assert(result.dropped == 0);
            if (initial == 0 && std::string(plan.name) == "append821ms") assert(result.dropped == 0);
            print_case(plan,result); ++cases;
        }
    }
    const auto& adjacent = plans[8];
    const auto old256 = Simulation(256,100,false,adjacent).run();
    const auto new256 = Simulation(256,100,true,adjacent).run();
    const auto new512 = Simulation(512,100,true,adjacent).run();
    assert(old256.dropped > 0 && new512.dropped == 0);
    assert(new256.dropped < old256.dropped); // removing one sleep helps, not a cure
    const Plan beyond_buffer{"append6000ms", {{InjectAt::Append,256,6000000}}};
    const auto still_finite = Simulation(1024,100,true,beyond_buffer).run();
    assert(still_finite.dropped > 0); // even 1024 cannot remove unbounded I/O tails
    print_case(beyond_buffer,still_finite); ++cases;
    const Plan normal120{"normal120s", {}};
    const auto sustained = Simulation(256,0,true,normal120,120000000).run();
    assert(sustained.live_produced == 24720 && sustained.produced == 24975);
    assert(sustained.dropped == 0 && sustained.dequeued == sustained.produced);
    print_case(normal120,sustained);
    sampled_pressure_observation();
    std::printf("STORAGE_PRESSURE_SUMMARY {\"matrix_cases\":%u,\"normal_120s_cases\":1,\"total_cases\":%u,\"old256_drop\":%u,\"catchup256_drop\":%u,\"catchup512_drop\":%u,\"over_capacity1024_drop\":%u,\"hardware\":\"NOT_RUN\"}\n",
        cases,cases+1,old256.dropped,new256.dropped,new512.dropped,still_finite.dropped);
    std::puts("HOST_STORAGE_PRESSURE_TEST_PASS (TEST_ONLY SYNTHETIC deterministic 206/s/controlled tails/queue ledger; HARDWARE_NOT_RUN)");
}
