#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

namespace node::drivers::toe_trace {

struct Edge {
    std::uint64_t us = 0;
    std::uint32_t irq_number = 0;
    bool level_high = false;
};
struct Request {
    std::uint64_t request_us = 0, sdk_begin_us = 0, sdk_end_us = 0, end_us = 0;
    std::uint64_t last_edge_us = 0, last_valid_us = 0;
    std::uint32_t seq = 0;
    std::int32_t result = 0;
    std::uint8_t status = 0;
    char origin = 'A'; // Arm, IRQ, Poll
    bool sdk_entered = false;
    bool status_present = false;
    std::uint8_t address = 0, reg = 0;
    std::uint64_t lock_wait_us = 0, raw_begin_us = 0, raw_end_us = 0;
    std::int32_t raw_result = 0;
    bool raw_entered = false;
};

// One ISR writer owns edges under irq_lock. ImuTask is the sole request writer.
// The exporter reads both parts after the producer has stopped and IRQ is disabled.
class Trace {
public:
    static constexpr std::size_t edge_limit = 128;
    static constexpr std::size_t first_limit = 32;
    static constexpr std::size_t around = 8;

    bool wants_edge() const { return edge_count < edges.size(); }
    void note_edge(Edge edge) {
        if (wants_edge()) edges[edge_count++] = edge;
    }
    void note_request(Request record, std::int32_t target_error = 0) {
        record.seq = ++total_requests;
        if (first_count < first.size()) first[first_count++] = record;
        if (first_error_seq) {
            if (after_count < after.size()) after[after_count++] = record;
            return;
        }
        if (record.sdk_entered && record.result != 0 && (!target_error || record.result == target_error)) {
            first_error_seq = record.seq;
            first_error = record;
            before_count = rolling_count;
            const auto earliest = (rolling_next + around - rolling_count) % around;
            for (std::size_t i = 0; i < rolling_count; ++i) before[i] = rolling[(earliest + i) % around];
            return;
        }
        rolling[rolling_next] = record;
        rolling_next = (rolling_next + 1) % around;
        if (rolling_count < around) ++rolling_count;
    }
    static bool rate_abnormal(std::uint32_t edges, std::uint64_t capture_us) {
        // Allow a one-second observation window. 500 Hz is a diagnostic
        // flag for a nominal 100 Hz stream, not an acceptance threshold.
        return capture_us >= 1'000'000 && std::uint64_t{edges} * 1'000'000 > 500 * capture_us;
    }

    std::array<Edge, edge_limit> edges{};
    std::array<Request, first_limit> first{};
    std::array<Request, around> before{}, after{};
    Request first_error{};
    std::size_t edge_count = 0, first_count = 0, before_count = 0, after_count = 0;
    std::uint32_t total_requests = 0, first_error_seq = 0;

private:
    std::array<Request, around> rolling{};
    std::size_t rolling_next = 0, rolling_count = 0;
};

// Observes the existing read after the SDK wrapper and app lock have returned.
// SDK timestamps/status are meaningful only when the corresponding flags are set.
void observe_status_read(Request record);

} // namespace node::drivers::toe_trace

