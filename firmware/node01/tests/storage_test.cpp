#include "node/diagnostic_log.hpp"
#include <cassert>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <string>
#include <array>
#include <cstdio>
#include <cstring>
#include <cerrno>
#include <cinttypes>
#include <limits>
#include <vector>

namespace {
// Independent compatibility oracle: the pre-optimization field-by-field writer.
// It intentionally retains the old sequence/precision rather than reconstructing
// expected CSV from the new all-row format strings.
std::string original_csv_row(const node::sampling::AcquisitionRecord& r) {
    std::string out;
    auto add = [&](const char* format, auto... args) {
        char text[128]{};
        const int n = std::snprintf(text, sizeof(text), format, args...);
        assert(n >= 0 && static_cast<std::size_t>(n) < sizeof(text));
        out.append(text, static_cast<std::size_t>(n));
    };
    const bool imu = r.kind == node::sampling::RecordKind::Imu;
    const auto valid = imu ? r.imu.validity : r.soil.validity;
    const auto time = imu ? r.imu.acquired_uptime_us : r.soil.acquired_uptime_us;
    const char* state = valid == node::sampling::Validity::Valid ? "Valid" :
        valid == node::sampling::Validity::Error ? "Error" : "Unavailable";
    add("%s,%u,%" PRIu64 ",%" PRIu64 ",", imu ? "imu" : "soil", r.channel,
        static_cast<std::uint64_t>(r.acquisition_index), r.attempted_uptime_us);
    if (time) add("%" PRIu64, *time);
    add(",,false,%s,%d", state, r.error);
    for (unsigned i = 0; i != 6; ++i) {
        add(",");
        if (imu && valid == node::sampling::Validity::Valid) add("%d", static_cast<int>(r.imu_raw[i]));
    }
    for (unsigned i = 0; i != 6; ++i) {
        add(",");
        if (imu && valid == node::sampling::Validity::Valid)
            add("%.9g", static_cast<double>(i < 3 ? r.imu.acceleration_mps2[i] : r.imu.angular_rate_dps[i - 3]));
    }
    add(",");
    if (!imu && valid == node::sampling::Validity::Valid && r.soil.raw) add("%d", static_cast<int>(*r.soil.raw));
    add("\n");
    return out;
}
std::uint64_t test_clock_value = 0;
std::uint64_t test_clock() { test_clock_value += 7; return test_clock_value; }
void csv_compatibility_and_phase_timing(const std::string& dir) {
    // All validity states, missing/zero/max times, absent/zero/extreme raw Soil,
    // signed raw IMU extremes, signed zero and very small/large floating fields.
    std::vector<node::sampling::AcquisitionRecord> records;
    const std::array<node::sampling::Validity, 3> states{node::sampling::Validity::Valid,
        node::sampling::Validity::Unavailable, node::sampling::Validity::Error};
    for (unsigned kind = 0; kind != 2; ++kind) for (const auto state : states)
        for (unsigned choice = 0; choice != 4; ++choice) {
            node::sampling::AcquisitionRecord r;
            r.kind = kind ? node::sampling::RecordKind::Soil : node::sampling::RecordKind::Imu;
            r.channel = choice;
            r.acquisition_index = std::numeric_limits<std::uint64_t>::max() - records.size();
            r.attempted_uptime_us = std::numeric_limits<std::uint64_t>::max();
            if (choice) r.imu.acquired_uptime_us = r.soil.acquired_uptime_us = choice == 1 ? 0 :
                choice == 2 ? 123456789 : std::numeric_limits<std::uint64_t>::max();
            r.imu.validity = r.soil.validity = state;
            if (choice) r.soil.raw = static_cast<std::int16_t>(choice == 1 ? 0 : choice == 2 ? -32768 : 32767);
            r.imu_raw = {-32768, -1, 0, 1, 12345, 32767};
            r.imu.acceleration_mps2 = {-0.0F, std::numeric_limits<float>::max(), std::numeric_limits<float>::min()};
            r.imu.angular_rate_dps = {-1234.56789F, 0.0000123456789F, 9876543.0F};
            r.error = choice == 3 ? std::numeric_limits<int>::min() : state == node::sampling::Validity::Error ? ESP_ERR_TIMEOUT : 0;
            records.push_back(r);
        }
    // Cross many 4-KiB write boundaries with non-repeating input. TEST_ONLY.
    for (unsigned i = 0; i != 512; ++i) {
        auto r = records[i % records.size()];
        r.channel = i % 3; r.acquisition_index = i;
        r.attempted_uptime_us = static_cast<std::uint64_t>(i) * 1234567;
        r.imu.acceleration_mps2[0] = static_cast<float>(static_cast<int>(i) - 256) / 17.0F;
        records.push_back(r);
    }
    std::string expected;
    node::storage::DiagnosticLog log(test_clock);
    assert(log.timing_enabled() && log.open_new(dir.c_str(), "# TEST_ONLY CSV compatibility; not hardware\n"));
    const std::string path = log.path();
    for (const auto& r : records) { expected += original_csv_row(r); assert(log.append(r)); }
    assert(log.rows() == records.size() && log.close_and_verify());
    std::ifstream in(path, std::ios::binary);
    const std::string actual((std::istreambuf_iterator<char>(in)), {});
    const auto header = actual.find("\nkind,channel,");
    assert(header != std::string::npos);
    const auto first_row = actual.find('\n', header + 1) + 1;
    assert(actual.substr(first_row) == expected);
    const auto& times = log.timings();
    auto phase = [&](node::storage::LogPhase p) -> const auto& { return times[static_cast<unsigned>(p)]; };
    assert(phase(node::storage::LogPhase::Format).calls == records.size());
    assert(phase(node::storage::LogPhase::Write).calls == records.size() + 3);
    assert(phase(node::storage::LogPhase::Crc).calls == records.size() + 3);
    assert(phase(node::storage::LogPhase::Write).bytes == actual.size());
    assert(phase(node::storage::LogPhase::Crc).bytes == actual.size());
    assert(phase(node::storage::LogPhase::Flush).calls == 1 && phase(node::storage::LogPhase::Sync).calls == 1);
    for (const auto& t : times) assert(t.failures == 0 && t.max_us == 7 && t.total_us == t.calls * 7);
    // A local rejection never pretends to have entered fwrite. Timer snapshots
    // also remain cumulative across files instead of silently clearing history.
    const auto before = phase(node::storage::LogPhase::Write).calls;
    assert(!log.append(records.front()) && log.last_error() == EBADF);
    assert(phase(node::storage::LogPhase::Write).calls == before);
    assert(log.open_new(dir.c_str(), "# TEST_ONLY next file\n") && log.close_and_verify());
    assert(phase(node::storage::LogPhase::Write).calls == before + 3);
}
void incremental_boundaries(const std::string& dir) {
    // Independent standard CRC-32 values generated with Python zlib for A*n.
    const std::array<unsigned, 11> sizes{0, 1, 511, 512, 513, 1024, 4095, 4096, 4097, 8192, 65536};
    const std::array<std::uint32_t, 11> crcs{0, 0xd3d99e8bU, 0x1b4e4ebdU,
        0x66121ff4U, 0x696fba91U, 0xb737fb1aU, 0x7d4546ffU, 0xfea63440U,
        0xa5fb792fU, 0x32253bccU, 0xa09b0680U};
    for (unsigned k = 0; k < sizes.size(); ++k) {
        const auto path = dir + "/B" + std::to_string(k);
        std::ofstream(path, std::ios::binary) << std::string(sizes[k], 'A');
        node::storage::ClosedSegment expected;
        assert(std::snprintf(expected.path, sizeof(expected.path), "%s", path.c_str()) < static_cast<int>(sizeof(expected.path)));
        expected.bytes = sizes[k]; expected.crc32 = crcs[k];
        node::storage::IncrementalVerifier reader;
        assert(reader.begin(expected));
        assert(!reader.begin(expected)); // cannot overwrite the one active descriptor
        auto result = node::storage::VerifyResult::Pending;
        unsigned steps = 0;
        while (result == node::storage::VerifyResult::Pending) {
            const auto before = reader.bytes_read();
            result = reader.step();
            assert(reader.bytes_read() - before <= node::storage::IncrementalVerifier::read_quantum && ++steps < 100);
        }
        assert(result == node::storage::VerifyResult::Passed && !reader.active());
        assert(reader.bytes_read() == sizes[k]);
        assert(steps == (sizes[k] + node::storage::IncrementalVerifier::read_quantum - 1) /
            node::storage::IncrementalVerifier::read_quantum + 1);
        // Extra suffix, including exact-4-KiB boundaries, must fail rather than
        // accepting the prefix as a complete file.
        std::ofstream(path, std::ios::app | std::ios::binary) << 'X';
        assert(reader.begin(expected));
        do { result = reader.step(); } while (result == node::storage::VerifyResult::Pending);
        assert(result == node::storage::VerifyResult::Failed);
        // Also distinguish a short file and a same-size CRC mismatch.
        std::ofstream(path, std::ios::binary | std::ios::trunc) << std::string(sizes[k] ? sizes[k] - 1 : 1, 'A');
        assert(reader.begin(expected));
        do { result = reader.step(); } while (result == node::storage::VerifyResult::Pending);
        assert(result == node::storage::VerifyResult::Failed);
        std::ofstream(path, std::ios::binary | std::ios::trunc) << std::string(sizes[k], 'A');
        expected.crc32 ^= 1;
        assert(reader.begin(expected));
        do { result = reader.step(); } while (result == node::storage::VerifyResult::Pending);
        assert(result == node::storage::VerifyResult::Failed);
    }
}
void data_rows_cross_chunk_and_reject_wrong_count(const std::string& dir) {
    // TEST_ONLY contents chosen to split "imu," across byte 4096 and place its
    // terminating newline exactly at byte 8192. CRCs are independent Python zlib.
    const std::string text = "#" + std::string(4091, 'X') + "\nimu," + std::string(4094, '1') +
        "\n# imu,metadata only\nkind,channel,columns\nsoil,1,41,,false,Error,263,,,,,,,,,,,,,\n";
    assert(text.size() == 8273);
    const auto path = dir + "/row-boundary";
    std::ofstream(path, std::ios::binary) << text;
    node::storage::ClosedSegment segment;
    assert(std::snprintf(segment.path, sizeof(segment.path), "%s", path.c_str()) < static_cast<int>(sizeof(segment.path)));
    segment.bytes = text.size(); segment.rows = 2; segment.crc32 = 0x91b0c06cU;
    node::storage::IncrementalVerifier reader;
    auto finish = [&] {
        assert(reader.begin(segment));
        auto result = node::storage::VerifyResult::Pending;
        while (result == node::storage::VerifyResult::Pending) result = reader.step();
        return result;
    };
    assert(finish() == node::storage::VerifyResult::Passed && reader.rows_read() == 2);
    assert(node::storage::DiagnosticLog::verify_file(path.c_str(), segment.bytes, segment.crc32, 2));
    // Same bytes, CRC, and EOF; the independent row-count requirement rejects it.
    segment.rows = 1;
    assert(finish() == node::storage::VerifyResult::Failed && reader.rows_read() == 2);
    assert(!node::storage::DiagnosticLog::verify_file(path.c_str(), segment.bytes, segment.crc32, 1));
    segment.rows = 3;
    assert(finish() == node::storage::VerifyResult::Failed);
    // A recomputed matching CRC cannot turn an unterminated data line into a row.
    std::ofstream(path, std::ios::binary | std::ios::trunc) << text.substr(0, text.size() - 1);
    segment.bytes = text.size() - 1; segment.crc32 = 0xdbc68b62U; segment.rows = 2;
    assert(finish() == node::storage::VerifyResult::Failed && reader.rows_read() == 1);
    assert(!node::storage::DiagnosticLog::verify_file(path.c_str(), segment.bytes, segment.crc32, 2));
}
void historic_filename_scan_preserves_evidence(const std::string& dir) {
    const auto subdir = dir + "/scan";
    assert(std::filesystem::create_directory(subdir));
    const auto prior = subdir + "/N0001234.CSV";
    std::ofstream(prior) << "historic evidence";
    // Similar-looking unrelated names must not exhaust the diagnostic namespace.
    std::ofstream(subdir + "/N9999999.CSV.bak") << "other";
    std::ofstream(subdir + "/NXXXXXXX.CSV") << "other";
    node::storage::DiagnosticLog log;
    assert(log.open_new(subdir.c_str(), "# TEST_ONLY directory scan\n"));
    assert(std::string(log.path()) == subdir + "/N0001235.CSV");
    assert(log.close_and_verify());
    // External creation after the one-time scan is still protected by O_EXCL.
    std::ofstream(subdir + "/N0001236.CSV") << "external evidence";
    assert(log.open_new(subdir.c_str(), "# TEST_ONLY collision\n"));
    assert(std::string(log.path()) == subdir + "/N0001237.CSV");
    assert(log.close_and_verify());
    std::ifstream before(prior);
    assert(std::string((std::istreambuf_iterator<char>(before)), {}) == "historic evidence");
    const auto other = dir + "/other";
    assert(std::filesystem::create_directory(other));
    std::ofstream(other + "/N0000042.CSV") << "another directory";
    assert(log.open_new(other.c_str(), "# TEST_ONLY changed directory\n"));
    assert(std::string(log.path()) == other + "/N0000043.CSV");
    assert(log.close_and_verify());
    const auto full = dir + "/full";
    assert(std::filesystem::create_directory(full));
    std::ofstream(full + "/N9999999.CSV") << "last evidence";
    assert(!log.open_new(full.c_str(), "# TEST_ONLY namespace exhaustion\n"));
    assert(log.last_error() == ENOSPC);
    assert(std::filesystem::file_size(full + "/N9999999.CSV") == 13);
}
void incremental_readback_interleaves_writes(const std::string& dir) {
    node::storage::DiagnosticLog log;
    assert(log.open_new(dir.c_str(), "# TEST_ONLY synthetic host records; no hardware evidence\n"));
    node::sampling::AcquisitionRecord record;
    record.kind = node::sampling::RecordKind::Soil;
    record.soil.raw = 0; record.soil.validity = node::sampling::Validity::Valid;
    record.soil.acquired_uptime_us = 10000;
    for (unsigned i = 0; i < 1000; ++i) { record.acquisition_index = i; assert(log.append(record)); }
    node::storage::ClosedSegment closed;
    assert(log.close_for_verification(closed) && closed.rows == 1000);
    assert(closed.bytes > 512 && !std::strcmp(closed.path, log.path()));
    node::storage::IncrementalVerifier reader;
    assert(reader.begin(closed));
    assert(log.open_new(dir.c_str(), "# TEST_ONLY next segment while old readback is pending\n"));
    assert(std::strcmp(log.path(), closed.path));
    unsigned wrote_during_readback = 0;
    auto result = node::storage::VerifyResult::Pending;
    while (result == node::storage::VerifyResult::Pending) {
        result = reader.step();
        record.acquisition_index = 1000 + wrote_during_readback;
        assert(log.append(record));
        ++wrote_during_readback;
    }
    assert(result == node::storage::VerifyResult::Passed && wrote_during_readback > 1);
    assert(reader.rows_read() == closed.rows);
    assert(log.rows() == wrote_during_readback && log.close_and_verify());
}
}

