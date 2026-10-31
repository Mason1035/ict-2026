#pragma once
#include "node/acquisition.hpp"
#include <array>
#include <cstdio>
#include <optional>

namespace node::storage {
enum class VerifyResult { Pending, Passed, Failed };
// One immutable closed-file descriptor. It does not retain sensor records.
struct ClosedSegment {
    char path[128]{};
    std::size_t bytes = 0;
    unsigned rows = 0;
    std::uint32_t crc32 = 0;
};
// Counts complete diagnostic data rows while preserving a line prefix across
// read chunks. Comments/metadata and the column header are not sensor records.
class DataRowCounter {
public:
    void reset() { prefix_bytes_ = rows_ = 0; }
    void consume(const char*, std::size_t);
    unsigned rows() const { return rows_; }
private:
    char prefix_[5]{};
    unsigned prefix_bytes_ = 0, rows_ = 0;
};
// StorageTask owns both writer and reader. Each step reads at most 4 KiB;
// there is no second SD task, unbounded buffer, or assumption of SD latency.
class IncrementalVerifier {
public:
    static constexpr std::size_t read_quantum = 4096; // eight 512-byte SD sectors per bounded read
    ~IncrementalVerifier() { cancel(); }
    bool begin(const ClosedSegment&);
    VerifyResult step();
    void cancel();
    bool active() const { return fd_ >= 0; }
    int last_error() const { return error_; }
    std::size_t bytes_read() const { return bytes_; }
    unsigned rows_read() const { return row_counter_.rows(); }
private:
    VerifyResult finish(bool valid);
    int fd_ = -1;
    ClosedSegment segment_{};
    DataRowCounter row_counter_;
    char buffer_[read_quantum]{};
    std::size_t bytes_ = 0;
    std::uint32_t crc_ = 0xffffffffU;
    int error_ = 0;
};
// StorageTask is the sole owner. Diagnostic CSV is NOT the frozen experiment CSV.
enum class LogPhase : unsigned { Format, Write, Crc, Flush, Sync, Count };
struct LogTiming {
    std::uint64_t calls = 0, failures = 0, total_us = 0, max_us = 0, bytes = 0;
};
class DiagnosticLog {
public:
    // One buffered submission is at most eight 512-byte sectors rather than
    // 32. This does not bound FAT allocation, card-busy time, or task preemption.
    static constexpr std::size_t write_buffer_bytes = 4096;
    using Clock = std::uint64_t (*)(); // monotonic microseconds, no I/O/allocation
    explicit DiagnosticLog(Clock clock = nullptr) : clock_(clock) {}
    ~DiagnosticLog();
    bool open_new(const char* directory, const char* metadata);
    bool append(const sampling::AcquisitionRecord&);
    bool flush();
    bool close_and_verify();
    bool close_for_verification(ClosedSegment&); // flush+close only; not VERIFIED
    void abandon(); // closes best-effort; partial file retained, never deleted
    const char* path() const { return path_; }
    unsigned rows() const { return rows_; }
    std::uint32_t crc32() const { return crc_ ^ 0xffffffffU; }
    std::size_t bytes() const { return bytes_; }
    int last_error() const { return error_; }
    bool last_write_uncertain() const { return write_uncertain_; }
    // Lifetime-cumulative, owner-only snapshot. All durations are wall time,
    // including preemption/waits; they are NOT CPU or card-internal timings.
    // Bytes are accepted fwrite bytes (Write) or CRC input bytes (Crc).
    const auto& timings() const { return timings_; }
    bool timing_enabled() const { return clock_ != nullptr; }
    static bool verify_file(const char*, std::size_t expected_bytes, std::uint32_t expected_crc,
        std::optional<unsigned> expected_rows = std::nullopt);
private:
    std::uint64_t start_timing() const { return clock_ ? clock_() : 0; }
    void end_timing(LogPhase, bool success, std::uint64_t started, std::size_t bytes = 0);
    bool write_bytes(const char*, std::size_t);
    bool locate_next_file(const char* directory);
    std::FILE* file_ = nullptr;
    char path_[128]{}, directory_[128]{}, buffer_[write_buffer_bytes]{};
    unsigned next_file_ = 1, rows_ = 0;
    std::size_t bytes_ = 0;
    std::uint32_t crc_ = 0xffffffffU;
    int error_ = 0;
    bool poisoned_ = false, write_uncertain_ = false;
    Clock clock_;
    std::array<LogTiming, static_cast<unsigned>(LogPhase::Count)> timings_{};
};
}
