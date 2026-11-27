#pragma once
#include "node/logic.hpp"
#include "node/protocol.hpp"
#include <array>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <optional>

static_assert(sizeof(double) == 8, "IEEE-754 binary64 (8-byte double) required");
static_assert(std::numeric_limits<double>::is_iec559, "IEC-559 / IEEE-754 double required");
static_assert(std::numeric_limits<double>::digits == 53, "IEEE-754 binary64 significand required");

namespace node::logic {

// Proposed V1 reason_mask bits matching algorithm/B_revised/hardware_handoff/interface_review_20261125.
// Note: TEST_ONLY configs must NOT populate formal reason_mask bits; bits 5..31 must be zero on TX.
namespace reason_bit {
inline constexpr std::uint32_t tilt_contribution = 1U << 0;
inline constexpr std::uint32_t vibration_contribution = 1U << 1;
inline constexpr std::uint32_t moisture_contribution = 1U << 2;
inline constexpr std::uint32_t growth_contribution = 1U << 3;
inline constexpr std::uint32_t dual_imu_consensus = 1U << 4;
inline constexpr std::uint32_t v1_mask = 0x1FU;
} // namespace reason_bit

namespace math {

struct TimedSample {
    std::int64_t timestamp_ms = 0;
    double value = 0.0;
};

struct CurvePoint {
    double x = 0.0;
    double y = 0.0;
};

struct Curve {
    static constexpr std::size_t max_points = 16;
    std::array<CurvePoint, max_points> points{};
    std::size_t count = 0;
};

// Pure IEEE-754 double (binary64) reference helpers mirroring candidate_features/reference.py & risk_math.py.
std::optional<double> gravity_tilt_change_deg(
    const std::array<double, 3>& current,
    const std::array<double, 3>& reference);

std::optional<double> causal_slope_per_second(const TimedSample* samples, std::size_t count);

std::optional<double> dynamic_accel_rms_mps2(const std::array<double, 3>* samples, std::size_t count);

std::optional<double> relative_wetness_index(double raw, double dry_raw, double wet_raw);

std::optional<double> evaluate_curve(double value, const Curve& curve);

std::optional<double> sensor_score(
    double tilt_c, double vib_c, double moist_c, double growth_c, double consensus_bonus);

// Exact unrounded boundaries: [0,30) NORMAL, [30,60) WATCH, [60,80) WARNING, [80,100] EMERGENCY.
std::optional<protocol::RiskLevel> classify_double(std::optional<double> score);

} // namespace math

enum class ConfigMode { Draft, TestOnly, Calibrated };

enum class MissingPolicy { Unspecified, RequireBothImuAndAllThreeSoilV1 };

enum class ValidationError {
    Ok,
    DraftRejected,
    MissingReviewRefs,
    InvalidReasonBits,
    InvalidWeights,
    InvalidMissingPolicy,
    InvalidCurve,
    InvalidConsensus,
    InvalidCalibration,
    InvalidBaseline,
    InvalidOdr,
    InvalidPolicyConstraint,
    MissingMetadata
};

struct RiskConfig {
    ConfigMode mode = ConfigMode::Draft;
    bool validated_for_runtime = false;
    bool review_a = false;
    bool review_b = false;
    bool review_c = false;
    bool has_config_hash = false;
    bool has_config_version = false;
    bool has_feature_version = false;
    bool has_calibration_version = false;
    bool has_frame_id = false;
    bool has_device_identity = false;
    bool has_sensor_ids = false;
    bool has_reason_mask_version = false;
    bool has_reason_bits = false;
    std::array<std::uint8_t, 5> reason_bits{0, 1, 2, 3, 4};

    std::array<double, 4> weights{0.30, 0.25, 0.25, 0.20};
    double imu_odr_hz = 0.0;
    double soil_odr_hz = 0.0;
    MissingPolicy missing_policy = MissingPolicy::Unspecified;

    struct ImuConfig {
        double gravity_tau_ms = 0.0;
        std::uint32_t warmup_ms = 0;
        std::uint32_t alignment_ms = 0;
        std::array<std::array<double, 3>, 2> baseline_gravity_mps2{};
    } imu{};

