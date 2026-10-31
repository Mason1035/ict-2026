#include "node/diagnostic_log.hpp"
#include "node/storage_recovery.hpp"
#include <cassert>
#include <cerrno>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <string>
#include <vector>
#include <unistd.h>

// TEST_ONLY GNU-ld wrappers around the real DiagnosticLog CRT/POSIX boundary.
// They do not emulate FATFS, an SD card, RTOS scheduling or hardware timings.
// No firmware source, buffering/sync policy or integrity check is replaced.
namespace injection {
enum class Fault { None, PartialWrite, Write, Flush, Sync, Close, Read };
Fault next = Fault::None;
unsigned fired = 0;
bool take(Fault fault) {
    if (next != fault) return false;
    next = Fault::None; ++fired; return true;
}
void arm(Fault fault) { assert(next == Fault::None); next = fault; fired = 0; }
void consumed() { assert(next == Fault::None && fired == 1); }
}

extern "C" {
std::size_t __real_fwrite(const void*, std::size_t, std::size_t, std::FILE*);
int __real_fflush(std::FILE*);
int __real_fclose(std::FILE*);
std::size_t __wrap_fwrite(const void* data, std::size_t size, std::size_t count, std::FILE* file) {
    if (file != stdout && file != stderr && injection::take(injection::Fault::PartialWrite)) {
        assert(size == 1 && count > 1); // DiagnosticLog's real byte-write API
        const auto accepted = __real_fwrite(data, size, count / 2, file);
        errno = ENOSPC; return accepted;
    }
    if (file != stdout && file != stderr && injection::take(injection::Fault::Write)) {
        errno = EIO; return 0;
    }
    return __real_fwrite(data, size, count, file);
}
int __wrap_fflush(std::FILE* file) {
    if (file != stdout && file != stderr && injection::take(injection::Fault::Flush)) {
        errno = EIO; return EOF;
    }
    return __real_fflush(file);
}
int __wrap_fclose(std::FILE* file) {
    // Actually release the stream first. The injected failure must not leak a
    // live CRT FILE just to make the production error branch observable.
    const int result = __real_fclose(file);
    if (injection::take(injection::Fault::Close)) { errno = EIO; return EOF; }
    return result;
}
#ifdef _WIN32
// MinGW/UCRT compiles _commit as an imported function-pointer reference. Wrapping
// only "_commit" would silently miss the real production call. Wrap that import
// symbol, preserving its genuine implementation through GNU __real_ relocation.
using Commit = int (*)(int);
extern Commit __real___imp__commit;
int wrapped_commit(int fd) {
    if (injection::take(injection::Fault::Sync)) { errno = EIO; return -1; }
    return __real___imp__commit(fd);
}
Commit __wrap___imp__commit = wrapped_commit;
int __real_read(int, void*, unsigned int);
int __wrap_read(int fd, void* data, unsigned int count) {
    if (injection::take(injection::Fault::Read)) { errno = EIO; return -1; }
    return __real_read(fd, data, count);
}
#else
int __real_fsync(int);
int __wrap_fsync(int fd) {
    if (injection::take(injection::Fault::Sync)) { errno = EIO; return -1; }
    return __real_fsync(fd);
}
ssize_t __real_read(int, void*, std::size_t);
ssize_t __wrap_read(int fd, void* data, std::size_t count) {
    if (injection::take(injection::Fault::Read)) { errno = EIO; return -1; }
    return __real_read(fd, data, count);
}
#endif
}

