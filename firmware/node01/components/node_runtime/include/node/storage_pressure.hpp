#pragma once
#include <cstdint>

namespace node::runtime::policy {
// Sampled AFTER a queue operation, not an atomic history of every queue depth.
// The Runtime attaches its current storage operation under the snapshot lock.
struct StorageQueueSample {
    std::uint64_t observed_us = 0, acquisition_index = 0, io_started_us = 0;
    std::uint32_t depth = 0, io_operation = 0;
    bool dropped = false, has_index = false;
};
struct StoragePressureSnapshot {
    std::uint64_t high_entries = 0, recoveries = 0, drops = 0, late_samples = 0;
    std::uint64_t high_total_us = 0, high_max_us = 0, high_since_us = 0, recovered_us = 0;
    std::uint32_t peak = 0;
    bool high = false;
    StorageQueueSample first_high{}, last_high{}, first_drop{}, last_drop{};
};
// Fixed-size observations only: no allocation, I/O, retry, queue mutation or
// logging. Runtime serializes this with its short existing snapshot lock.
class StoragePressure {
public:
    StoragePressure(unsigned high, unsigned low) : high_(high), low_(low) {}
    void observe(const StorageQueueSample& sample) {
        if (sample.depth > state_.peak) state_.peak = sample.depth;
        // A delayed cross-core sample must not reopen an already closed time
        // interval. Retain its real drop/index/peak evidence, skip only its
        // stale high/low transition, and report that decision explicitly.
        if (sample.dropped) {
            if (++state_.drops == 1) state_.first_drop = sample;
            state_.last_drop = sample;
        }
        if (sample.observed_us < last_observed_us_) { ++state_.late_samples; return; }
        last_observed_us_ = sample.observed_us;
        if (!state_.high && sample.depth >= high_) {
            state_.high = true; state_.high_since_us = sample.observed_us;
            if (++state_.high_entries == 1) state_.first_high = sample;
            state_.last_high = sample;
        } else if (state_.high && sample.depth <= low_) {
            const auto elapsed = sample.observed_us >= state_.high_since_us
                ? sample.observed_us - state_.high_since_us : 0;
            state_.high_total_us += elapsed;
            if (elapsed > state_.high_max_us) state_.high_max_us = elapsed;
            state_.high = false; state_.recovered_us = sample.observed_us; ++state_.recoveries;
        }
    }
    void copy_snapshot(StoragePressureSnapshot& copy, std::uint64_t now) const {
        copy = state_;
        if (copy.high && now >= copy.high_since_us) {
            const auto elapsed = now - copy.high_since_us;
            copy.high_total_us += elapsed;
            if (elapsed > copy.high_max_us) copy.high_max_us = elapsed;
        }
    }
    StoragePressureSnapshot snapshot(std::uint64_t now) const {
        StoragePressureSnapshot copy;
        copy_snapshot(copy, now); return copy;
    }
private:
    const unsigned high_, low_;
    StoragePressureSnapshot state_{};
    std::uint64_t last_observed_us_ = 0;
};
} // namespace node::runtime::policy
