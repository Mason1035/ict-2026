#pragma once
#include "node/acquisition.hpp"
#include "node/diagnostic_log.hpp"
#include <cstdint>
#include <optional>

namespace node::storage {
// StorageTask owns the backend and this state machine. No queue or hardware I/O
// is hidden here, so the exact recovery policy also runs in the host tests.
class Backend {
public:
    virtual ~Backend() = default;
    virtual bool recover() = 0; // abandon -> reset/unmount -> mount -> open NEW file
    virtual bool append(const sampling::AcquisitionRecord&) = 0;
    virtual bool flush() = 0;
    virtual bool close_and_verify() = 0;
    virtual bool open_next() = 0;
    virtual void abandon() = 0; // retain partial files; never delete/format
    virtual bool last_write_uncertain() const { return true; }
    virtual int last_error() const { return 0; }
    // Synchronous backends/tests remain compatible. The SD backend closes one
    // segment, opens the next writer, then interleaves bounded readback steps.
    virtual bool deferred_verification() const { return false; }
    virtual bool begin_verify() { return false; }
    virtual VerifyResult verify_step() { return VerifyResult::Failed; }
    virtual void abort_verification() {}
    // Firmware samples its monotonic clock AFTER a slow I/O/abandon operation.
    // Pure host backends can keep the caller-supplied deterministic time.
    virtual std::uint64_t completed_at_ms(std::uint64_t supplied_now) const { return supplied_now; }
};
enum class Operation {
    None, RecoveryAttempt, Recovered, AppendAccepted, AppendFailed,
    FlushAccepted, FlushFailed, FileVerified, VerifyFailed, Opened, OpenFailed,
    VerifyStarted, VerifyProgress
};
struct RecoveryStats {
    std::uint64_t append_accepted = 0, flush_accepted = 0, verified_files = 0, verified_rows = 0;
    std::uint64_t write_failures = 0, flush_failures = 0, verify_failures = 0, open_failures = 0;
    std::uint64_t recovery_failures = 0, recovery_attempts = 0, recoveries = 0, errors = 0;
    // Exposure observations, not a unique lost-record count. Failed flush/readback
    // can affect earlier accepted rows that this one-record pending slot cannot replay.
    std::uint64_t uncertain_records = 0, replayed_records = 0, retried_records = 0;
    std::uint64_t verification_steps = 0, verification_backpressure_steps = 0;
    std::uint64_t deferred_files = 0, verification_abandoned = 0;
};
class RecoveryWriter {
public:
    explicit RecoveryWriter(Backend& backend, unsigned flush_rows = 64, unsigned rollover_rows = 1000)
        : backend_(backend), flush_rows_(flush_rows ? flush_rows : 1),
          rollover_rows_(rollover_rows ? rollover_rows : 1) {}
    bool active() const { return active_ && phase_ != Phase::Open && !final_verification_ && !finished_; }
    bool recovering() const { return !active_ && !finished_; } // normal rollover Open is not recovery
    bool verification_active() const { return verification_active_; }
    bool can_take_record() const { return active() && !pending_ && !finish_requested_; }
    // Runtime requests this only after producers stop and its queue is drained.
    // An already-owned pending record still completes/retries before final close.
    void request_finish() { finish_requested_ = true; }
    bool finish_requested() const { return finish_requested_; }
    // Control-flow completion, NOT a loss-free data-quality or durability claim.
    // Historical error/uncertain/replay counters remain authoritative.
    bool finished() const { return finished_; }
    bool take_record(const sampling::AcquisitionRecord&);
    bool has_pending() const { return pending_.has_value(); }
    // One data/recovery attempt per call, plus best-effort abandon on failure.
    // This bounds state-machine work, not the SD/FATFS call's hardware latency.
    void step(std::uint64_t now_ms);
    const RecoveryStats& stats() const { return stats_; }
    Operation last_operation() const { return operation_; }
    std::uint64_t next_retry_ms() const { return next_retry_ms_; }
private:
    enum class Phase { Ready, Append, Flush, Verify, Open };
    void failed(std::uint64_t now_ms);
    void release_pending();
    void verify_one(std::uint64_t now_ms);
    Backend& backend_;
    const unsigned flush_rows_, rollover_rows_;
    RecoveryStats stats_{};
    std::optional<sampling::AcquisitionRecord> pending_;
    bool active_ = false, pending_retry_ = false, pending_uncertain_ = false;
    bool verification_active_ = false, verification_due_ = false;
    bool finish_requested_ = false, finished_ = false, final_verification_ = false;
    Phase phase_ = Phase::Ready;
    Operation operation_ = Operation::None;
    unsigned backoff_ = 0, rows_ = 0, unflushed_rows_ = 0;
    unsigned verification_rows_ = 0;
    std::uint64_t next_retry_ms_ = 0;
};
}
