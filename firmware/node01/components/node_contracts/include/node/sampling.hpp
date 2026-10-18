#pragma once
#include <array>
#include <cstdint>
#include <optional>
#include <type_traits>

namespace node::sampling {
enum class Validity { Unavailable, Valid, Error };
enum class ImuSite { Top, Toe };
struct ImuSample {
    std::array<float, 3> acceleration_mps2{}; // includes gravity; ignored unless valid
    std::array<float, 3> angular_rate_dps{};
    std::optional<std::uint64_t> acquired_uptime_us{};
    Validity validity = Validity::Unavailable;
};
struct SoilSample {
    std::optional<std::int16_t> raw{};
    std::optional<std::uint64_t> acquired_uptime_us{};
    Validity validity = Validity::Unavailable;
};
struct SensorSnapshot {
    std::array<ImuSample, 2> imu{};
    std::array<SoilSample, 3> soil{};
    // Per-channel time is retained; coherent memory does not imply simultaneous sampling.
};
static_assert(std::is_trivially_copyable_v<SensorSnapshot>);
} // namespace node::sampling