int main(int argc, char** argv) {
    assert(argc == 2);
    const std::string dir = argv[1];
    assert(std::filesystem::create_directory(dir));
    node::storage::DiagnosticLog log;
    assert(log.open_new(dir.c_str(), "# TEST_ONLY host input; no real sensor data\n"));
    const std::string first = log.path();
    node::sampling::AcquisitionRecord r;
    r.kind = node::sampling::RecordKind::Soil; r.channel = 1;
    r.soil.raw = 0; r.soil.validity = node::sampling::Validity::Valid;
    r.soil.acquired_uptime_us = 1234;
    assert(log.append(r));
    r.acquisition_index = 1;
    r.soil = {}; r.soil.validity = node::sampling::Validity::Error;
    r.error = ESP_ERR_TIMEOUT;
    assert(log.append(r));
    const auto crc = log.crc32();
    assert(log.close_and_verify());
    const auto bytes = std::filesystem::file_size(first);
    assert(node::storage::DiagnosticLog::verify_file(first.c_str(), bytes, crc));
    std::ifstream in(first);
    const std::string text((std::istreambuf_iterator<char>(in)), {});
    assert(text.find("1234,,false,Valid,0") != std::string::npos);
    assert(text.find(",Error,263,,,,,,,,,,,,,\n") != std::string::npos);
    in.close();
    // A new owner after restart must not overwrite a pre-existing diagnostic file.
    node::storage::DiagnosticLog restarted;
    assert(restarted.open_new(dir.c_str(), "# TEST_ONLY\n"));
    assert(first != restarted.path());
    assert(restarted.close_and_verify());
    // Deliberately corrupt ONLY the host test artifact, then prove readback rejects it.
    std::ofstream corrupt(first, std::ios::app | std::ios::binary);
    corrupt << 'X'; corrupt.close();
    assert(!node::storage::DiagnosticLog::verify_file(first.c_str(), bytes, crc));
    node::storage::DiagnosticLog failure;
    assert(!failure.open_new((dir + "/missing/subdir").c_str(), "# TEST_ONLY\n"));
    data_rows_cross_chunk_and_reject_wrong_count(dir);
    historic_filename_scan_preserves_evidence(dir);
    incremental_boundaries(dir);
    incremental_readback_interleaves_writes(dir);
    csv_compatibility_and_phase_timing(dir);
}
