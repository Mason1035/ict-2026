#include "node/storage_recovery.hpp"
#include <cassert>
#include <deque>
#include <vector>
#include <limits>

namespace {
using node::sampling::AcquisitionRecord;
using node::storage::Operation;
struct FakeStorage final : node::storage::Backend {
    bool recover_ok = true, append_ok = true, flush_ok = true, verify_ok = true, open_ok = true;
    bool uncertain = true;
    bool deferred = false, begin_ok = true;
    unsigned verify_quanta = 4, quanta_left = 0, begin_calls = 0, quantum_calls = 0, abort_calls = 0;
    std::uint64_t completion_delay_ms = 0;
    unsigned recover_calls = 0, append_calls = 0, flush_calls = 0, verify_calls = 0, open_calls = 0, abandon_calls = 0;
    std::vector<std::uint64_t> attempted_indices;
    bool recover() override { ++recover_calls; return recover_ok; }
    bool append(const AcquisitionRecord& r) override {
        ++append_calls; attempted_indices.push_back(r.acquisition_index); return append_ok;
    }
    bool flush() override { ++flush_calls; return flush_ok; }
    bool close_and_verify() override { ++verify_calls; return verify_ok; }
    bool open_next() override { ++open_calls; return open_ok; }
    void abandon() override { ++abandon_calls; }
    bool deferred_verification() const override { return deferred; }
    bool begin_verify() override { ++begin_calls; quanta_left = verify_quanta; return begin_ok; }
    node::storage::VerifyResult verify_step() override {
        ++quantum_calls;
        if (!verify_ok) return node::storage::VerifyResult::Failed;
        if (quanta_left) { --quanta_left; return node::storage::VerifyResult::Pending; }
        return node::storage::VerifyResult::Passed;
    }
    void abort_verification() override { ++abort_calls; }
    bool last_write_uncertain() const override { return uncertain; }
    std::uint64_t completed_at_ms(std::uint64_t supplied_now) const override {
        return supplied_now + completion_delay_ms;
    }
};
AcquisitionRecord record(std::uint64_t id) {
    AcquisitionRecord result;
    result.acquisition_index = id;
    result.kind = node::sampling::RecordKind::Soil;
    result.soil.validity = node::sampling::Validity::Valid;
    result.soil.raw = 0; // real zero must survive an identical-record retry
    return result;
}
void mount_failure_backoff() {
    FakeStorage backend;
    backend.recover_ok = false;
    node::storage::RecoveryWriter writer(backend);
    writer.step(0);
    assert(!writer.active() && !writer.can_take_record());
    assert(!writer.take_record(record(1)));
    assert(writer.stats().recovery_failures == 1 && writer.next_retry_ms() == 250);
    writer.step(249); assert(backend.recover_calls == 1);
    writer.step(250); assert(writer.next_retry_ms() == 750);
    writer.step(750); assert(writer.next_retry_ms() == 1750);
    writer.step(1750); assert(writer.next_retry_ms() == 3750);
    writer.step(3750); assert(writer.next_retry_ms() == 8750);
    writer.step(8750); assert(writer.next_retry_ms() == 13750);
    backend.recover_ok = true;
    writer.step(13750);
    assert(writer.active() && writer.stats().recoveries == 1 && writer.stats().errors == 6);
}
void append_failure(bool uncertain) {
    FakeStorage backend;
    node::storage::RecoveryWriter writer(backend);
    writer.step(0); assert(writer.take_record(record(42)));
    backend.append_ok = false; backend.uncertain = uncertain;
    writer.step(1);
    assert(writer.last_operation() == Operation::AppendFailed);
    assert(!writer.active() && writer.has_pending() && !writer.can_take_record());
    assert(writer.stats().write_failures == 1 && writer.stats().append_accepted == 0);
    assert(writer.stats().uncertain_records == (uncertain ? 1U : 0U));
    assert(!writer.take_record(record(43)));
    backend.append_ok = true;
    writer.step(250); assert(backend.recover_calls == 1);
    writer.step(251); assert(writer.active() && writer.has_pending());
    writer.step(252);
    assert((backend.attempted_indices == std::vector<std::uint64_t>{42, 42}));
    assert(writer.stats().retried_records == 1);
    assert(writer.stats().replayed_records == (uncertain ? 1U : 0U));
    assert(writer.stats().append_accepted == 1 && writer.can_take_record());
}
void slow_failure_backoff_starts_after_io_completion() {
    FakeStorage backend;
    backend.recover_ok = false;
    backend.completion_delay_ms = 1000; // slow failed mount plus best-effort cleanup
    node::storage::RecoveryWriter writer(backend);
    writer.step(0);
    assert(writer.next_retry_ms() == 1250);
    writer.step(1000); writer.step(1249);
    assert(backend.recover_calls == 1);
    writer.step(1250);
    assert(backend.recover_calls == 2 && writer.next_retry_ms() == 2750);

    FakeStorage flush_backend;
    node::storage::RecoveryWriter flush_writer(flush_backend, 1, 1000);
    flush_writer.step(0); assert(flush_writer.take_record(record(6))); flush_writer.step(1);
    flush_backend.flush_ok = false; flush_backend.completion_delay_ms = 1000;
    flush_writer.step(2);
    assert(flush_writer.last_operation() == Operation::FlushFailed);
    assert(flush_writer.next_retry_ms() == 1252);
    flush_writer.step(1002); flush_writer.step(1251);
    assert(flush_backend.recover_calls == 1);
    flush_backend.flush_ok = true;
    flush_writer.step(1252);
    assert(flush_backend.recover_calls == 2 && flush_writer.has_pending());
}
void flush_failure_retains_current_not_whole_old_tail() {
    FakeStorage backend;
    node::storage::RecoveryWriter writer(backend, 2, 1000);
    writer.step(0);
    assert(writer.take_record(record(100))); writer.step(1);
    assert(writer.take_record(record(101))); writer.step(2);
    assert(writer.has_pending());
    backend.flush_ok = false; writer.step(3);
    assert(writer.last_operation() == Operation::FlushFailed);
    assert(writer.stats().append_accepted == 2 && writer.stats().flush_accepted == 0);
    assert(writer.stats().uncertain_records == 2 && writer.has_pending());
    backend.flush_ok = true;
    writer.step(253); writer.step(254);
    assert((backend.attempted_indices == std::vector<std::uint64_t>{100, 101, 101}));
    assert(writer.stats().replayed_records == 1 && writer.stats().verified_files == 0);
    // The preceding accepted-but-unflushed row is at risk; no assertion calls it
    // definitely lost or claims this single pending slot can replay that row.
}
void retry_preserves_prior_uncertainty() {
    FakeStorage backend;
    node::storage::RecoveryWriter writer(backend);
    writer.step(0); assert(writer.take_record(record(55)));
    backend.append_ok = false; backend.uncertain = true; writer.step(1);
    writer.step(251);
    backend.uncertain = false; writer.step(252); // this attempt clearly did not write
    writer.step(502);
    backend.append_ok = true; writer.step(503);
    assert(writer.stats().retried_records == 2 && writer.stats().replayed_records == 2);
    assert(writer.stats().uncertain_records == 1); // retain earlier file ambiguity
    assert((backend.attempted_indices == std::vector<std::uint64_t>{55, 55, 55}));
}
void verify_failure_then_successful_reopen_is_not_overwritten() {
    FakeStorage backend;
    node::storage::RecoveryWriter writer(backend, 64, 1);
    writer.step(0); assert(writer.take_record(record(7))); writer.step(1);
    backend.verify_ok = false; writer.step(2);
    assert(writer.last_operation() == Operation::VerifyFailed);
    assert(!writer.active() && writer.stats().verify_failures == 1);
    assert(writer.stats().verified_files == 0 && backend.open_calls == 0);
    backend.verify_ok = true;
    writer.step(252); // recovery may open a NEW file, but cannot erase the failure
    assert(writer.active() && writer.stats().verify_failures == 1);
    writer.step(253); writer.step(254); writer.step(255);
    assert(writer.stats().verified_files == 1 && writer.stats().verified_rows == 1);
    assert(writer.stats().verify_failures == 1 && backend.open_calls == 1);
    assert((backend.attempted_indices == std::vector<std::uint64_t>{7, 7}));
}
void open_failure_after_verified_does_not_replay_verified_row() {
    FakeStorage backend;
    node::storage::RecoveryWriter writer(backend, 64, 1);
    writer.step(0); assert(writer.take_record(record(99))); writer.step(1); writer.step(2);
    assert(writer.stats().verified_files == 1 && !writer.has_pending());
    assert(!writer.can_take_record()); // old file closed, next file not yet open
    backend.open_ok = false; writer.step(3);
    assert(writer.last_operation() == Operation::OpenFailed && !writer.has_pending());
    assert(writer.stats().open_failures == 1 && writer.stats().verify_failures == 0);
    writer.step(253);
    assert(writer.can_take_record() && backend.append_calls == 1);
    assert(writer.stats().replayed_records == 0 && writer.stats().uncertain_records == 0);
}
void temporary_unavailable_retains_queue_and_pending_order() {
    FakeStorage backend;
    node::storage::RecoveryWriter writer(backend);
    std::deque<AcquisitionRecord> queue{record(10), record(11), record(12)};
    auto feed = [&] {
        if (writer.can_take_record() && !queue.empty()) {
            assert(writer.take_record(queue.front())); queue.pop_front();
        }
    };
    writer.step(0); feed(); assert(queue.size() == 2);
    backend.append_ok = false; writer.step(1);
    backend.recover_ok = false;
    for (unsigned ms = 2; ms < 1000; ++ms) { feed(); writer.step(ms); }
    assert(queue.size() == 2 && backend.append_calls == 1);
    assert(writer.has_pending() && writer.stats().recovery_failures == 2);
    backend.recover_ok = backend.append_ok = true;
    writer.step(writer.next_retry_ms());
    assert(writer.has_pending() && !writer.can_take_record());
    writer.step(2000); feed(); writer.step(2001); feed(); writer.step(2002);
    assert((backend.attempted_indices == std::vector<std::uint64_t>{10, 10, 11, 12}));
    assert(queue.empty() && writer.stats().append_accepted == 3);
}
void finish_pending_empty_and_idempotent() {
    FakeStorage backend;
    backend.deferred = true; backend.verify_quanta = 2;
    node::storage::RecoveryWriter writer(backend, 256, std::numeric_limits<unsigned>::max());
    writer.step(0); assert(writer.take_record(record(42)));
    writer.request_finish(); writer.request_finish();
    assert(writer.finish_requested() && !writer.finished() && !writer.can_take_record());
    assert(!writer.take_record(record(43)));
    writer.step(1); // finish never discards the one already-owned pending record
    assert(backend.append_calls == 1 && !writer.has_pending());
    writer.step(2); assert(writer.verification_active() && !writer.finished());
    writer.step(3); writer.step(4); assert(!writer.finished());
    writer.step(5);
    assert(writer.finished() && !writer.active() && !writer.recovering());
    assert(writer.stats().verified_rows == 1 && backend.open_calls == 0);
    assert(writer.stats().uncertain_records == 0 && backend.recover_calls == 1);
    const auto steps = writer.stats().verification_steps;
    writer.request_finish(); writer.step(99999);
    assert(writer.finished() && !writer.take_record(record(44)));
    assert(writer.stats().verification_steps == steps && backend.recover_calls == 1 && backend.open_calls == 0);

    FakeStorage empty;
    empty.deferred = true; empty.verify_quanta = 0;
    node::storage::RecoveryWriter empty_writer(empty);
    empty_writer.request_finish(); // even a header-only file has to close/read back
    empty_writer.step(0); empty_writer.step(1);
    assert(empty_writer.verification_active() && empty_writer.stats().verified_files == 0);
    empty_writer.step(2);
    assert(empty_writer.finished() && empty_writer.stats().verified_files == 1);
    assert(empty_writer.stats().verified_rows == 0 && empty.append_calls == 0 && empty.open_calls == 0);

    FakeStorage synchronous;
    node::storage::RecoveryWriter sync_writer(synchronous);
    sync_writer.step(0); assert(sync_writer.take_record(record(1))); sync_writer.request_finish();
    sync_writer.step(1); sync_writer.step(2);
    assert(sync_writer.finished() && synchronous.verify_calls == 1 && synchronous.open_calls == 0);
}
void finish_after_rollover_does_not_open_a_successor() {
    for (const bool deferred : {false, true}) {
        FakeStorage backend;
        backend.deferred = deferred; backend.verify_quanta = 1;
        node::storage::RecoveryWriter writer(backend, 64, 1);
        writer.step(0); assert(writer.take_record(record(7))); writer.step(1); writer.step(2);
        writer.request_finish();
        for (unsigned now = 3; !writer.finished() && now < 10; ++now) writer.step(now);
        assert(writer.finished() && backend.open_calls == 0 && backend.recover_calls == 1);
        assert(writer.stats().verified_rows == 1 && writer.stats().verified_files == 1);
    }
}
void finish_failures_keep_evidence_and_retry_identity() {
    FakeStorage pending;
    pending.deferred = true; pending.verify_quanta = 0;
    node::storage::RecoveryWriter writer(pending);
    writer.step(0); assert(writer.take_record(record(9))); writer.request_finish();
    pending.append_ok = false; writer.step(1);
    assert(writer.has_pending() && writer.recovering() && !writer.finished());
    pending.append_ok = true; writer.step(251); writer.step(252); writer.step(253); writer.step(254);
    assert(writer.finished() && (pending.attempted_indices == std::vector<std::uint64_t>{9, 9}));
    assert(writer.stats().errors == 1 && writer.stats().write_failures == 1);
    assert(writer.stats().uncertain_records == 1 && writer.stats().replayed_records == 1);
    assert(writer.stats().verified_rows == 1 && pending.open_calls == 0);

    FakeStorage closing;
    closing.deferred = true; closing.verify_quanta = 0; closing.begin_ok = false;
    node::storage::RecoveryWriter close_writer(closing);
    close_writer.step(0); assert(close_writer.take_record(record(10))); close_writer.step(1);
    close_writer.request_finish(); close_writer.step(2);
    assert(close_writer.recovering() && !close_writer.finished() && !close_writer.has_pending());
    assert(close_writer.stats().verify_failures == 1 && close_writer.stats().uncertain_records == 1);
    close_writer.step(251); assert(closing.recover_calls == 1);
    closing.begin_ok = true; close_writer.step(252); close_writer.step(253); close_writer.step(254);
    assert(close_writer.finished() && closing.recover_calls == 2 && closing.open_calls == 0);
    // A successful empty recovered file cannot certify the earlier uncertain row.
    assert(close_writer.stats().verified_rows == 0 && close_writer.stats().uncertain_records == 1);
    assert(close_writer.stats().errors == 1 && close_writer.stats().replayed_records == 0);

    FakeStorage bad_read;
    bad_read.deferred = true; bad_read.verify_quanta = 0;
    node::storage::RecoveryWriter verify_writer(bad_read);
    verify_writer.step(0); assert(verify_writer.take_record(record(11))); verify_writer.step(1);
    verify_writer.request_finish(); verify_writer.step(2);
    bad_read.verify_ok = false; verify_writer.step(3);
    assert(!verify_writer.finished() && verify_writer.stats().verified_files == 0);
    assert(verify_writer.stats().verify_failures == 1 && verify_writer.stats().uncertain_records == 1);
    bad_read.verify_ok = true; verify_writer.step(253); verify_writer.step(254); verify_writer.step(255);
    assert(verify_writer.finished() && verify_writer.stats().uncertain_records == 1);
    assert(verify_writer.stats().verified_rows == 0 && verify_writer.stats().errors == 1);
}
struct TailStorage final : node::storage::Backend {
    std::uint64_t us = 0;
    unsigned append_calls = 0, remaining = 0;
    bool recover() override { us += 1000; return true; }
    bool append(const AcquisitionRecord&) override {
        us += ++append_calls == 1000 ? 1632120 : 1000; return true;
    }
    bool flush() override { us += 100; return true; }
    bool close_and_verify() override { assert(false); return false; }
    bool open_next() override { assert(false); return false; }
    void abandon() override {}
    bool deferred_verification() const override { return true; }
    bool begin_verify() override { us += 200; remaining = 10; return true; }
    node::storage::VerifyResult verify_step() override {
        us += 4000;
        return --remaining ? node::storage::VerifyResult::Pending : node::storage::VerifyResult::Passed;
    }
};
void finite_capture_preserves_explicit_long_tail_losses() {
    // HOST MODEL ONLY: a measured-shape 1.632-second tail is injected into an
    // otherwise arbitrary fast backend. This is NOT real SD throughput evidence.
    TailStorage backend;
    node::storage::RecoveryWriter writer(backend, 256, std::numeric_limits<unsigned>::max());
    std::deque<AcquisitionRecord> queue;
    constexpr unsigned target = 206 * 20;
    unsigned produced = 0, drops = 0, dequeued = 0, budget = 0, guard = 0;
    while (!writer.finished() && ++guard < 1000000) {
        while (produced < target && produced * 1000000ULL / 206 <= backend.us) {
            if (queue.size() < 128) queue.push_back(record(produced)); else ++drops;
            ++produced;
        }
        if (writer.can_take_record() && !queue.empty()) {
            assert(writer.take_record(queue.front())); queue.pop_front(); ++dequeued;
        }
        if (produced == target && queue.empty() && !writer.has_pending()) writer.request_finish();
        const auto before = backend.us;
        writer.step(backend.us / 1000);
        if (writer.last_operation() == Operation::AppendAccepted && ++budget == 32) {
            backend.us += 10000; budget = 0;
        }
        if (backend.us == before) backend.us += 100;
        assert(queue.size() <= 128);
    }
    assert(writer.finished() && drops >= 200 && produced == target);
    assert(drops + dequeued == produced && writer.stats().append_accepted == dequeued);
    assert(writer.stats().verified_rows == dequeued && writer.stats().verified_files == 1);
    assert(writer.stats().errors == 0); // no API failure does NOT imply no queue loss
}
void production_batch_policy_retains_sync_and_readback() {
    FakeStorage backend;
    backend.deferred = true; backend.verify_quanta = 0;
    node::storage::RecoveryWriter writer(backend, 256, 4000);
    writer.step(0);
    for (unsigned i = 0; i != 4000; ++i) {
        assert(writer.take_record(record(i)));
        while (writer.has_pending()) writer.step(i + 1);
    }
    assert(backend.append_calls == 4000 && backend.flush_calls == 15);
    assert(writer.stats().append_accepted == 4000 && writer.stats().flush_accepted == 4000);
    // A closed/synced segment is still NOT VERIFIED until complete readback.
    assert(writer.stats().verified_files == 0 && writer.verification_active());
    assert(writer.stats().deferred_files == 1 && backend.begin_calls == 1);
    writer.step(4001); // open the next writer
    writer.step(4002); // complete the old segment's explicitly modeled readback
    assert(writer.stats().verified_files == 1 && writer.stats().verified_rows == 4000);
    assert(writer.can_take_record() && writer.stats().uncertain_records == 0);
}
void deferred_verification_interleaves_and_bounds_backlog() {
    FakeStorage backend;
    backend.deferred = true; backend.verify_quanta = 4;
    node::storage::RecoveryWriter writer(backend, 64, 2);
    writer.step(0);
    assert(writer.take_record(record(1))); writer.step(1);
    assert(writer.take_record(record(2))); writer.step(2); writer.step(3);
    assert(writer.last_operation() == Operation::VerifyStarted);
    assert(!writer.active() && !writer.recovering() && writer.verification_active());
    assert(writer.stats().verified_files == 0 && backend.begin_calls == 1);
    writer.step(4); // opens the next writer; old readback has not run yet
    assert(writer.can_take_record() && writer.verification_active());
    assert(writer.take_record(record(3)));
    writer.step(5); assert(writer.last_operation() == Operation::VerifyProgress);
    writer.step(6); assert(backend.attempted_indices.back() == 3);
    assert(writer.take_record(record(4)));
    writer.step(7); writer.step(8); // chunk, then new record append
    assert(backend.attempted_indices.back() == 4 && writer.has_pending());
    // The new segment is full while its predecessor is pending: preserve both,
    // expose backpressure, and never overwrite the single verification slot.
    writer.step(9); writer.step(10);
    assert(backend.begin_calls == 1 && writer.stats().verification_backpressure_steps == 2);
    writer.step(11); // final EOF/check result for the old descriptor
    assert(writer.last_operation() == Operation::FileVerified && writer.stats().verified_rows == 2);
    writer.step(12); // now and only now begin readback for the second descriptor
    assert(backend.begin_calls == 2 && writer.stats().deferred_files == 2);
    assert(writer.stats().verification_steps == 5 && writer.stats().verified_files == 1);
    assert(!writer.recovering());
}
void deferred_failures_preserve_pending_and_prior_evidence() {
    FakeStorage backend;
    backend.deferred = true;
    node::storage::RecoveryWriter writer(backend, 64, 1);
    writer.step(0); assert(writer.take_record(record(30))); writer.step(1); writer.step(2); writer.step(3);
    assert(writer.take_record(record(31))); // not appended; old verification will fail first
    backend.verify_ok = false; writer.step(4);
    assert(writer.recovering() && writer.has_pending() && !writer.verification_active());
    assert(writer.stats().verify_failures == 1 && writer.stats().verified_files == 0);
    assert(writer.stats().uncertain_records == 1); // closed old segment, not unwritten current pending
    backend.verify_ok = true; writer.step(254); writer.step(255);
    assert((backend.attempted_indices == std::vector<std::uint64_t>{30, 31}));
    assert(writer.stats().retried_records == 1 && writer.stats().replayed_records == 0);
    assert(writer.stats().verify_failures == 1); // later recovery cannot erase it

    FakeStorage failed_begin;
    failed_begin.deferred = true; failed_begin.begin_ok = false;
    node::storage::RecoveryWriter begin_writer(failed_begin, 64, 1);
    begin_writer.step(0); assert(begin_writer.take_record(record(50))); begin_writer.step(1); begin_writer.step(2);
    assert(begin_writer.recovering() && begin_writer.has_pending());
    assert(begin_writer.stats().verify_failures == 1 && begin_writer.stats().uncertain_records == 1);
    failed_begin.begin_ok = true; begin_writer.step(252); begin_writer.step(253);
    assert((failed_begin.attempted_indices == std::vector<std::uint64_t>{50, 50}));
    assert(begin_writer.stats().replayed_records == 1);

    FakeStorage failed_writer;
    failed_writer.deferred = true;
    node::storage::RecoveryWriter abandoned(failed_writer, 64, 1);
    abandoned.step(0); assert(abandoned.take_record(record(60))); abandoned.step(1); abandoned.step(2); abandoned.step(3);
    assert(abandoned.take_record(record(61))); abandoned.step(4); // one pending verify chunk
    failed_writer.append_ok = false; abandoned.step(5);
    assert(abandoned.stats().verification_abandoned == 1 && failed_writer.abort_calls == 1);
    assert(!abandoned.verification_active() && abandoned.has_pending());
    assert(abandoned.stats().uncertain_records == 2); // old closed file plus uncertain current write

    FakeStorage failed_open;
    failed_open.deferred = true; failed_open.open_ok = false;
    node::storage::RecoveryWriter no_writer(failed_open, 64, 1);
    no_writer.step(0); assert(no_writer.take_record(record(70))); no_writer.step(1); no_writer.step(2);
    assert(no_writer.verification_active() && !no_writer.has_pending());
    no_writer.step(3);
    assert(no_writer.recovering() && no_writer.stats().open_failures == 1);
    assert(no_writer.stats().verification_abandoned == 1 && no_writer.stats().uncertain_records == 1);
    assert(no_writer.stats().verified_files == 0 && no_writer.stats().replayed_records == 0);
}
struct LatencyStorage final : node::storage::Backend {
    explicit LatencyStorage(bool incremental) : incremental_(incremental) {}
    std::uint64_t us = 0;
    unsigned remaining = 0;
    bool recover() override { us += 1000; return true; }
    bool append(const AcquisitionRecord&) override { us += 1000; return true; }
    bool flush() override { us += 100; return true; }
    bool close_and_verify() override { us += 640200; return true; }
    bool open_next() override { us += 200; return true; }
    void abandon() override {}
    bool deferred_verification() const override { return incremental_; }
    bool begin_verify() override { us += 200; remaining = 160; return true; }
    node::storage::VerifyResult verify_step() override {
        us += 4000;
        return --remaining ? node::storage::VerifyResult::Pending : node::storage::VerifyResult::Passed;
    }
private: bool incremental_;
};
struct ThroughputResult { unsigned drop; std::uint64_t max_step; std::uint64_t consumed; };
ThroughputResult simulate_latencies(bool incremental) {
    // TEST_ONLY SYNTHETIC latency model: this is a scheduling regression test,
    // not measured PC/SD performance or proof that real hardware reaches 206/s.
    LatencyStorage backend(incremental);
    node::storage::RecoveryWriter writer(backend);
    std::deque<AcquisitionRecord> queue;
    std::uint64_t produced = 0, dequeued = 0, max_step = 0;
    unsigned drops = 0, work = 0;
    while (backend.us < 20000000) {
        while (produced * 1000000 / 206 <= backend.us) {
            if (queue.size() < 128) queue.push_back(record(produced)); else ++drops;
            ++produced;
        }
        if (writer.can_take_record() && !queue.empty()) {
            assert(writer.take_record(queue.front())); queue.pop_front(); ++dequeued;
        }
        const auto before = backend.us;
        const auto appended = writer.stats().append_accepted;
        writer.step(backend.us / 1000);
        if (backend.us - before > max_step) max_step = backend.us - before;
        if (writer.stats().append_accepted != appended && ++work == 8) { work = 0; backend.us += 10000; }
        if (backend.us == before) backend.us += 100; // no-work/EOF/open bookkeeping yields modeled time
    }
    return {drops, max_step, dequeued};
}
void bounded_quantum_reduces_synthetic_rollover_stall() {
    const auto blocking = simulate_latencies(false);
    const auto incremental = simulate_latencies(true);
    assert(blocking.drop > 0 && blocking.max_step >= 640000);
    assert(incremental.drop == 0 && incremental.max_step <= 4000);
    assert(incremental.consumed > blocking.consumed);
}
}
int main() {
    mount_failure_backoff();
    slow_failure_backoff_starts_after_io_completion();
    append_failure(false);
    append_failure(true);
    retry_preserves_prior_uncertainty();
    flush_failure_retains_current_not_whole_old_tail();
    verify_failure_then_successful_reopen_is_not_overwritten();
    open_failure_after_verified_does_not_replay_verified_row();
    temporary_unavailable_retains_queue_and_pending_order();
    finish_pending_empty_and_idempotent();
    finish_after_rollover_does_not_open_a_successor();
    finish_failures_keep_evidence_and_retry_identity();
    finite_capture_preserves_explicit_long_tail_losses();
    production_batch_policy_retains_sync_and_readback();
    deferred_verification_interleaves_and_bounds_backlog();
    deferred_failures_preserve_pending_and_prior_evidence();
    bounded_quantum_reduces_synthetic_rollover_stall();
}