    struct SoilProbeCal {
        double dry_raw = 0.0;
        double wet_raw = 0.0;
        double min_span_raw = 0.0;
    };
    struct SoilConfig {
        std::uint32_t alignment_ms = 0;
        std::array<SoilProbeCal, 3> calibration{};
    } soil{};

    struct WindowSpec {
        std::uint32_t lookback_ms = 0;
        std::uint32_t max_gap_ms = 0;
        std::uint32_t max_age_ms = 0;
        std::uint32_t min_samples = 0;
        std::uint32_t min_span_ms = 0;
    };
    struct WindowsConfig {
        WindowSpec tilt{};
        WindowSpec vibration{};
        WindowSpec soil_growth{};
    } windows{};

    struct CurvesConfig {
        math::Curve tilt{};
        math::Curve vibration{};
        math::Curve moisture{};
        math::Curve growth{};
    } curves{};

    struct ConsensusConfig {
        double tilt_threshold_deg = 0.0;
        double max_tilt_difference_deg = 0.0;
        double bonus = 5.0;
    } consensus{};

    std::uint64_t config_hash_tag = 0;
};

ValidationError validate_risk_config(const RiskConfig& config);

struct FeatureInputs {
    std::array<std::optional<double>, 2> imu_tilt_deg{};
    std::array<std::optional<double>, 2> imu_vibration_rms{};
    std::array<std::optional<double>, 3> soil_moisture_pct{};
    std::optional<double> soil_growth_pct_min{};
};

struct RiskEvalResult {
    bool valid = false;
    std::optional<double> score{};
    std::optional<protocol::RiskLevel> level{};
    std::optional<std::uint32_t> reason_mask{};
    risk_runtime::Calibration calibration = risk_runtime::Calibration::NotReady;
    risk_runtime::Fault fault = risk_runtime::Fault::Uncalibrated;
    std::array<std::optional<double>, 4> contributions{};
    std::optional<double> consensus_bonus{};

    risk_runtime::Snapshot to_runtime_snapshot() const;
};

class RiskEngine {
public:
    bool configured() const { return configured_; }
    ValidationError load_config(const RiskConfig& config);
    const RiskConfig& active_config() const { return config_; }
    RiskEvalResult evaluate(const FeatureInputs& inputs) const;

private:
    bool configured_ = false;
    RiskConfig config_{};
};

// Five-state local alarm latch policy and state machine matching B's V0.1 proposal.
enum class AlarmMode {
    Unarmed,
    Armed,
    ActiveLatched,
    AckedLatched,
    RecoveryPending
};

struct AlarmPolicy {
    ConfigMode mode = ConfigMode::Draft;
    bool validated_for_runtime = false;
    bool review_a = false;
    bool review_b = false;
    bool review_c = false;
    bool has_alarm_policy_version = false;
    bool has_risk_config_hash = false;
    bool has_reason_mask_version = false;
    bool has_hardware_profile = false;
    bool has_device_identity = false;

    std::uint32_t entry_dwell_ms = 0;
    double clear_score_exclusive = 0.0;
    std::uint32_t clear_dwell_ms = 0;
    std::uint32_t max_valid_result_age_ms = 0;

    bool auto_clear = false;
    bool clear_requires_ack = true;
    bool persist_latch = true;
    bool unknown_keeps_latch = true;

    std::uint64_t risk_config_tag = 0;
    std::uint64_t alarm_policy_tag = 0;
};

ValidationError validate_alarm_policy(const AlarmPolicy& policy);

enum class PersistStatus {
    EmptyFirstBoot,
    ValidRestored,
    CorruptFault
};

struct PersistedLatch {
    static constexpr std::size_t encoded_bytes = 64;
    bool latched = false;
    bool acked = false;
    protocol::RiskLevel highest_level = protocol::RiskLevel::Warning;
    std::uint32_t trigger_reason_mask = 0;
    std::uint32_t latest_reason_mask = 0;
    std::uint64_t trigger_boot_id = 0;
    std::uint64_t trigger_seq = 0;
    std::uint64_t trigger_uptime_ms = 0;
    std::uint64_t risk_config_tag = 0;
    std::uint64_t alarm_policy_tag = 0;
    std::uint64_t ack_uptime_ms = 0;
};

std::uint32_t crc32_ieee(const std::uint8_t* data, std::size_t size);
bool encode_persisted_latch(const PersistedLatch& latch, std::array<std::uint8_t, PersistedLatch::encoded_bytes>& out);
PersistStatus decode_persisted_latch(const std::uint8_t* data, std::size_t size, PersistedLatch& out);

struct AlarmObservation {
    std::uint64_t observation_seq = 0;
    std::uint64_t sample_uptime_ms = 0;
    std::uint64_t boot_id = 0;
    bool calibrated = false;
    bool warmup_complete = false;
    bool is_replay = false;
    std::optional<double> sensor_score{};
    std::optional<protocol::RiskLevel> level{};
    std::optional<std::uint32_t> reason_mask{};
};

struct AlarmState {
    AlarmMode mode = AlarmMode::Unarmed;
    bool policy_loaded = false;
    bool input_fault = true;
    bool persistence_fault = false;
    bool acked = false;
    bool buzzer_on = false;
    bool led_on = false;

