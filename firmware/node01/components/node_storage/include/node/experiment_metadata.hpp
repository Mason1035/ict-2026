#pragma once
#include <cstddef>
#include <cstdint>

namespace node::storage {
struct ExperimentRecord {
    const char* source = "REAL_SENSOR";
    const char* experiment_id = "";
    const char* elf_sha256 = "";
    const char* csv_path = "";
    const char* stop_reason = "NONE";
    unsigned requested_seconds = 0;
    std::uint64_t start_us = 0, stop_us = 0;
    std::uint64_t last_producer_ack_us = 0;
    std::uint64_t produced = 0, enqueued = 0, dequeued = 0, accepted = 0, verified_rows = 0;
    std::uint64_t queue_drop = 0, internal_drop = 0, errors = 0, uncertain = 0, replay = 0;
    std::uint64_t i2c_errors = 0, lock_timeouts = 0, sensor_errors = 0;
    std::uint64_t top_valid = 0, toe_valid = 0, soil_valid[3]{};
    std::uint64_t csv_bytes = 0;
    std::uint32_t csv_crc = 0;
    bool csv_verified = false, storage_clean = false;
};
// StorageTask sole owner. Fixed buffers stay in static instance, not its stack.
// Each .BEG/.END file is O_EXCL, synced, closed, byte/length/CRC/EOF checked.
class ExperimentMetadata {
public:
    bool save(const ExperimentRecord&, bool final);
    const char* path() const { return path_; }
    int last_error() const { return error_; }
    std::size_t bytes() const { return bytes_; }
    std::uint32_t crc32() const { return crc_; }
private:
    char document_[2048]{}, path_[128]{}, readback_[128]{};
    int error_ = 0;
    std::size_t bytes_ = 0;
    std::uint32_t crc_ = 0;
};
}
