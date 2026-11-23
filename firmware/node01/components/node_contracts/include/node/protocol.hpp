#pragma once
#include <array>
#include <cstddef>
#include <cstdint>
#include <optional>
#include <string_view>

static_assert(__cplusplus == 201703L, "Application must build as C++17");
namespace node::protocol {
inline constexpr char schema[] = "zhifang.telemetry.v2";
// All widths below are in-memory implementation types, NOT a frozen wire layout.
using Integer = std::uint64_t;
inline constexpr Integer json_safe_integer_max = 9007199254740991ULL;
enum class RiskLevel { Normal, Watch, Warning, Emergency };
std::optional<RiskLevel> classify(std::optional<float> score);
struct Risk {
    std::optional<float> sensor_score{};
    std::optional<RiskLevel> level{};
    std::optional<Integer> reason_mask{}; // TBD-12: no bit numbers invented.
};
struct Imu {
    std::string_view id{}; // immutable lifetime; do not queue borrowed strings
    std::optional<float> ax{}, ay{}, az{}, gx{}, gy{}, gz{};
    std::optional<float> tilt_deg{}, tilt_rate_dps{}, vibration_rms{};
    bool valid = false;
};
struct Soil {
    std::optional<std::int16_t> top_raw{}, middle_raw{}, toe_raw{};
    std::optional<float> top_pct{}, middle_pct{}, toe_pct{}, avg_pct{}, growth_pct_min{};
};
struct Experiment {
    std::optional<std::string_view> run_id{};
    std::optional<unsigned> rain_level{};
};
struct System {
    bool wifi_up = false, mqtt_up = false, lora_ready = false, sd_ok = false;
    bool edge_online = false, sensor_degraded = true;
};
struct MessageIdentity {
    std::string_view device_id{};
    Integer boot_id = 0, seq = 0;
};
// Only a future durable allocator may supply identity. A draft is not a message.
// Missing boot allocation must block output without stopping local Risk/Alarm.
struct TelemetryDraft {
    std::string_view schema_name = schema;
    std::string_view site_id{};
    std::optional<MessageIdentity> identity{};
    std::optional<Integer> timestamp_ms{};
    Integer uptime_ms = 0;
    bool time_synced = false;
    std::array<Imu, 2> imu{Imu{"top"}, Imu{"toe"}};
    Soil soil{};
    Experiment experiment{};
    Risk risk{};
    System system{};
};
enum class SerializeStatus { NotImplemented, InvalidDraft, BufferTooSmall, Encoded };
struct SerializeResult { SerializeStatus status; std::size_t bytes_written; };
class TelemetrySerializer {
public:
    virtual ~TelemetrySerializer() = default;
    // Must emit all v2 fields, null invalid observations, reject NaN/Inf,
    // validate identity/time/risk; no heap-growing output buffer.
    virtual SerializeResult encode(const TelemetryDraft&, char*, std::size_t) = 0;
};
class IdentityAllocator {
public:
    virtual ~IdentityAllocator() = default;
    // Commit non-repeating boot allocation before issuing any original record.
    // One sequence across record types; retry/forward preserves original ID.
    virtual std::optional<MessageIdentity> next_original() = 0;
};
} // namespace node::protocol
