#pragma once
#include <cstdint>
#include <limits>

namespace node::drivers::timing {
// A relative RTOS wait can lose almost one tick to its starting phase. Round
// the requested minimum duration UP, then add one guard tick. This changes
// software waiting only, not sensor ODR, SCL timing or calibration parameters.
constexpr std::uint32_t guarded_wait_ticks(std::uint32_t minimum_ms, std::uint32_t tick_hz) {
    if (!minimum_ms || !tick_hz) return 0;
    const auto ticks = (static_cast<std::uint64_t>(minimum_ms) * tick_hz + 999) / 1000 + 1;
    return ticks > std::numeric_limits<std::uint32_t>::max() ? 0 : static_cast<std::uint32_t>(ticks);
}
// I2cBus::delay_ms is a minimum-duration startup delay. Preserve its existing
// zero-ms one-tick block; positive durations need the same phase guard as a
// minimum wait. Invalid/unrepresentable inputs retain the zero error sentinel.
constexpr std::uint32_t minimum_delay_ticks(std::uint32_t minimum_ms, std::uint32_t tick_hz) {
    if (!tick_hz) return 0;
    return minimum_ms ? guarded_wait_ticks(minimum_ms, tick_hz) : 1;
}
constexpr std::uint32_t guarded_timeout_ms(std::uint32_t minimum_ms, std::uint32_t tick_hz) {
    if (!minimum_ms || !tick_hz) return 0;
    const auto ticks = guarded_wait_ticks(minimum_ms, tick_hz);
    if (!ticks) return 0; // unrepresentable input; callers must reject zero for a positive budget
    const auto ms = (static_cast<std::uint64_t>(ticks) * 1000 + tick_hz - 1) / tick_hz;
    return ms > std::numeric_limits<std::uint32_t>::max() ? 0 : static_cast<std::uint32_t>(ms);
}
} // namespace node::drivers::timing