    std::optional<protocol::RiskLevel> highest_level{};
    std::optional<protocol::RiskLevel> trigger_level{};
    std::optional<std::uint32_t> trigger_reason_mask{};
    std::optional<std::uint32_t> latest_reason_mask{};
    std::uint64_t trigger_boot_id = 0;
    std::uint64_t trigger_seq = 0;
    std::uint64_t trigger_uptime_ms = 0;
    std::uint64_t ack_uptime_ms = 0;

    bool latched() const {
        return mode == AlarmMode::ActiveLatched ||
               mode == AlarmMode::AckedLatched ||
               mode == AlarmMode::RecoveryPending;
    }
    bool safe_to_ignore() const {
        return mode == AlarmMode::Armed && !persistence_fault && !input_fault && !latched();
    }
};

class AlarmStateMachine {
public:
    PersistStatus restore_persisted(const std::uint8_t* data, std::size_t size);
    ValidationError load_policy(const AlarmPolicy& policy, bool warmup_complete = false);
    void step(std::uint64_t now_ms, const AlarmObservation& obs);

    bool local_ack(std::uint64_t now_ms);
    bool local_clear(std::uint64_t now_ms);
    bool remote_ack() { return false; }   // Forbidden in V1
    bool remote_clear() { return false; } // Forbidden in V1

    PersistedLatch export_persisted() const;
    const AlarmState& state() const { return state_; }

private:
    void break_continuous_timers();
    bool check_valid_live_observation(std::uint64_t now_ms, const AlarmObservation& obs);

    bool has_policy_ = false;
    AlarmPolicy policy_{};
    AlarmState state_{};

    bool has_last_obs_ = false;
    std::uint64_t last_obs_seq_ = 0;
    std::uint64_t last_obs_sample_ms_ = 0;
    std::uint64_t last_step_now_ms_ = 0;

    bool entry_timer_active_ = false;
    std::uint64_t entry_since_ms_ = 0;
    bool clear_timer_active_ = false;
    std::uint64_t clear_since_ms_ = 0;
};

// Fixed-capacity causal observation buffer mirroring candidate_features/causal_window.py.
// Zero dynamic allocation; reset on non-monotonic time or gaps > max_gap_ms.
template<std::size_t Capacity>
class CausalBuffer {
public:
    static_assert(Capacity >= 2, "CausalBuffer capacity must be >= 2");

    void clear() {
        head_ = 0;
        count_ = 0;
    }

    void reset_all() {
        clear();
        has_last_ = false;
        last_uptime_ms_ = 0;
    }

    void add(std::int64_t uptime_ms,
             std::optional<double> value,
             bool valid,
             std::uint32_t lookback_ms,
             std::uint32_t max_gap_ms);

