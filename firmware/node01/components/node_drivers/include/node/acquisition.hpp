#pragma once
#include "node/sensors.hpp"

namespace node::sampling {
// Internal diagnostic record, not Telemetry and not the 00 experimental CSV.
// A Soil update occupies its OWN record; it is never duplicated at IMU rate.
enum class RecordKind { Imu, Soil };
struct AcquisitionRecord {
    RecordKind kind = RecordKind::Imu;
    unsigned channel = 0;
    // Boot-local allocation order, NOT sensor time order or formal MessageIdentity.seq.
    std::uint64_t acquisition_index = 0;
    std::uint64_t attempted_uptime_us = 0;
    ImuSample imu{};
    SoilSample soil{};
    std::array<std::int16_t, 6> imu_raw{};
    esp_err_t error = ESP_OK;
};
static_assert(std::is_trivially_copyable_v<AcquisitionRecord>);
}
