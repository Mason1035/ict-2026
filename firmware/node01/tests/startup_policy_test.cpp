#include "node/startup_policy.hpp"
#include "node/acquisition_policy.hpp"
#include "node/imu_irq_policy.hpp"
#include "node/storage_recovery.hpp"
#include <algorithm>
#include <array>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <vector>

// TEST_ONLY deterministic policies and injected backend. This does NOT execute
// FreeRTOS events, SDK probes/I2C, physical startup timing or an SD filesystem.
namespace {
using namespace node::runtime::startup;
using node::runtime::policy::CaptureWindow;
using node::storage::RecoveryWriter;
using node::storage::VerifyResult;

struct FakeBackend final : node::storage::Backend {
    bool recover_ok = true, verify_ok = true;
    unsigned recoveries = 0, appends = 0, closes = 0, verifies = 0, abandoned = 0, opens = 0;
    bool recover() override { ++recoveries; return recover_ok; }
    bool append(const node::sampling::AcquisitionRecord&) override { ++appends; return true; }
    bool flush() override { return true; }
    bool open_next() override { ++opens; return true; }
    void abandon() override { ++abandoned; }
    bool close_and_verify() override { assert(false); return false; }
    bool deferred_verification() const override { return true; }
    bool begin_verify() override { ++closes; return true; }
    VerifyResult verify_step() override {
        ++verifies;
        if (!verify_ok) return VerifyResult::Failed;
        return verifies < 3 ? VerifyResult::Pending : VerifyResult::Passed;
    }
};

// Cooperative TEST_ONLY schedule explores permutations of task service order.
// Runtime uses these exact gates, but FreeRTOS event delivery is not simulated.
struct Boot {
    Plan plan;
    InitState top = InitState::Pending, toe = InitState::Pending, ads = InitState::Pending;
    bool abort = false, sd_ready = false, imu_attempted = false, ads_attempted = false, sd_attempted = false;
    bool fail_top = false, fail_toe = false, fail_ads = false, sd_stays_unready = false;
    unsigned sd_waits = 0, records = 0;
    std::uint64_t now = 1;
    CaptureWindow capture{120};
    std::vector<unsigned> operations;
    explicit Boot(Plan p) : plan(p) {}
    void service(unsigned task) {
        now += 1000;
        if (abort) return;
        if (task == 0) {
            if (!imu_attempted) {
                operations.push_back(0); top = fail_top ? InitState::Failed : InitState::Ready;
                operations.push_back(1); toe = fail_toe ? InitState::Failed : InitState::Ready;
                imu_attempted = true;
            }
            const auto gate = capture_gate(plan, true, true, top, toe, ads, sd_ready);
            if (gate == Gate::Blocked) abort = true;
            if (may_begin_capture(gate, abort)) capture.begin(now);
        } else if (task == 1 && !ads_attempted) {
            const auto gate = slow_gate(plan, top, toe);
            if (gate == Gate::Blocked) { abort = true; return; }
            if (gate == Gate::Wait) return;
            operations.push_back(2); ads_attempted = true;
            ads = fail_ads ? InitState::Failed : InitState::Ready;
        } else if (task == 2 && !sd_ready) {
            const auto gate = storage_gate(plan, top, toe, ads);
            if (gate == Gate::Blocked) { abort = true; return; }
            if (gate == Gate::Wait) return;
            if (!sd_attempted) { operations.push_back(3); sd_attempted = true; }
            if (++sd_waits >= 3 && !sd_stays_unready) { operations.push_back(4); sd_ready = true; }
        }
        if (capture.observation().started) {
            assert(sd_ready && top != InitState::Pending && toe != InitState::Pending && ads != InitState::Pending);
            if (plan == Plan::ImuFirst) assert(top == InitState::Ready && toe == InitState::Ready && ads == InitState::Ready);
        } else assert(records == 0);
    }
};

void probe_cases() {
    constexpr std::array<std::uint8_t, 3> addresses{0x68, 0x69, 0x48};
    for (const auto plan : {Plan::Concurrent, Plan::Probe, Plan::ImuFirst}) {
        for (bool isolation : {false, true}) for (bool bus_ready : {false, true}) for (int probe_error : {0, 259}) {
            std::vector<std::uint8_t> calls;
            std::vector<int> errors;
            run_probes(bus_ready && probes_enabled(plan, isolation), addresses, [&](std::uint8_t address) {
                calls.push_back(address); errors.push_back(address == 0x69 ? probe_error : 0);
            });
            const bool expected = bus_ready && (isolation || plan == Plan::Probe);
            assert(calls.size() == (expected ? 3U : 0U));
            if (expected) {
                assert(std::equal(calls.begin(), calls.end(), addresses.begin()));
                assert(errors[1] == probe_error); // failure is retained, not replaced by success or retried
            }
        }
    }
    // No production callback can mark either sensor Ready via this helper.
    node::drivers::ImuIrqGate toe;
    run_probes(true, addresses, [](std::uint8_t) {});
    assert(!toe.may_arm() && !toe.may_notify());
}

void schedules() {
    std::array<unsigned, 3> tasks{0,1,2};
    unsigned permutations = 0;
    bool concurrent_sd_before_imu = false;
    do {
        ++permutations;
        for (const auto plan : {Plan::Concurrent, Plan::Probe, Plan::ImuFirst}) {
            Boot boot(plan);
            for (unsigned round = 0; round < 8 && !boot.capture.observation().started; ++round)
                for (auto task : tasks) boot.service(task);
            assert(boot.capture.observation().started && !boot.abort);
            const auto position = [&](unsigned op) { return std::find(boot.operations.begin(), boot.operations.end(), op); };
            assert(position(0) < position(1)); // same ImuTask preserves TOP -> TOE
            assert(position(3) < position(4)); // mount/open complete before capture
            if (plan == Plan::ImuFirst) {
                assert(position(1) < position(2) && position(2) < position(3));
            } else if (position(3) < position(0)) concurrent_sd_before_imu = true;
            const auto epoch = boot.capture.observation().started_us;
            assert(epoch > 0 && !boot.capture.poll(epoch + 119999999ULL));
            assert(boot.capture.poll(epoch + 120000000ULL));
        }
        for (unsigned failed_sensor : {0U, 1U, 2U}) {
            Boot fail(Plan::ImuFirst); fail.fail_top = failed_sensor == 0;
            fail.fail_toe = failed_sensor == 1; fail.fail_ads = failed_sensor == 2;
            for (unsigned round = 0; round < 8 && !fail.abort; ++round)
                for (auto task : tasks) fail.service(task);
            assert(fail.abort && !fail.sd_attempted && !fail.capture.observation().started && fail.records == 0);
            if (failed_sensor != 2) assert(!fail.ads_attempted);
        }
        Boot degraded(Plan::Probe); degraded.fail_toe = true;
        for (unsigned round = 0; round < 8 && !degraded.capture.observation().started; ++round)
            for (auto task : tasks) degraded.service(task);
        assert(degraded.capture.observation().started && degraded.toe == InitState::Failed);
        node::drivers::ImuIrqGate toe;
        toe.initialized(degraded.toe == InitState::Ready); toe.arm_result(true);
        assert(!toe.may_arm() && !toe.may_notify()); // completed-failure is not Ready
    } while (std::next_permutation(tasks.begin(), tasks.end()));
    assert(permutations == 6 && concurrent_sd_before_imu);
    // Source-supported old fail-open behavior starts an epoch after a timeout.
    CaptureWindow old(120); old.begin(5000000); assert(old.observation().started);
    for (auto plan : {Plan::Concurrent, Plan::Probe, Plan::ImuFirst}) {
        Boot missing_sd(plan); missing_sd.sd_stays_unready = true;
        for (unsigned round = 0; round < 8; ++round) for (auto task : {0U,1U,2U}) missing_sd.service(task);
        assert(!missing_sd.capture.observation().started && missing_sd.records == 0);
        missing_sd.abort = true; // runtime bounded startup wait expires
        missing_sd.sd_ready = true; // late I/O completion cannot clear sticky abort
        const auto gate = capture_gate(plan,true,true,missing_sd.top,missing_sd.toe,missing_sd.ads,true);
        assert(gate == Gate::Proceed && !may_begin_capture(gate, missing_sd.abort));
        missing_sd.service(0);
        assert(!missing_sd.capture.observation().started && missing_sd.records == 0);
    }
    assert(capture_gate(Plan::Concurrent,false,true,InitState::Pending,InitState::Pending,InitState::Pending,true) == Gate::Proceed);
    assert(capture_gate(Plan::Concurrent,true,false,InitState::Ready,InitState::Ready,InitState::Ready,false) == Gate::Proceed);
}

void aborted_empty_file() {
    FakeBackend backend;
    RecoveryWriter writer(backend, 256, UINT32_MAX);
    writer.step(0); // a late mount+open really completed, but no epoch was promised
    assert(writer.active() && backend.recoveries == 1);
    bool saw_deferred = false;
    unsigned steps = 0;
    for (; steps < 10; ++steps) {
        const auto action = abort_action(false,true,writer.active(),writer.verification_active(),writer.finished());
        if (action == AbortAction::ParkVerified) break;
        assert(action == AbortAction::FinishEmptyFile);
        writer.request_finish(); writer.step(steps + 1);
        if (writer.verification_active()) {
            saw_deferred = true;
            assert(!writer.active()); // the real writer reports inactive during final verification
        }
    }
    assert(saw_deferred && steps < 10 && writer.finished());
    assert(writer.stats().verified_files == 1 && writer.stats().verified_rows == 0);
    assert(writer.stats().append_accepted == 0 && backend.appends == 0 && backend.opens == 0);
    assert(backend.closes == 1 && backend.verifies == 3 && !backend.abandoned);
    assert(abort_action(true,true,false,false,false) == AbortAction::None); // never steal a running capture
    assert(abort_action(false,false,true,false,false) == AbortAction::None);
    FakeBackend failed; failed.verify_ok = false;
    RecoveryWriter broken(failed,256,UINT32_MAX);
    broken.step(0); broken.request_finish(); broken.step(1); broken.step(2);
    assert(broken.stats().verify_failures == 1 && !broken.finished());
    assert(abort_action(false,true,broken.active(),broken.verification_active(),broken.finished()) == AbortAction::StopUnverified);
    assert(broken.stats().verified_files == 0 && failed.abandoned == 1);
    // No retry is performed after the startup owner selects StopUnverified.
    const auto attempts = broken.stats().recovery_attempts;
    assert(attempts == 1);
    FakeBackend missing; missing.recover_ok = false;
    RecoveryWriter unavailable(missing,256,UINT32_MAX); unavailable.step(0);
    assert(unavailable.stats().recovery_failures == 1);
    assert(abort_action(false,true,unavailable.active(),unavailable.verification_active(),unavailable.finished()) == AbortAction::StopUnverified);
    assert(!unavailable.stats().verified_files && !unavailable.stats().append_accepted);
}
}

int main() {
    probe_cases(); schedules(); aborted_empty_file();
    std::puts("HOST_STARTUP_POLICY_TEST_PASS (TEST_ONLY task permutations/probe callbacks/timeout/empty-file cleanup; HARDWARE_NOT_RUN)");
}