    bool slice(std::int64_t end_uptime_ms,
               std::uint32_t lookback_ms,
               std::uint32_t max_gap_ms,
               std::uint32_t max_age_ms,
               std::uint32_t min_samples,
               std::uint32_t min_span_ms,
               math::TimedSample* out,
               std::size_t out_capacity,
               std::size_t& out_count) const;

private:
    struct Entry {
        std::int64_t uptime_ms = 0;
        double value = 0.0;
        bool valid = false;
    };
    std::array<Entry, Capacity> entries_{};
    std::size_t head_ = 0;
    std::size_t count_ = 0;
    bool has_last_ = false;
    std::int64_t last_uptime_ms_ = 0;
};

struct ImuFeatureProjection {
    std::optional<double> tilt_deg{};
    std::optional<double> tilt_rate_dps{};
    std::optional<double> vibration_rms{};
};

struct SoilFeatureProjection {
    std::optional<double> top_pct{};
    std::optional<double> middle_pct{};
    std::optional<double> toe_pct{};
    std::optional<double> avg_pct{};
    std::optional<double> growth_pct_min{};
};

struct PipelineProjection {
    std::array<ImuFeatureProjection, 2> imu{};
    SoilFeatureProjection soil{};
    std::optional<double> dual_imu_tilt_difference_deg{};
    RiskEvalResult risk{};
};

struct SoilRawObs {
    std::int64_t uptime_ms = 0;
    bool valid = false;
    std::int16_t raw = 0;
};

// Full causal feature + risk evaluation pipeline mirroring telemetry_v2_intake/runtime.py.
// Note: contains fixed CausalBuffer<512> instances (~56 KiB total); allocate static/member rather
// than on small FreeRTOS task stacks.
class FeaturePipeline {
public:
    ValidationError reset(const RiskConfig& config);
    bool configured() const { return configured_; }

    bool ingest_imu(unsigned site,
                    std::int64_t uptime_ms,
                    bool valid,
                    const std::array<double, 3>& accel_mps2);

    bool ingest_soil_group(std::int64_t group_uptime_ms,
                           const std::array<std::optional<SoilRawObs>, 3>& updates);

    PipelineProjection evaluate_at(std::int64_t end_uptime_ms) const;

private:
    enum class SoilProbeStatus { Missing, InvalidObs, StaleOrFuture, Valid, CalRangeExceeded };

    void eval_soil_at(std::int64_t end_uptime_ms,
                      std::array<std::optional<double>, 3>& out_values,
                      std::array<SoilProbeStatus, 3>& out_status,
                      std::optional<double>& out_avg) const;

    struct ImuChannelState {
        bool has_last = false;
        std::int64_t last_uptime_ms = 0;
        bool last_valid = false;
        std::array<double, 3> last_accel{};

        bool has_gravity = false;
        std::array<double, 3> gravity{};
        bool has_start = false;
        std::int64_t start_ms = 0;

        CausalBuffer<512> tilt_buf{};
        CausalBuffer<512> energy_buf{};
    };

    bool configured_ = false;
    RiskConfig config_{};
    RiskEngine risk_engine_{};

    std::array<ImuChannelState, 2> imu_{};
    std::array<bool, 3> soil_present_{};
    std::array<SoilRawObs, 3> soil_{};
    bool has_last_soil_tuple_ = false;
    std::array<std::int64_t, 3> last_soil_tuple_{};
    CausalBuffer<64> soil_growth_buf_{};
    mutable std::array<math::TimedSample, 512> scratch_{};
};

// Single-press GPIO21 anti-misoperation gesture FSM matching REVIEW_ADDENDUM_20261126.md:
// - Held at boot suppressed until released.
// - Short press fires Ack ONLY on release if < clear_hold_ms.
// - Long press >= clear_hold_ms fires Clear ONLY if press started while recovery_ready_and_acked
//   and recovery stayed uninterrupted for the full hold duration; release never fires Ack after hold.
enum class ButtonEvent { None, Ack, Clear };

struct ButtonGestureConfig {
    std::uint32_t debounce_ms = 30;
    std::uint32_t clear_hold_ms = 3000;
};

class LocalButtonGesture {
public:
    explicit LocalButtonGesture(ButtonGestureConfig config = {}) : config_(config) {}

    ButtonEvent update(std::uint64_t now_ms, bool raw_pressed, bool recovery_ready_and_acked);
    bool pressed() const { return debounced_pressed_; }

private:
    ButtonGestureConfig config_{};
    bool initialized_ = false;
    std::uint64_t last_now_ms_ = 0;
    bool last_raw_ = false;
    std::uint64_t raw_since_ms_ = 0;
    bool debounced_pressed_ = false;
    bool boot_suppress_until_release_ = false;
    std::uint64_t press_start_ms_ = 0;
    bool clear_eligible_for_this_press_ = false;
    bool press_consumed_by_clear_ = false;
};

} // namespace node::logic