namespace {
using node::sampling::AcquisitionRecord;
using node::storage::ClosedSegment;
using node::storage::DiagnosticLog;
using node::storage::IncrementalVerifier;
using node::storage::RecoveryWriter;
using node::storage::VerifyResult;
constexpr const char* metadata = "# TEST_ONLY injected host failures; not real hardware or sensor data\n";
AcquisitionRecord record(std::uint64_t index = 42) {
    AcquisitionRecord value;
    value.kind = node::sampling::RecordKind::Soil;
    value.channel = 1; value.acquisition_index = index;
    value.attempted_uptime_us = index * 10000;
    value.soil.acquired_uptime_us = value.attempted_uptime_us;
    value.soil.validity = node::sampling::Validity::Valid;
    value.soil.raw = 1234;
    return value;
}
std::string directory(const std::string& root, const char* name) {
    const auto path = root + "/" + name;
    assert(std::filesystem::create_directory(path)); return path;
}
std::string bytes(const std::string& path) {
    std::ifstream input(path, std::ios::binary);
    assert(input.good());
    return std::string(std::istreambuf_iterator<char>(input), {});
}
void reopen_preserves_old_file(DiagnosticLog& log, const std::string& dir, const std::string& original) {
    log.abandon();
    const auto prior = bytes(original);
    assert(!prior.empty() && std::filesystem::exists(original));
    assert(log.open_new(dir.c_str(), metadata));
    assert(original != log.path() && log.last_error() == 0 && !log.last_write_uncertain());
    assert(log.append(record(43)) && log.close_and_verify()); // only the NEW file
    assert(bytes(original) == prior); // no overwrite/renumber/repair of failed evidence
}
void write_failures(const std::string& root) {
    for (const auto fault : {injection::Fault::PartialWrite, injection::Fault::Write}) {
        const auto dir = directory(root, fault == injection::Fault::PartialWrite ? "partial" : "write");
        DiagnosticLog log;
        assert(log.open_new(dir.c_str(), metadata));
        const std::string path = log.path();
        const auto prior_bytes = log.bytes();
        injection::arm(fault);
        assert(!log.append(record())); injection::consumed();
        assert(log.last_error() == (fault == injection::Fault::PartialWrite ? ENOSPC : EIO));
        assert(log.last_write_uncertain() && log.rows() == 0);
        assert(fault == injection::Fault::PartialWrite ? log.bytes() > prior_bytes : log.bytes() == prior_bytes);
        ClosedSegment result;
        assert(!log.close_for_verification(result));
        assert(!result.path[0] && result.rows == 0 && result.bytes == 0);
        reopen_preserves_old_file(log, dir, path);
    }
}
void flush_sync_close_failures(const std::string& root) {
    for (const auto fault : {injection::Fault::Flush, injection::Fault::Sync, injection::Fault::Close}) {
        const auto dir = directory(root, fault == injection::Fault::Flush ? "flush" : fault == injection::Fault::Sync ? "sync" : "close");
        DiagnosticLog log;
        assert(log.open_new(dir.c_str(), metadata) && log.append(record()));
        const std::string path = log.path();
        ClosedSegment result;
        injection::arm(fault);
        assert(!log.close_for_verification(result)); injection::consumed();
        assert(log.last_error() == EIO && !result.path[0] && result.bytes == 0 && result.rows == 0);
        if (fault != injection::Fault::Close) assert(log.last_write_uncertain());
        // A clean flush followed by fclose failure is still not VERIFIED even
        // when the "last write uncertain" flag itself is false. RecoveryWriter
        // below records the entire failed segment as uncertain in that case.
        reopen_preserves_old_file(log, dir, path);
    }
}
void read_failure(const std::string& root) {
    const auto dir = directory(root, "read");
    DiagnosticLog log;
    assert(log.open_new(dir.c_str(), metadata) && log.append(record()));
    ClosedSegment closed;
    assert(log.close_for_verification(closed));
    const auto original = bytes(closed.path);
    IncrementalVerifier reader;
    assert(reader.begin(closed));
    injection::arm(injection::Fault::Read);
    assert(reader.step() == VerifyResult::Failed); injection::consumed();
    assert(reader.last_error() == EIO && !reader.active() && reader.bytes_read() == 0);
    assert(bytes(closed.path) == original);
    // An explicit new verification may succeed after the injected failure ends;
    // the failed call above remains Failed, it is not retroactively relabelled.
    assert(reader.begin(closed));
    auto state = VerifyResult::Pending;
    while (state == VerifyResult::Pending) state = reader.step();
    assert(state == VerifyResult::Passed && reader.rows_read() == 1);
}

class RealLogBackend final : public node::storage::Backend {
public:
    explicit RealLogBackend(std::string dir) : dir_(std::move(dir)) {}
    bool recover() override { log.abandon(); return log.open_new(dir_.c_str(), metadata); }
    bool append(const AcquisitionRecord& value) override { return log.append(value); }
    bool flush() override { return log.flush(); }
    bool close_and_verify() override { return log.close_and_verify(); }
    bool open_next() override { return log.open_new(dir_.c_str(), metadata); }
    void abandon() override { verifier.cancel(); log.abandon(); }
    bool last_write_uncertain() const override { return log.last_write_uncertain(); }
    bool deferred_verification() const override { return true; }
    bool begin_verify() override { return log.close_for_verification(closed) && verifier.begin(closed); }
    VerifyResult verify_step() override { return verifier.step(); }
    void abort_verification() override { verifier.cancel(); }
    DiagnosticLog log;
    IncrementalVerifier verifier;
    ClosedSegment closed{};
private: std::string dir_;
};

void writer_never_counts_failed_file_as_verified(const std::string& root) {
    const std::vector<injection::Fault> faults{injection::Fault::PartialWrite, injection::Fault::Write,
        injection::Fault::Flush, injection::Fault::Sync, injection::Fault::Close, injection::Fault::Read};
    for (unsigned n = 0; n < faults.size(); ++n) {
        const auto fault = faults[n];
        const auto dir = directory(root, ("writer" + std::to_string(n)).c_str());
        RealLogBackend backend(dir);
        RecoveryWriter writer(backend, 1, UINT32_MAX);
        writer.step(0); assert(writer.active());
        const std::string old_path = backend.log.path();
        assert(writer.take_record(record())); writer.request_finish();
        if (fault == injection::Fault::PartialWrite || fault == injection::Fault::Write) injection::arm(fault);
        writer.step(1); // real append
        if (fault == injection::Fault::Flush || fault == injection::Fault::Sync) injection::arm(fault);
        if (!writer.stats().errors) writer.step(2); // real flush
        if (fault == injection::Fault::Close) injection::arm(fault);
        if (!writer.stats().errors) writer.step(3); // close + begin verifier
        if (fault == injection::Fault::Read) injection::arm(fault);
        if (!writer.stats().errors) writer.step(4); // real read
        injection::consumed();
        assert(writer.stats().errors == 1 && writer.stats().verified_rows == 0 && writer.stats().verified_files == 0);
        assert(!writer.finished() && !writer.active());
        assert(writer.stats().uncertain_records >= 1);
        const auto old_bytes = bytes(old_path);
        writer.step(writer.next_retry_ms()); // preserve failed file, new O_EXCL successor
        const std::string new_path = backend.log.path();
        assert(new_path != old_path && writer.active());
        for (unsigned step = 0; step < 20 && !writer.finished(); ++step) writer.step(1000 + step);
        assert(writer.finished() && writer.stats().verified_files == 1);
        const bool replay_pending = fault != injection::Fault::Close && fault != injection::Fault::Read;
        assert(writer.stats().verified_rows == (replay_pending ? 1U : 0U));
        assert(writer.stats().errors == 1 && writer.stats().uncertain_records >= 1);
        assert(bytes(old_path) == old_bytes); // failed segment was never overwritten or promoted
        if (replay_pending) {
            assert(writer.stats().retried_records == 1 && writer.stats().replayed_records == 1);
            assert(bytes(new_path).find("soil,1,42,") != std::string::npos); // original identity retained
        }
    }
}
}

int main(int argc, char** argv) {
    assert(argc == 2);
    const std::string root = argv[1];
    assert(std::filesystem::create_directory(root));
    write_failures(root); flush_sync_close_failures(root); read_failure(root);
    writer_never_counts_failed_file_as_verified(root);
    std::puts("HOST_STORAGE_IO_FAULT_TEST_PASS (TEST_ONLY real writer/CRT failures; FATFS/MicroSD HARDWARE_NOT_RUN)");
}
