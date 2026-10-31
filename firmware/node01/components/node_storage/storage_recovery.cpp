#include "node/storage_recovery.hpp"
#include <algorithm>

namespace node::storage {
bool RecoveryWriter::take_record(const sampling::AcquisitionRecord& record) {
    if (!can_take_record()) return false;
    pending_ = record;
    phase_ = Phase::Append;
    return true;
}
void RecoveryWriter::release_pending() {
    pending_.reset(); pending_retry_ = pending_uncertain_ = false; phase_ = Phase::Ready;
}
void RecoveryWriter::failed(std::uint64_t now_ms) {
    constexpr unsigned delays[] = {250, 500, 1000, 2000, 5000};
    active_ = false; final_verification_ = false;
    ++stats_.errors;
    if (verification_active_) {
        // A concurrent writer failure can prevent completing the old readback.
        // Keep that file and count its exposure; never silently mark it verified.
        stats_.uncertain_records += verification_rows_;
        ++stats_.verification_abandoned;
        backend_.abort_verification();
        verification_active_ = verification_due_ = false;
        verification_rows_ = 0;
    }
    // fclose is best-effort and may itself complete a prior uncertain write.
    // Replayed records keep their original acquisition_index for duplicate detection.
    backend_.abandon();
    if (pending_) pending_retry_ = true;
    next_retry_ms_ = backend_.completed_at_ms(now_ms) + delays[std::min(backoff_, 4U)];
    if (backoff_ < 4) ++backoff_;
}
void RecoveryWriter::verify_one(std::uint64_t now_ms) {
    ++stats_.verification_steps;
    if (phase_ == Phase::Verify) ++stats_.verification_backpressure_steps;
    const auto outcome = backend_.verify_step();
    verification_due_ = false;
    if (outcome == VerifyResult::Pending) { operation_ = Operation::VerifyProgress; return; }
    const auto checked_rows = verification_rows_;
    verification_active_ = false; verification_rows_ = 0;
    if (outcome == VerifyResult::Passed) {
        ++stats_.verified_files; stats_.verified_rows += checked_rows;
        operation_ = Operation::FileVerified;
        if (final_verification_) {
            final_verification_ = false; finished_ = true; active_ = false;
        }
        return;
    }
    ++stats_.verify_failures;
    stats_.uncertain_records += checked_rows + rows_;
    // New current pending may be completely unwritten (Append), or already
    // accepted while waiting for flush/rollover. Retry only that actual pending.
    if (pending_ && phase_ != Phase::Append) pending_uncertain_ = true;
    backend_.abort_verification();
    operation_ = Operation::VerifyFailed; failed(now_ms);
}
void RecoveryWriter::step(std::uint64_t now_ms) {
    operation_ = Operation::None;
    if (finished_) return;
    if (!active_) {
        if (now_ms < next_retry_ms_) return;
        ++stats_.recovery_attempts;
        operation_ = Operation::RecoveryAttempt;
        if (!backend_.recover()) {
            ++stats_.recovery_failures;
            failed(now_ms);
            return;
        }
        ++stats_.recoveries;
        active_ = true; backoff_ = rows_ = unflushed_rows_ = 0;
        phase_ = pending_ ? Phase::Append : Phase::Ready;
        operation_ = Operation::Recovered;
        return;
    }
    if (phase_ == Phase::Open) {
        if (finish_requested_) {
            // Rollover already closed the current writer. Finish its remaining
            // readback without creating a spurious empty successor file.
            if (verification_active_) { final_verification_ = true; verify_one(now_ms); }
            else { finished_ = true; active_ = false; }
            return;
        }
        if (!backend_.open_next()) {
            ++stats_.open_failures; operation_ = Operation::OpenFailed; failed(now_ms);
        } else { phase_ = Phase::Ready; operation_ = Operation::Opened; }
        return;
    }
    if (verification_active_ && (verification_due_ || phase_ == Phase::Verify || !pending_)) {
        verify_one(now_ms);
        return;
    }
    if (finish_requested_ && !pending_ && phase_ == Phase::Ready) phase_ = Phase::Verify;
    if (!pending_ && phase_ != Phase::Verify) return;
    if (phase_ == Phase::Append) {
        if (pending_retry_) {
            ++stats_.retried_records;
            if (pending_uncertain_) ++stats_.replayed_records;
            pending_retry_ = false;
        }
        if (!backend_.append(*pending_)) {
            ++stats_.write_failures;
            const bool current_write_uncertain = backend_.last_write_uncertain();
            pending_uncertain_ = pending_uncertain_ || current_write_uncertain;
            stats_.uncertain_records += unflushed_rows_ + (current_write_uncertain ? 1U : 0U);
            operation_ = Operation::AppendFailed; failed(now_ms); return;
        }
        ++stats_.append_accepted; ++rows_; ++unflushed_rows_;
        if (verification_active_) verification_due_ = true;
        operation_ = Operation::AppendAccepted;
        if (rows_ % flush_rows_ == 0) phase_ = Phase::Flush;
        else if (rows_ >= rollover_rows_) phase_ = Phase::Verify;
        else release_pending();
        return;
    }
    if (phase_ == Phase::Flush) {
        if (!backend_.flush()) {
            ++stats_.flush_failures; stats_.uncertain_records += unflushed_rows_;
            pending_uncertain_ = true;
            operation_ = Operation::FlushFailed; failed(now_ms); return;
        }
        stats_.flush_accepted += unflushed_rows_; unflushed_rows_ = 0;
        operation_ = Operation::FlushAccepted;
        if (rows_ >= rollover_rows_) phase_ = Phase::Verify; else release_pending();
        return;
    }
    if (phase_ == Phase::Verify) {
        if (backend_.deferred_verification()) {
            // A previous descriptor is always finished first (the branch above).
            // This bounds backlog to one closed file without discarding evidence.
            if (!backend_.begin_verify()) {
                ++stats_.verify_failures; stats_.uncertain_records += rows_;
                pending_uncertain_ = true;
                operation_ = Operation::VerifyFailed; failed(now_ms); return;
            }
            verification_rows_ = rows_;
            verification_active_ = verification_due_ = true;
            ++stats_.deferred_files;
            stats_.flush_accepted += unflushed_rows_; unflushed_rows_ = 0;
            // The closed file remains evidence, not VERIFIED. Subsequent old
            // readback failure cannot replay its whole contents from one slot.
            release_pending(); rows_ = 0;
            if (finish_requested_) final_verification_ = true;
            else phase_ = Phase::Open;
            operation_ = Operation::VerifyStarted;
            return;
        }
        const bool verified = backend_.close_and_verify();
        if (!verified) {
            ++stats_.verify_failures; stats_.uncertain_records += rows_;
            pending_uncertain_ = true;
            operation_ = Operation::VerifyFailed; failed(now_ms); return;
        }
        ++stats_.verified_files; stats_.verified_rows += rows_;
        stats_.flush_accepted += unflushed_rows_; unflushed_rows_ = 0;
        // A later open failure MUST NOT replay a record in a verified file.
        release_pending(); rows_ = 0;
        if (finish_requested_) { finished_ = true; active_ = false; }
        else phase_ = Phase::Open;
        operation_ = Operation::FileVerified;
    }
}
}
