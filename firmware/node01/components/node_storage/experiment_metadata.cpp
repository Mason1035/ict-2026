#include "node/experiment_metadata.hpp"
#include <cerrno>
#include <cinttypes>
#include <cstdio>
#include <cstring>
#include <fcntl.h>
#include <unistd.h>
#ifdef _WIN32
#include <io.h>
#endif

namespace node::storage {
namespace {
bool safe(const char* p) {
    if (!p || !*p) return false;
    for (; *p; ++p) if (!((*p >= 'a' && *p <= 'z') || (*p >= 'A' && *p <= 'Z') ||
            (*p >= '0' && *p <= '9') || *p == '_' || *p == '-' || *p == '/' || *p == '.' || *p == ':')) return false;
    return true;
}
std::uint32_t update(std::uint32_t crc, const char* data, std::size_t n) {
    for (std::size_t i = 0; i < n; ++i) {
        crc ^= static_cast<unsigned char>(data[i]);
        for (unsigned bit = 0; bit < 8; ++bit) crc = (crc >> 1) ^ (0xedb88320U & (0U - (crc & 1U)));
    }
    return crc;
}
}
bool ExperimentMetadata::save(const ExperimentRecord& r, bool final) {
    error_ = 0; bytes_ = 0; crc_ = 0; errno = 0;
    if (!safe(r.csv_path) || !safe(r.elf_sha256) || !safe(r.experiment_id) || !safe(r.stop_reason) || !r.source ||
            (std::strcmp(r.source,"REAL_SENSOR") && std::strcmp(r.source,"TEST_ONLY_SYNTHETIC")) || std::strlen(r.elf_sha256) != 64 ||
            r.requested_seconds < 30 || r.requested_seconds > 300 || (final && r.stop_us < r.start_us)) { error_ = EINVAL; return false; }
    const auto len = std::strlen(r.csv_path);
    if (len < 4 || len >= sizeof(path_) || std::strcmp(r.csv_path+len-4, ".CSV")) { error_ = EINVAL; return false; }
    std::memcpy(path_, r.csv_path, len+1); std::memcpy(path_+len-3, final ? "END" : "BEG", 3);
    const int n = std::snprintf(document_, sizeof(document_),
        "{\"record_type\":\"%s\",\"experiment_id\":\"%s\",\"elf_sha256\":\"%s\","
        "\"mode\":\"SANDBOX_EXPERIMENT_CAPTURE\",\"source\":\"%s\",\"calibration_status\":\"NOT_READY\","
        "\"metadata_status\":\"REQUIRES_INDEPENDENT_READBACK\",\"requested_seconds\":%u,\"start_us\":%" PRIu64 ",\"stop_us\":%" PRIu64 ","
        "\"actual_duration_us\":%" PRIu64 ",\"last_producer_ack_us\":%" PRIu64 ",\"stop_reason\":\"%s\",\"csv\":\"%s\","
        "\"imu_addresses\":[104,105],\"ads_address\":72,\"imu_odr_hz\":100,\"i2c_hz\":100000,\"sd_hz\":10000000,"
        "\"queue_capacity\":512,\"sync_rows\":256,\"write_buffer_bytes\":4096,"
        "\"produced\":%" PRIu64 ",\"enqueued\":%" PRIu64 ",\"dequeued\":%" PRIu64 ",\"accepted\":%" PRIu64 ",\"verified_rows\":%" PRIu64 ","
        "\"queue_drop\":%" PRIu64 ",\"internal_drop\":%" PRIu64 ",\"errors\":%" PRIu64 ",\"uncertain\":%" PRIu64 ",\"replay\":%" PRIu64 ","
        "\"i2c_errors\":%" PRIu64 ",\"lock_timeouts\":%" PRIu64 ",\"sensor_errors\":%" PRIu64 ",\"top_valid\":%" PRIu64 ",\"toe_valid\":%" PRIu64 ",\"soil_valid\":[%" PRIu64 ",%" PRIu64 ",%" PRIu64 "],"
        "\"csv_bytes\":%" PRIu64 ",\"csv_crc32\":\"%08" PRIx32 "\",\"csv_verified\":%s,\"storage_clean\":%s}\n",
        final ? "END" : r.start_us ? "BEGIN" : "START_INTENT",r.experiment_id,r.elf_sha256,r.source,r.requested_seconds,r.start_us,r.stop_us,
        r.stop_us >= r.start_us && r.stop_us ? r.stop_us-r.start_us : 0,r.last_producer_ack_us,r.stop_reason,r.csv_path,
        r.produced,r.enqueued,r.dequeued,r.accepted,r.verified_rows,r.queue_drop,r.internal_drop,r.errors,r.uncertain,r.replay,
        r.i2c_errors,r.lock_timeouts,r.sensor_errors,r.top_valid,r.toe_valid,r.soil_valid[0],r.soil_valid[1],r.soil_valid[2],
        r.csv_bytes,r.csv_crc,r.csv_verified ? "true" : "false",r.storage_clean ? "true" : "false");
    if (n < 0 || static_cast<std::size_t>(n) >= sizeof(document_)) { error_ = EOVERFLOW; return false; }
    bytes_ = static_cast<std::size_t>(n);
    int flags = O_CREAT | O_EXCL | O_WRONLY;
#ifdef _WIN32
    flags |= O_BINARY;
#endif
    const int fd = ::open(path_, flags, 0600);
    if (fd < 0) { error_ = errno ? errno : EIO; return false; }
    auto* file = fdopen(fd, "wb");
    if (!file) { error_ = errno ? errno : EIO; ::close(fd); return false; }
    // Fixed application buffer already holds the entire small document. Avoid
    // another hidden stdio buffer allocation for this infrequent sidecar.
    bool ok = std::setvbuf(file, nullptr, _IONBF, 0) == 0;
    if (ok) ok = std::fwrite(document_, 1, bytes_, file) == bytes_;
    if (!ok) error_ = errno ? errno : EIO;
    if (ok && std::fflush(file) != 0) { error_ = errno ? errno : EIO; ok = false; }
#ifdef _WIN32
    if (ok && _commit(fileno(file)) != 0) { error_ = errno ? errno : EIO; ok = false; }
#else
    if (ok && fsync(fileno(file)) != 0) { error_ = errno ? errno : EIO; ok = false; }
#endif
    if (std::fclose(file) != 0) { if (!error_) error_ = errno ? errno : EIO; ok = false; }
    if (!ok) return false; // leave partial evidence, never rewrite as success
    file = std::fopen(path_, "rb");
    if (!file) { error_ = errno ? errno : EIO; return false; }
    std::size_t total = 0; std::uint32_t crc = 0xffffffffU;
    for (;;) {
        const auto count = std::fread(readback_, 1, sizeof(readback_), file);
        if (!count) break;
        if (count > bytes_-total || std::memcmp(document_+total,readback_,count)) { error_ = EIO; ok = false; break; }
        total += count; crc = update(crc,readback_,count);
    }
    ok = ok && !std::ferror(file) && std::feof(file) && total == bytes_;
    if (!ok && !error_) error_ = errno ? errno : EIO;
    if (std::fclose(file) != 0) { if (!error_) error_ = errno ? errno : EIO; ok = false; }
    crc_ = crc ^ 0xffffffffU;
    return ok;
}
}
