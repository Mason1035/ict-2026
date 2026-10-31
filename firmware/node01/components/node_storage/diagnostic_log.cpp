#include "node/diagnostic_log.hpp"
#include <cerrno>
#include <cinttypes>
#include <cstdarg>
#include <cstring>
#include <fcntl.h>
#include <dirent.h>
#include <unistd.h>
#ifdef _WIN32
#include <io.h>
#endif

namespace node::storage {
namespace {
constexpr std::uint32_t nibble[16] = {
    0x00000000U, 0x1db71064U, 0x3b6e20c8U, 0x26d930acU,
    0x76dc4190U, 0x6b6b51f4U, 0x4db26158U, 0x5005713cU,
    0xedb88320U, 0xf00f9344U, 0xd6d6a3e8U, 0xcb61b38cU,
    0x9b64c2b0U, 0x86d3d2d4U, 0xa00ae278U, 0xbdbdf21cU};
std::uint32_t update_crc(std::uint32_t crc, const char* p, std::size_t n) {
    for (std::size_t i = 0; i < n; ++i) {
        crc ^= static_cast<unsigned char>(p[i]);
        // Standard reflected CRC-32, two four-bit lookups per byte. The 64-byte
        // read-only table avoids eight conditional bit rounds per CSV byte.

        crc = (crc >> 4) ^ nibble[crc & 15U];
        crc = (crc >> 4) ^ nibble[crc & 15U];
    }
    return crc;
}
const char* validity(sampling::Validity v) {
    switch (v) {
    case sampling::Validity::Valid: return "Valid";
    case sampling::Validity::Error: return "Error";
    default: return "Unavailable";
    }
}
}
void DataRowCounter::consume(const char* data, std::size_t bytes) {
    for (std::size_t i = 0; i < bytes; ++i) {
        const char ch = data[i];
        if (ch == '\n') {
            if ((prefix_bytes_ >= 4 && std::memcmp(prefix_, "imu,", 4) == 0) ||
                    (prefix_bytes_ == 5 && std::memcmp(prefix_, "soil,", 5) == 0)) ++rows_;
            prefix_bytes_ = 0;
        } else if (prefix_bytes_ < sizeof(prefix_)) prefix_[prefix_bytes_++] = ch;
    }
}
DiagnosticLog::~DiagnosticLog() { abandon(); }
void DiagnosticLog::end_timing(LogPhase phase, bool success, std::uint64_t started, std::size_t bytes) {
    const auto finished = clock_ ? clock_() : 0;
    const auto elapsed = finished >= started ? finished - started : 0;
    auto& value = timings_[static_cast<unsigned>(phase)];
    ++value.calls;
    if (!success) ++value.failures;
    value.total_us += elapsed; value.bytes += bytes;
    if (elapsed > value.max_us) value.max_us = elapsed;
}
void DiagnosticLog::abandon() {
    if (file_) {
        // Preserve the triggering error; fclose can alter errno or finish an
        // uncertain buffered write, but that does not make the segment verified.
        const int original = error_;
        errno = 0;
        if (std::fclose(file_) != 0 && !original) error_ = errno ? errno : EIO;
        if (original) error_ = original;
        file_ = nullptr;
    }
}
bool DiagnosticLog::locate_next_file(const char* directory) {
    if (std::strcmp(directory_, directory) == 0) return true;
    if (std::strlen(directory) >= sizeof(directory_)) { errno = error_ = ENAMETOOLONG; return false; }
    // Discover the high-water filename once, instead of issuing open(O_EXCL)
    // for every historic segment on each boot. Creation still uses O_EXCL:
    // an externally added collision must never overwrite existing evidence.
    DIR* entries = opendir(directory);
    if (!entries) { error_ = errno ? errno : EIO; return false; }
    unsigned next = 1;
    errno = 0;
    while (const auto* entry = readdir(entries)) {
        const char* name = entry->d_name;
        if (std::strlen(name) != 12 || name[0] != 'N' || std::strcmp(name + 8, ".CSV")) continue;
        unsigned index = 0;
        bool numeric = true;
        for (unsigned i = 1; i != 8; ++i) {
            if (name[i] < '0' || name[i] > '9') { numeric = false; break; }
            index = index * 10 + static_cast<unsigned>(name[i] - '0');
        }
        if (numeric && index >= next) next = index + 1;
    }
    const int scan_error = errno;
    const bool closed = closedir(entries) == 0;
    if (scan_error || !closed) { errno = error_ = scan_error ? scan_error : (errno ? errno : EIO); return false; }
    next_file_ = next;
    std::strcpy(directory_, directory);
    return true;
}
bool DiagnosticLog::open_new(const char* directory, const char* metadata) {
    if (file_ || !directory || !directory[0] || !metadata) { errno = error_ = EINVAL; return false; }
    error_ = 0; poisoned_ = write_uncertain_ = false;
    if (!locate_next_file(directory)) return false;
    for (unsigned attempts = 0; attempts < 4096 && next_file_ <= 9999999; ++attempts) {
        const int n = std::snprintf(path_, sizeof(path_), "%s/N%07u.CSV", directory, next_file_++);
        if (n < 0 || static_cast<unsigned>(n) >= sizeof(path_)) { errno = error_ = ENAMETOOLONG; return false; }
        int flags = O_CREAT | O_EXCL | O_WRONLY;
#ifdef _WIN32
        flags |= O_BINARY;
#endif
        const int fd = ::open(path_, flags, 0600);
        if (fd < 0) { if (errno == EEXIST) continue; error_ = errno ? errno : EIO; return false; }
        file_ = fdopen(fd, "wb");
        if (!file_) { error_ = errno ? errno : EIO; ::close(fd); errno = error_; return false; }
        if (std::setvbuf(file_, buffer_, _IOFBF, sizeof(buffer_)) != 0) { error_ = errno ? errno : EIO; abandon(); errno = error_; return false; }
        crc_ = 0xffffffffU; bytes_ = rows_ = 0;
        constexpr const char* header =
            "# NODE01_ENGINEERING_DIAGNOSTIC_V1; not experiment CSV; not training data; calibration=TODO_CALIBRATION\n"
            "# timestamp_ms unavailable; acquisition_index boot-local diagnostic only, NOT formal message seq\n";
        constexpr const char* columns =
            "kind,channel,acquisition_index,attempted_uptime_us,acquired_uptime_us,timestamp_ms,time_synced,validity,error,"
            "ax_raw,ay_raw,az_raw,gx_raw,gy_raw,gz_raw,ax_mps2,ay_mps2,az_mps2,gx_dps,gy_dps,gz_dps,soil_raw\n";
        if (!write_bytes(header, std::strlen(header)) || !write_bytes(metadata, std::strlen(metadata)) ||
            !write_bytes(columns, std::strlen(columns))) { abandon(); return false; }
        // Header and rows share the same buffered-write/sync boundary. Normal
        // flush and close/readback still apply; no power-loss claim is made.
        return true;
    }
    errno = error_ = ENOSPC; return false;
}
bool DiagnosticLog::write_bytes(const char* data, std::size_t n) {
    if (!file_ || poisoned_) { errno = error_ = file_ ? EIO : EBADF; return false; }
    const auto write_started = start_timing();
    errno = 0;
    const auto accepted = std::fwrite(data, 1, n, file_);
    const int write_error = errno;
    end_timing(LogPhase::Write, accepted == n, write_started, accepted);
    const auto crc_started = start_timing();
    crc_ = update_crc(crc_, data, accepted); bytes_ += accepted;
    end_timing(LogPhase::Crc, true, crc_started, accepted);
    if (accepted != n) {
        error_ = write_error ? write_error : EIO; poisoned_ = write_uncertain_ = true;
        errno = error_; return false;
    }
    return true;
}
bool DiagnosticLog::append(const sampling::AcquisitionRecord& r) {
    write_uncertain_ = false;
    const auto format_started = start_timing();
    char line[512]{};
    const bool imu = r.kind == sampling::RecordKind::Imu;
    const auto valid = imu ? r.imu.validity : r.soil.validity;
    const auto time = imu ? r.imu.acquired_uptime_us : r.soil.acquired_uptime_us;
    char time_text[21]{}; // full uint64 decimal + NUL; absent remains empty
    if (time) std::snprintf(time_text, sizeof(time_text), "%" PRIu64, *time);
    int n;
    if (imu && valid == sampling::Validity::Valid) {
        // Preserve the exact existing CSV format/%.9g precision, while replacing
        // dozens of tiny printf invocations with one complete row operation.
        n = std::snprintf(line, sizeof(line),
            "imu,%u,%" PRIu64 ",%" PRIu64 ",%s,,false,Valid,%d,%d,%d,%d,%d,%d,%d,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,\n",
            r.channel, static_cast<std::uint64_t>(r.acquisition_index), r.attempted_uptime_us, time_text, r.error,
            static_cast<int>(r.imu_raw[0]), static_cast<int>(r.imu_raw[1]), static_cast<int>(r.imu_raw[2]),
            static_cast<int>(r.imu_raw[3]), static_cast<int>(r.imu_raw[4]), static_cast<int>(r.imu_raw[5]),
            static_cast<double>(r.imu.acceleration_mps2[0]), static_cast<double>(r.imu.acceleration_mps2[1]),
            static_cast<double>(r.imu.acceleration_mps2[2]), static_cast<double>(r.imu.angular_rate_dps[0]),
            static_cast<double>(r.imu.angular_rate_dps[1]), static_cast<double>(r.imu.angular_rate_dps[2]));
    } else {
        char soil_text[8]{};
        if (!imu && valid == sampling::Validity::Valid && r.soil.raw)
            std::snprintf(soil_text, sizeof(soil_text), "%d", static_cast<int>(*r.soil.raw));
        n = std::snprintf(line, sizeof(line), "%s,%u,%" PRIu64 ",%" PRIu64 ",%s,,false,%s,%d,,,,,,,,,,,,,%s\n",
            imu ? "imu" : "soil", r.channel, static_cast<std::uint64_t>(r.acquisition_index),
            r.attempted_uptime_us, time_text, validity(valid), r.error, soil_text);
    }
    const bool formatted = n >= 0 && static_cast<std::size_t>(n) < sizeof(line);
    end_timing(LogPhase::Format, formatted, format_started);
    if (!formatted) { errno = error_ = EOVERFLOW; return false; } // no write was attempted
    if (!write_bytes(line, static_cast<std::size_t>(n))) return false;
    ++rows_;
    return true;
}
bool DiagnosticLog::flush() {
    if (!file_) { errno = error_ = EBADF; return false; }
    const auto flush_started = start_timing();
    errno = 0;
    const bool flushed = std::fflush(file_) == 0;
    const int flush_error = errno;
    end_timing(LogPhase::Flush, flushed, flush_started);
    if (!flushed) {
        error_ = flush_error ? flush_error : EIO; poisoned_ = write_uncertain_ = true;
        errno = error_; return false;
    }
    const auto sync_started = start_timing();
    errno = 0;
#ifdef _WIN32
    const bool synced = _commit(fileno(file_)) == 0;
#else
    const bool synced = fsync(fileno(file_)) == 0;
#endif
    const int sync_error = errno;
    end_timing(LogPhase::Sync, synced, sync_started);
    if (!synced || poisoned_) {
        error_ = sync_error ? sync_error : EIO; poisoned_ = write_uncertain_ = true;
        errno = error_; return false;
    }
    return true;
}
bool DiagnosticLog::verify_file(const char* path, std::size_t expected_bytes, std::uint32_t expected_crc,
        std::optional<unsigned> expected_rows) {
    errno = 0;
    auto* f = std::fopen(path, "rb");
    if (!f) return false;
    char chunk[512]; std::size_t bytes = 0;
    DataRowCounter row_counter;
    std::uint32_t crc = 0xffffffffU;
    while (bytes <= expected_bytes) {
        const auto n = std::fread(chunk, 1, sizeof(chunk), f);
        if (!n) break;
        bytes += n; crc = update_crc(crc, chunk, n); row_counter.consume(chunk, n);
    }
    bool ok = !std::ferror(f) && bytes == expected_bytes && (crc ^ 0xffffffffU) == expected_crc &&
        (!expected_rows || row_counter.rows() == *expected_rows);
    int failure = ok ? 0 : (errno ? errno : EIO);
    if (std::fclose(f) != 0) { ok = false; if (!failure) failure = errno ? errno : EIO; }
    if (!ok) errno = failure;
    return ok;
}
bool DiagnosticLog::close_and_verify() {
    ClosedSegment segment;
    if (!close_for_verification(segment)) return false;
    if (!verify_file(segment.path, segment.bytes, segment.crc32, segment.rows)) {
        errno = error_ = errno ? errno : EIO; poisoned_ = true; return false;
    }
    return true;
}
bool DiagnosticLog::close_for_verification(ClosedSegment& segment) {
    segment = {};
    if (!file_) { errno = error_ = EBADF; return false; }
    bool ok = flush();
    int failure = ok ? 0 : error_;
    if (std::fclose(file_) != 0) { ok = false; if (!failure) failure = errno ? errno : EIO; }
    file_ = nullptr;
    if (!ok) { errno = error_ = failure ? failure : EIO; poisoned_ = true; }
    else {
        std::memcpy(segment.path, path_, sizeof(segment.path));
        segment.bytes = bytes_; segment.rows = rows_; segment.crc32 = crc32();
    }
    return ok;
}
void IncrementalVerifier::cancel() {
    if (fd_ >= 0) {
        const int original = error_;
        if (::close(fd_) != 0 && !original) error_ = errno ? errno : EIO;
        if (original) error_ = original;
        fd_ = -1;
    }
}
bool IncrementalVerifier::begin(const ClosedSegment& segment) {
    if (fd_ >= 0) { errno = EBUSY; return false; } // do not replace/poison the existing readback
    if (!segment.path[0]) { errno = error_ = EINVAL; return false; }
    error_ = 0;
    int flags = O_RDONLY;
#ifdef _WIN32
    flags |= O_BINARY;
#endif
    fd_ = ::open(segment.path, flags);
    if (fd_ < 0) { error_ = errno ? errno : EIO; return false; }
    // A POSIX read avoids stdio prefetch and unbuffered one-byte refill loops.
    segment_ = segment; bytes_ = 0; crc_ = 0xffffffffU; row_counter_.reset();
    return true;
}
VerifyResult IncrementalVerifier::finish(bool valid) {
    if (!valid && !error_) error_ = EIO;
    cancel();
    if (error_) { errno = error_; return VerifyResult::Failed; }
    return VerifyResult::Passed;
}
VerifyResult IncrementalVerifier::step() {
    if (fd_ < 0) { errno = error_ = EBADF; return VerifyResult::Failed; }
    // Request one extra byte only when it fits this same <=4-KiB quantum;
    // exact multiples get a separate EOF step, rejecting trailing corruption.
    // Multi-sector reads amortize the measured per-read SD command overhead.
    const auto remaining = segment_.bytes - bytes_;
    const auto request = remaining >= sizeof(buffer_) ? sizeof(buffer_) : remaining + 1;
    errno = 0;
    const auto received = ::read(fd_, buffer_, request);
    if (received < 0) { error_ = errno ? errno : EIO; return finish(false); }
    const auto count = static_cast<std::size_t>(received);
    crc_ = update_crc(crc_, buffer_, count); bytes_ += count; row_counter_.consume(buffer_, count);
    if (bytes_ > segment_.bytes) return finish(false);
    if (!count)
        return finish(bytes_ == segment_.bytes && (crc_ ^ 0xffffffffU) == segment_.crc32 &&
            row_counter_.rows() == segment_.rows);
    return VerifyResult::Pending;
}
}
