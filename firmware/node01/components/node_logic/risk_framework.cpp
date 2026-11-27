#include "node/risk_framework.hpp"
#include <algorithm>
#include <cmath>

namespace node::logic {
namespace {

inline constexpr double kPi = 3.14159265358979323846;
inline constexpr std::array<double, 4> kFrozenWeights{0.30, 0.25, 0.25, 0.20};
inline constexpr std::array<std::uint8_t, 4> kLatchMagic{'Z', 'H', 'A', 'L'};
inline constexpr std::uint8_t kLatchFormatVersion = 1;

bool finite(double v) { return std::isfinite(v); }

bool finite_vec3(const std::array<double, 3>& v) {
    return finite(v[0]) && finite(v[1]) && finite(v[2]);
}

bool valid_window(const RiskConfig::WindowSpec& w) {
    return w.lookback_ms >= 1U &&
           w.max_gap_ms >= 1U &&
           w.min_samples >= 2U &&
           w.min_span_ms >= 1U &&
           w.min_span_ms <= w.lookback_ms;
}

bool valid_curve(const math::Curve& c) {
    if (c.count < 2 || c.count > math::Curve::max_points) return false;
    for (std::size_t i = 0; i < c.count; ++i) {
        const double x = c.points[i].x;
        const double y = c.points[i].y;
        if (!finite(x) || !finite(y) || y < 0.0 || y > 100.0) return false;
        if (i > 0) {
            const double prev_x = c.points[i - 1].x;
            const double prev_y = c.points[i - 1].y;
            if (x <= prev_x || y < prev_y || !finite(x - prev_x)) return false;
        }
    }
    return true;
}

void write_u32_le(std::uint8_t* dst, std::uint32_t v) {
    dst[0] = static_cast<std::uint8_t>(v & 0xFFU);
    dst[1] = static_cast<std::uint8_t>((v >> 8) & 0xFFU);
    dst[2] = static_cast<std::uint8_t>((v >> 16) & 0xFFU);
    dst[3] = static_cast<std::uint8_t>((v >> 24) & 0xFFU);
}

void write_u64_le(std::uint8_t* dst, std::uint64_t v) {
    for (unsigned i = 0; i < 8; ++i) {
        dst[i] = static_cast<std::uint8_t>((v >> (8U * i)) & 0xFFU);
    }
}

std::uint32_t read_u32_le(const std::uint8_t* src) {
    return static_cast<std::uint32_t>(src[0]) |
           (static_cast<std::uint32_t>(src[1]) << 8) |
           (static_cast<std::uint32_t>(src[2]) << 16) |
           (static_cast<std::uint32_t>(src[3]) << 24);
}

std::uint64_t read_u64_le(const std::uint8_t* src) {
    std::uint64_t v = 0;
    for (unsigned i = 0; i < 8; ++i) {
        v |= static_cast<std::uint64_t>(src[i]) << (8U * i);
    }
    return v;
}

} // namespace

namespace math {

std::optional<double> gravity_tilt_change_deg(
    const std::array<double, 3>& current,
    const std::array<double, 3>& reference) {
    if (!finite_vec3(current) || !finite_vec3(reference)) return std::nullopt;
    const double n_cur2 = current[0] * current[0] + current[1] * current[1] + current[2] * current[2];
    const double n_ref2 = reference[0] * reference[0] + reference[1] * reference[1] + reference[2] * reference[2];
    if (!finite(n_cur2) || !finite(n_ref2) || n_cur2 <= 0.0 || n_ref2 <= 0.0) return std::nullopt;
    const double norm_cur = std::sqrt(n_cur2);
    const double norm_ref = std::sqrt(n_ref2);
    if (norm_cur == 0.0 || norm_ref == 0.0) return std::nullopt;
    const double dot = current[0] * reference[0] + current[1] * reference[1] + current[2] * reference[2];
    const double raw_cos = dot / (norm_cur * norm_ref);
    if (!finite(raw_cos)) return std::nullopt;
    const double clamped = std::max(-1.0, std::min(1.0, raw_cos));
    return std::acos(clamped) * (180.0 / kPi);
}

std::optional<double> causal_slope_per_second(const TimedSample* samples, std::size_t count) {
    if (!samples || count < 2) return std::nullopt;
    for (std::size_t i = 0; i < count; ++i) {
        if (!finite(samples[i].value)) return std::nullopt;
        if (i > 0 && samples[i].timestamp_ms <= samples[i - 1].timestamp_ms) return std::nullopt;
    }
    const std::uint64_t start_u = static_cast<std::uint64_t>(samples[0].timestamp_ms);
    double sum_t = 0.0;
    double sum_v = 0.0;
    for (std::size_t i = 0; i < count; ++i) {
        const std::uint64_t dt_ms = static_cast<std::uint64_t>(samples[i].timestamp_ms) - start_u;
        const double t_sec = static_cast<double>(dt_ms) / 1000.0;
        sum_t += t_sec;
        sum_v += samples[i].value;
    }
    const double n = static_cast<double>(count);
    const double mean_t = sum_t / n;
    const double mean_v = sum_v / n;
    double numerator = 0.0;
    double denominator = 0.0;
    for (std::size_t i = 0; i < count; ++i) {
        const std::uint64_t dt_ms = static_cast<std::uint64_t>(samples[i].timestamp_ms) - start_u;
        const double t_sec = static_cast<double>(dt_ms) / 1000.0;
        const double dt = t_sec - mean_t;
        const double dv = samples[i].value - mean_v;
        numerator += dt * dv;
        denominator += dt * dt;
    }
    if (!finite(numerator) || !finite(denominator) || denominator <= 0.0) return std::nullopt;
    const double slope = numerator / denominator;
    return finite(slope) ? std::optional<double>{slope} : std::nullopt;
}

std::optional<double> dynamic_accel_rms_mps2(const std::array<double, 3>* samples, std::size_t count) {
    if (!samples || count == 0) return std::nullopt;
    double sum_sq = 0.0;
    for (std::size_t i = 0; i < count; ++i) {
        if (!finite_vec3(samples[i])) return std::nullopt;
        sum_sq += samples[i][0] * samples[i][0] +
                  samples[i][1] * samples[i][1] +
                  samples[i][2] * samples[i][2];
    }
    if (!finite(sum_sq)) return std::nullopt;
    return std::sqrt(sum_sq / static_cast<double>(count));
}

std::optional<double> relative_wetness_index(double raw, double dry_raw, double wet_raw) {
    if (!finite(raw) || !finite(dry_raw) || !finite(wet_raw)) return std::nullopt;
    const double span = wet_raw - dry_raw;
    if (!finite(span) || span == 0.0) return std::nullopt;
    const double idx = (raw - dry_raw) / span;
    return finite(idx) ? std::optional<double>{idx} : std::nullopt;
}

std::optional<double> evaluate_curve(double value, const Curve& curve) {
    if (!finite(value) || !valid_curve(curve)) return std::nullopt;
    if (value <= curve.points[0].x) return curve.points[0].y;
    for (std::size_t i = 1; i < curve.count; ++i) {
        const double x0 = curve.points[i - 1].x;
        const double y0 = curve.points[i - 1].y;
        const double x1 = curve.points[i].x;
        const double y1 = curve.points[i].y;
        if (value <= x1) {
            return y0 + (y1 - y0) * (value - x0) / (x1 - x0);
        }
    }
    return curve.points[curve.count - 1].y;
}

std::optional<double> sensor_score(
    double tilt_c, double vib_c, double moist_c, double growth_c, double consensus_bonus) {
    const std::array<double, 4> c{tilt_c, vib_c, moist_c, growth_c};
    for (double v : c) {
        if (!finite(v) || v < 0.0 || v > 100.0) return std::nullopt;
    }
    if (!finite(consensus_bonus) || (consensus_bonus != 0.0 && consensus_bonus != 5.0)) {
        return std::nullopt;
    }
    double total = 0.0;
    for (std::size_t i = 0; i < 4; ++i) {
        total += kFrozenWeights[i] * c[i];
    }
    total += consensus_bonus;
    if (!finite(total)) return std::nullopt;
    return std::max(0.0, std::min(100.0, total));
}

std::optional<protocol::RiskLevel> classify_double(std::optional<double> score) {
    if (!score || !finite(*score) || *score < 0.0 || *score > 100.0) return std::nullopt;
    if (*score < 30.0) return protocol::RiskLevel::Normal;
    if (*score < 60.0) return protocol::RiskLevel::Watch;
    if (*score < 80.0) return protocol::RiskLevel::Warning;
    return protocol::RiskLevel::Emergency;
}

} // namespace math

ValidationError validate_risk_config(const RiskConfig& c) {
    if (c.mode == ConfigMode::Draft) return ValidationError::DraftRejected;

    if (!c.has_config_version || !c.has_feature_version || !c.has_calibration_version ||
        !c.has_frame_id || !c.has_device_identity || !c.has_sensor_ids) {
        return ValidationError::MissingMetadata;
    }

    if (c.mode == ConfigMode::Calibrated) {
        if (!c.validated_for_runtime || !c.review_a || !c.review_b || !c.review_c) {
            return ValidationError::MissingReviewRefs;
        }
        if (!c.has_config_hash) return ValidationError::MissingMetadata;
        if (!c.has_reason_mask_version || !c.has_reason_bits) return ValidationError::InvalidReasonBits;
        std::uint32_t used_mask = 0;
        for (std::uint8_t bit : c.reason_bits) {
            if (bit > 31U) return ValidationError::InvalidReasonBits;
            const std::uint32_t flag = 1U << bit;
            if (used_mask & flag) return ValidationError::InvalidReasonBits;
            used_mask |= flag;
        }
    } else {
        if (c.validated_for_runtime) return ValidationError::InvalidPolicyConstraint;
        if (c.has_reason_mask_version || c.has_reason_bits) return ValidationError::InvalidReasonBits;
    }

    for (std::size_t i = 0; i < 4; ++i) {
        if (!finite(c.weights[i]) || c.weights[i] != kFrozenWeights[i]) {
            return ValidationError::InvalidWeights;
        }
    }

    if (c.missing_policy != MissingPolicy::RequireBothImuAndAllThreeSoilV1) {
        return ValidationError::InvalidMissingPolicy;
    }

    if (!finite(c.imu_odr_hz) || c.imu_odr_hz < 0.001 ||
        !finite(c.soil_odr_hz) || c.soil_odr_hz < 0.001) {
        return ValidationError::InvalidOdr;
    }

    if (!finite(c.imu.gravity_tau_ms) || c.imu.gravity_tau_ms < 0.001 || c.imu.warmup_ms < 1U) {
        return ValidationError::InvalidBaseline;
    }
    for (const auto& vec : c.imu.baseline_gravity_mps2) {
        if (!finite_vec3(vec)) return ValidationError::InvalidBaseline;
        const double norm2 = vec[0] * vec[0] + vec[1] * vec[1] + vec[2] * vec[2];
        if (!finite(norm2) || norm2 <= 0.0) return ValidationError::InvalidBaseline;
    }

    for (const auto& probe : c.soil.calibration) {
        if (!finite(probe.dry_raw) || !finite(probe.wet_raw) ||
            !finite(probe.min_span_raw) || probe.min_span_raw < 0.001) {
            return ValidationError::InvalidCalibration;
        }
        const double span = probe.wet_raw - probe.dry_raw;
        if (!finite(span) || std::abs(span) < probe.min_span_raw) {
            return ValidationError::InvalidCalibration;
        }
    }

    if (!valid_window(c.windows.tilt) ||
        !valid_window(c.windows.vibration) ||
        !valid_window(c.windows.soil_growth)) {
        return ValidationError::InvalidPolicyConstraint;
    }

    if (!valid_curve(c.curves.tilt) ||
        !valid_curve(c.curves.vibration) ||
        !valid_curve(c.curves.moisture) ||
        !valid_curve(c.curves.growth)) {
        return ValidationError::InvalidCurve;
    }

    if (!finite(c.consensus.tilt_threshold_deg) || c.consensus.tilt_threshold_deg < 0.0 ||
        !finite(c.consensus.max_tilt_difference_deg) || c.consensus.max_tilt_difference_deg < 0.0 ||
        !finite(c.consensus.bonus) || (c.consensus.bonus != 0.0 && c.consensus.bonus != 5.0)) {
        return ValidationError::InvalidConsensus;
    }

    return ValidationError::Ok;
}

risk_runtime::Snapshot RiskEvalResult::to_runtime_snapshot() const {
    risk_runtime::Snapshot out{};
    out.calibration = calibration;
    out.fault = fault;
    if (valid && score && level) {
        out.risk.sensor_score = static_cast<float>(*score);
        out.risk.level = level;
        if (reason_mask) {
            out.risk.reason_mask = static_cast<protocol::Integer>(*reason_mask);
        }
    }
    return out;
}

ValidationError RiskEngine::load_config(const RiskConfig& config) {
    const auto err = validate_risk_config(config);
    if (err != ValidationError::Ok) return err;
    config_ = config;
    configured_ = true;
    return ValidationError::Ok;
}

RiskEvalResult RiskEngine::evaluate(const FeatureInputs& inputs) const {
    RiskEvalResult out{};
    if (!configured_) {
        out.calibration = risk_runtime::Calibration::NotReady;
        out.fault = risk_runtime::Fault::Uncalibrated;
        return out;
    }
    out.calibration = risk_runtime::Calibration::Ready;

    for (unsigned k = 0; k < 2; ++k) {
        if (!inputs.imu_tilt_deg[k] || !finite(*inputs.imu_tilt_deg[k]) ||
            !inputs.imu_vibration_rms[k] || !finite(*inputs.imu_vibration_rms[k])) {
            out.fault = risk_runtime::Fault::InputUnavailable;
            return out;
        }
    }
    for (unsigned k = 0; k < 3; ++k) {
        if (!inputs.soil_moisture_pct[k] || !finite(*inputs.soil_moisture_pct[k])) {
            out.fault = risk_runtime::Fault::InputUnavailable;
            return out;
        }
    }
    if (!inputs.soil_growth_pct_min || !finite(*inputs.soil_growth_pct_min)) {
        out.fault = risk_runtime::Fault::InputUnavailable;
        return out;
    }

    const double tilt = std::max(*inputs.imu_tilt_deg[0], *inputs.imu_tilt_deg[1]);
    const double vib = std::max(*inputs.imu_vibration_rms[0], *inputs.imu_vibration_rms[1]);
    const double moist = (*inputs.soil_moisture_pct[0] +
                          *inputs.soil_moisture_pct[1] +
                          *inputs.soil_moisture_pct[2]) / 3.0;
    const double growth = std::max(0.0, *inputs.soil_growth_pct_min);

    const auto c_tilt = math::evaluate_curve(tilt, config_.curves.tilt);
    const auto c_vib = math::evaluate_curve(vib, config_.curves.vibration);
    const auto c_moist = math::evaluate_curve(moist, config_.curves.moisture);
    const auto c_growth = math::evaluate_curve(growth, config_.curves.growth);
    if (!c_tilt || !c_vib || !c_moist || !c_growth) {
        out.fault = risk_runtime::Fault::InputUnavailable;
        return out;
    }

    const double min_tilt = std::min(*inputs.imu_tilt_deg[0], *inputs.imu_tilt_deg[1]);
    const double diff_tilt = std::abs(*inputs.imu_tilt_deg[0] - *inputs.imu_tilt_deg[1]);
    const bool consensus_hit = (min_tilt >= config_.consensus.tilt_threshold_deg) &&
                               (diff_tilt <= config_.consensus.max_tilt_difference_deg);
    const double bonus = consensus_hit ? config_.consensus.bonus : 0.0;

    const auto score = math::sensor_score(*c_tilt, *c_vib, *c_moist, *c_growth, bonus);
    const auto level = math::classify_double(score);
    if (!score || !level) {
        out.fault = risk_runtime::Fault::InputUnavailable;
        return out;
    }

    out.valid = true;
    out.score = score;
    out.level = level;
    out.contributions = {c_tilt, c_vib, c_moist, c_growth};
    out.consensus_bonus = bonus;
    out.fault = risk_runtime::Fault::None;

    if (config_.mode == ConfigMode::Calibrated) {
        std::uint32_t mask = 0;
        if (*c_tilt > 0.0) mask |= (1U << config_.reason_bits[0]);
        if (*c_vib > 0.0) mask |= (1U << config_.reason_bits[1]);
        if (*c_moist > 0.0) mask |= (1U << config_.reason_bits[2]);
        if (*c_growth > 0.0) mask |= (1U << config_.reason_bits[3]);
        if (bonus == 5.0) mask |= (1U << config_.reason_bits[4]);
        out.reason_mask = mask & reason_bit::v1_mask;
    }
    return out;
}

ValidationError validate_alarm_policy(const AlarmPolicy& p) {
    if (p.mode == ConfigMode::Draft) return ValidationError::DraftRejected;

    if (p.unknown_keeps_latch != true ||
        p.auto_clear != false ||
        p.clear_requires_ack != true) {
        return ValidationError::InvalidPolicyConstraint;
    }
    if (p.entry_dwell_ms == 0U || p.clear_dwell_ms == 0U || p.max_valid_result_age_ms == 0U) {
        return ValidationError::InvalidPolicyConstraint;
    }
    if (!finite(p.clear_score_exclusive) ||
        p.clear_score_exclusive < 0.0 ||
        p.clear_score_exclusive >= 60.0) {
        return ValidationError::InvalidPolicyConstraint;
    }

    if (p.mode == ConfigMode::Calibrated) {
        if (!p.validated_for_runtime || !p.review_a || !p.review_b || !p.review_c) {
            return ValidationError::MissingReviewRefs;
        }
        if (!p.has_alarm_policy_version || !p.has_risk_config_hash ||
            !p.has_reason_mask_version || !p.has_hardware_profile || !p.has_device_identity) {
            return ValidationError::MissingMetadata;
        }
    } else {
        if (p.validated_for_runtime) return ValidationError::InvalidPolicyConstraint;
    }
    return ValidationError::Ok;
}

std::uint32_t crc32_ieee(const std::uint8_t* data, std::size_t size) {
    std::uint32_t crc = 0xFFFFFFFFU;
    for (std::size_t i = 0; i < size; ++i) {
        crc ^= data[i];
        for (int b = 0; b < 8; ++b) {
            crc = (crc & 1U) ? ((crc >> 1) ^ 0xEDB88320U) : (crc >> 1);
        }
    }
    return crc ^ 0xFFFFFFFFU;
}

bool encode_persisted_latch(
    const PersistedLatch& latch,
    std::array<std::uint8_t, PersistedLatch::encoded_bytes>& out) {
    if (latch.acked && !latch.latched) return false;
    if (latch.highest_level != protocol::RiskLevel::Warning &&
        latch.highest_level != protocol::RiskLevel::Emergency) {
        return false;
    }
    out.fill(0);
    for (std::size_t i = 0; i < 4; ++i) out[i] = kLatchMagic[i];
    out[4] = kLatchFormatVersion;
    out[5] = static_cast<std::uint8_t>((latch.latched ? 0x01U : 0x00U) |
                                       (latch.acked ? 0x02U : 0x00U));
    out[6] = static_cast<std::uint8_t>(latch.highest_level);
    out[7] = 0; // reserved
    write_u32_le(&out[8], latch.trigger_reason_mask);
    write_u32_le(&out[12], latch.latest_reason_mask);
    write_u64_le(&out[16], latch.trigger_boot_id);
    write_u64_le(&out[24], latch.trigger_seq);
    write_u64_le(&out[32], latch.trigger_uptime_ms);
    write_u64_le(&out[40], latch.risk_config_tag);
    write_u64_le(&out[48], latch.alarm_policy_tag);
    // Reserve bytes [56..59] for optional checksumed ack timestamp modulo/low bits? Better keep ack_uptime_ms zeroed or fit cleanly!
    // Wait: encoded_bytes is 64; bytes [56..59] reserved/zero, bytes [60..63] = CRC32.
    write_u32_le(&out[56], static_cast<std::uint32_t>(latch.ack_uptime_ms & 0xFFFFFFFFULL));
    const std::uint32_t crc = crc32_ieee(out.data(), PersistedLatch::encoded_bytes - 4);
    write_u32_le(&out[PersistedLatch::encoded_bytes - 4], crc);
    return true;
}

PersistStatus decode_persisted_latch(const std::uint8_t* data, std::size_t size, PersistedLatch& out) {
    if (size == 0U && data == nullptr) return PersistStatus::EmptyFirstBoot;
    if (size == 0U) return PersistStatus::EmptyFirstBoot;
    if (!data || size != PersistedLatch::encoded_bytes) return PersistStatus::CorruptFault;

    for (std::size_t i = 0; i < 4; ++i) {
        if (data[i] != kLatchMagic[i]) return PersistStatus::CorruptFault;
    }
    if (data[4] != kLatchFormatVersion || data[7] != 0) return PersistStatus::CorruptFault;

    const std::uint32_t expected_crc = crc32_ieee(data, PersistedLatch::encoded_bytes - 4);
    const std::uint32_t stored_crc = read_u32_le(&data[PersistedLatch::encoded_bytes - 4]);
    if (expected_crc != stored_crc) return PersistStatus::CorruptFault;

    const std::uint8_t flags = data[5];
    if ((flags & ~0x03U) != 0U) return PersistStatus::CorruptFault;
    const bool latched = (flags & 0x01U) != 0U;
    const bool acked = (flags & 0x02U) != 0U;
    if (acked && !latched) return PersistStatus::CorruptFault;

    const std::uint8_t level_raw = data[6];
    if (level_raw != static_cast<std::uint8_t>(protocol::RiskLevel::Warning) &&
        level_raw != static_cast<std::uint8_t>(protocol::RiskLevel::Emergency)) {
        return PersistStatus::CorruptFault;
    }

    out.latched = latched;
    out.acked = acked;
    out.highest_level = static_cast<protocol::RiskLevel>(level_raw);
    out.trigger_reason_mask = read_u32_le(&data[8]);
    out.latest_reason_mask = read_u32_le(&data[12]);
    out.trigger_boot_id = read_u64_le(&data[16]);
    out.trigger_seq = read_u64_le(&data[24]);
    out.trigger_uptime_ms = read_u64_le(&data[32]);
    out.risk_config_tag = read_u64_le(&data[40]);
    out.alarm_policy_tag = read_u64_le(&data[48]);
    out.ack_uptime_ms = static_cast<std::uint64_t>(read_u32_le(&data[56]));
    return PersistStatus::ValidRestored;
}

void AlarmStateMachine::break_continuous_timers() {
    entry_timer_active_ = false;
    entry_since_ms_ = 0;
    clear_timer_active_ = false;
    clear_since_ms_ = 0;
    if (state_.mode == AlarmMode::RecoveryPending) {
        state_.mode = state_.acked ? AlarmMode::AckedLatched : AlarmMode::ActiveLatched;
    }
}

PersistStatus AlarmStateMachine::restore_persisted(const std::uint8_t* data, std::size_t size) {
    PersistedLatch decoded{};
    const auto status = decode_persisted_latch(data, size, decoded);
    break_continuous_timers();
    if (status == PersistStatus::EmptyFirstBoot) {
        state_.persistence_fault = false;
        return status;
    }
    if (status == PersistStatus::CorruptFault) {
        state_.persistence_fault = true;
        state_.input_fault = true;
        if (!state_.latched()) {
            state_.mode = AlarmMode::Unarmed;
        }
        return status;
    }

    state_.persistence_fault = false;
    if (decoded.latched) {
        state_.acked = decoded.acked;
        state_.mode = decoded.acked ? AlarmMode::AckedLatched : AlarmMode::ActiveLatched;
        state_.highest_level = decoded.highest_level;
        state_.trigger_level = decoded.highest_level;
        state_.trigger_reason_mask = decoded.trigger_reason_mask;
        state_.latest_reason_mask = decoded.latest_reason_mask;
        state_.trigger_boot_id = decoded.trigger_boot_id;
        state_.trigger_seq = decoded.trigger_seq;
        state_.trigger_uptime_ms = decoded.trigger_uptime_ms;
        state_.ack_uptime_ms = decoded.ack_uptime_ms;
        state_.buzzer_on = !decoded.acked;
        state_.led_on = true;
    }
    return status;
}

ValidationError AlarmStateMachine::load_policy(const AlarmPolicy& policy, bool warmup_complete) {
    const auto err = validate_alarm_policy(policy);
    if (err != ValidationError::Ok) return err;
    policy_ = policy;
    has_policy_ = true;
    state_.policy_loaded = true;
    break_continuous_timers();
    if (!state_.persistence_fault && state_.mode == AlarmMode::Unarmed && warmup_complete) {
        state_.mode = AlarmMode::Armed;
    }
    return ValidationError::Ok;
}

bool AlarmStateMachine::check_valid_live_observation(
    std::uint64_t now_ms, const AlarmObservation& obs) {
    if (now_ms < last_step_now_ms_) return false;
    last_step_now_ms_ = now_ms;

    if (obs.is_replay || !obs.calibrated || !obs.warmup_complete) return false;
    if (has_last_obs_) {
        if (obs.observation_seq <= last_obs_seq_ || obs.sample_uptime_ms <= last_obs_sample_ms_) {
            return false;
        }
    }
    if (obs.sample_uptime_ms > now_ms) return false;
    if ((now_ms - obs.sample_uptime_ms) > policy_.max_valid_result_age_ms) return false;

    const auto classified = math::classify_double(obs.sensor_score);
    if (!classified || !obs.level || *classified != *obs.level) return false;
    if (policy_.mode == ConfigMode::Calibrated && !obs.reason_mask.has_value()) return false;
    return true;
}

void AlarmStateMachine::step(std::uint64_t now_ms, const AlarmObservation& obs) {
    if (!has_policy_ || state_.persistence_fault) {
        state_.input_fault = true;
        break_continuous_timers();
        return;
    }

    if (state_.mode == AlarmMode::Unarmed && obs.warmup_complete) {
        state_.mode = AlarmMode::Armed;
    }

    if (!check_valid_live_observation(now_ms, obs)) {
        state_.input_fault = true;
        break_continuous_timers();
        return;
    }

    has_last_obs_ = true;
    last_obs_seq_ = obs.observation_seq;
    last_obs_sample_ms_ = obs.sample_uptime_ms;
    state_.input_fault = false;

    const double score = *obs.sensor_score;
    const auto level = *obs.level;
    const std::optional<std::uint32_t> mask = obs.reason_mask
        ? std::optional<std::uint32_t>{*obs.reason_mask & reason_bit::v1_mask}
        : std::nullopt;

    if (state_.mode == AlarmMode::Armed) {
        if (level == protocol::RiskLevel::Warning || level == protocol::RiskLevel::Emergency) {
            if (!entry_timer_active_) {
                entry_timer_active_ = true;
                entry_since_ms_ = obs.sample_uptime_ms;
            }
            if ((obs.sample_uptime_ms - entry_since_ms_) >= policy_.entry_dwell_ms) {
                state_.mode = AlarmMode::ActiveLatched;
                state_.acked = false;
                state_.highest_level = level;
                state_.trigger_level = level;
                state_.trigger_reason_mask = mask;
                state_.latest_reason_mask = mask;
                state_.trigger_boot_id = obs.boot_id;
                state_.trigger_seq = obs.observation_seq;
                state_.trigger_uptime_ms = obs.sample_uptime_ms;
                state_.ack_uptime_ms = 0;
                state_.buzzer_on = true;
                state_.led_on = true;
                entry_timer_active_ = false;
                entry_since_ms_ = 0;
            }
        } else {
            entry_timer_active_ = false;
            entry_since_ms_ = 0;
        }
        return;
    }

    if (state_.latched()) {
        state_.latest_reason_mask = mask;
        if (level == protocol::RiskLevel::Warning || level == protocol::RiskLevel::Emergency) {
            if (!state_.highest_level || level > *state_.highest_level) {
                state_.highest_level = level;
            }
        }
        if (score < policy_.clear_score_exclusive) {
            if (!clear_timer_active_) {
                clear_timer_active_ = true;
                clear_since_ms_ = obs.sample_uptime_ms;
            }
            if ((obs.sample_uptime_ms - clear_since_ms_) >= policy_.clear_dwell_ms) {
                state_.mode = AlarmMode::RecoveryPending;
            }
        } else {
            clear_timer_active_ = false;
            clear_since_ms_ = 0;
            if (state_.mode == AlarmMode::RecoveryPending) {
                state_.mode = state_.acked ? AlarmMode::AckedLatched : AlarmMode::ActiveLatched;
            }
        }
    }
}

bool AlarmStateMachine::local_ack(std::uint64_t now_ms) {
    if (state_.persistence_fault) return false;
    if (state_.mode == AlarmMode::ActiveLatched) {
        state_.mode = AlarmMode::AckedLatched;
        state_.acked = true;
        state_.ack_uptime_ms = now_ms;
        state_.buzzer_on = false;
        state_.led_on = true;
        return true;
    }
    if (state_.mode == AlarmMode::RecoveryPending && !state_.acked) {
        state_.acked = true;
        state_.ack_uptime_ms = now_ms;
        state_.buzzer_on = false;
        state_.led_on = true;
        return true;
    }
    return false;
}

bool AlarmStateMachine::local_clear(std::uint64_t now_ms) {
    (void)now_ms;
    if (state_.persistence_fault) return false;
    if (state_.mode != AlarmMode::RecoveryPending || !state_.acked) return false;

    state_.mode = AlarmMode::Armed;
    state_.acked = false;
    state_.buzzer_on = false;
    state_.led_on = false;
    state_.highest_level.reset();
    state_.trigger_level.reset();
    state_.trigger_reason_mask.reset();
    state_.latest_reason_mask.reset();
    state_.trigger_boot_id = 0;
    state_.trigger_seq = 0;
    state_.trigger_uptime_ms = 0;
    state_.ack_uptime_ms = 0;
    clear_timer_active_ = false;
    clear_since_ms_ = 0;
    entry_timer_active_ = false;
    entry_since_ms_ = 0;
    return true;
}

PersistedLatch AlarmStateMachine::export_persisted() const {
    PersistedLatch out{};
    out.latched = state_.latched();
    out.acked = state_.acked;
    out.highest_level = state_.highest_level.value_or(protocol::RiskLevel::Warning);
    out.trigger_reason_mask = state_.trigger_reason_mask.value_or(0U);
    out.latest_reason_mask = state_.latest_reason_mask.value_or(0U);
    out.trigger_boot_id = state_.trigger_boot_id;
    out.trigger_seq = state_.trigger_seq;
    out.trigger_uptime_ms = state_.trigger_uptime_ms;
    out.risk_config_tag = policy_.risk_config_tag;
    out.alarm_policy_tag = policy_.alarm_policy_tag;
    out.ack_uptime_ms = state_.ack_uptime_ms;
    return out;
}

template<std::size_t Capacity>
void CausalBuffer<Capacity>::add(std::int64_t uptime_ms,
                                 std::optional<double> value,
                                 bool valid,
                                 std::uint32_t lookback_ms,
                                 std::uint32_t max_gap_ms) {
    if (uptime_ms < 0) return;
    const bool keep_valid = valid && value.has_value() && finite(*value);
    const double clean_val = keep_valid ? *value : 0.0;

    if (has_last_) {
        if (uptime_ms <= last_uptime_ms_) {
            clear();
        } else {
            const std::uint64_t dt = static_cast<std::uint64_t>(uptime_ms - last_uptime_ms_);
            if (dt > max_gap_ms) {
                clear();
            }
        }
    }

    has_last_ = true;
    last_uptime_ms_ = uptime_ms;

    if (count_ == Capacity) {
        head_ = (head_ + 1U) % Capacity;
        --count_;
    }
    const std::size_t tail = (head_ + count_) % Capacity;
    entries_[tail] = Entry{uptime_ms, clean_val, keep_valid};
    ++count_;

    const std::int64_t start = uptime_ms - static_cast<std::int64_t>(lookback_ms);
    while (count_ > 0 && entries_[head_].uptime_ms < start) {
        head_ = (head_ + 1U) % Capacity;
        --count_;
    }
}

template<std::size_t Capacity>
bool CausalBuffer<Capacity>::slice(std::int64_t end_uptime_ms,
                                   std::uint32_t lookback_ms,
                                   std::uint32_t max_gap_ms,
                                   std::uint32_t max_age_ms,
                                   std::uint32_t min_samples,
                                   std::uint32_t min_span_ms,
                                   math::TimedSample* out,
                                   std::size_t out_capacity,
                                   std::size_t& out_count) const {
    out_count = 0;
    if (end_uptime_ms < 0 || !out || out_capacity == 0) return false;
    if (has_last_ && end_uptime_ms < last_uptime_ms_) return false;

    const std::int64_t start = end_uptime_ms - static_cast<std::int64_t>(lookback_ms);
    for (std::size_t i = 0; i < count_; ++i) {
        const Entry& e = entries_[(head_ + i) % Capacity];
        if (e.valid && e.uptime_ms >= start && e.uptime_ms <= end_uptime_ms) {
            if (out_count >= out_capacity) return false;
            out[out_count++] = math::TimedSample{e.uptime_ms, e.value};
        }
    }

    if (out_count == 0) return false;
    const std::uint64_t age = static_cast<std::uint64_t>(end_uptime_ms - out[out_count - 1].timestamp_ms);
    if (age > max_age_ms) return false;

    for (std::size_t i = 1; i < out_count; ++i) {
        const std::uint64_t gap = static_cast<std::uint64_t>(out[i].timestamp_ms - out[i - 1].timestamp_ms);
        if (gap > max_gap_ms) return false;
    }

    if (out_count < min_samples) return false;
    const std::uint64_t span = static_cast<std::uint64_t>(out[out_count - 1].timestamp_ms - out[0].timestamp_ms);
    if (span < min_span_ms) return false;
    return true;
}

template class CausalBuffer<512>;
template class CausalBuffer<64>;

ValidationError FeaturePipeline::reset(const RiskConfig& config) {
    const auto err = risk_engine_.load_config(config);
    if (err != ValidationError::Ok) return err;
    config_ = config;
    configured_ = true;
    for (auto& ch : imu_) {
        ch.has_last = false;
        ch.last_uptime_ms = 0;
        ch.last_valid = false;
        ch.last_accel = {};
        ch.has_gravity = false;
        ch.gravity = {};
        ch.has_start = false;
        ch.start_ms = 0;
        ch.tilt_buf.reset_all();
        ch.energy_buf.reset_all();
    }
    soil_present_ = {};
    soil_ = {};
    has_last_soil_tuple_ = false;
    last_soil_tuple_ = {};
    soil_growth_buf_.reset_all();
    return ValidationError::Ok;
}

bool FeaturePipeline::ingest_imu(unsigned site,
                                 std::int64_t uptime_ms,
                                 bool valid,
                                 const std::array<double, 3>& accel_mps2) {
    if (!configured_ || site >= 2U || uptime_ms < 0) return false;
    if (valid && !finite_vec3(accel_mps2)) return false;

    auto& ch = imu_[site];
    if (ch.has_last) {
        if (uptime_ms < ch.last_uptime_ms) return false;
        if (uptime_ms == ch.last_uptime_ms) {
            const bool same = (ch.last_valid == valid) && (!valid || ch.last_accel == accel_mps2);
            return same;
        }
    }

    const std::uint32_t gap_limit = std::min(config_.windows.tilt.max_gap_ms,
                                             config_.windows.vibration.max_gap_ms);
    const bool gap_reset = !ch.has_last ||
        (static_cast<std::uint64_t>(uptime_ms - ch.last_uptime_ms) > gap_limit);
    if (gap_reset || !valid || !ch.has_gravity) {
        ch.has_gravity = false;
        ch.has_start = false;
        ch.tilt_buf.reset_all();
        ch.energy_buf.reset_all();
    }

    std::optional<double> tilt{};
    std::optional<double> energy{};
    if (valid) {
        if (!ch.has_gravity) {
            ch.gravity = accel_mps2;
            ch.has_gravity = true;
            ch.start_ms = uptime_ms;
            ch.has_start = true;
        } else {
            const double dt = static_cast<double>(uptime_ms - ch.last_uptime_ms);
            const double alpha = -std::expm1(-dt / config_.imu.gravity_tau_ms);
            for (unsigned a = 0; a < 3; ++a) {
                ch.gravity[a] = ch.gravity[a] + alpha * (accel_mps2[a] - ch.gravity[a]);
            }
        }
        if (ch.has_start &&
            static_cast<std::uint64_t>(uptime_ms - ch.start_ms) >= config_.imu.warmup_ms) {
            tilt = math::gravity_tilt_change_deg(ch.gravity, config_.imu.baseline_gravity_mps2[site]);
            double sq_sum = 0.0;
            for (unsigned a = 0; a < 3; ++a) {
                const double dyn = accel_mps2[a] - ch.gravity[a];
                sq_sum += dyn * dyn;
            }
            if (finite(sq_sum)) energy = sq_sum;
        }
    }

    ch.tilt_buf.add(uptime_ms, tilt, tilt.has_value(),
                    config_.windows.tilt.lookback_ms, config_.windows.tilt.max_gap_ms);
    ch.energy_buf.add(uptime_ms, energy, energy.has_value(),
                      config_.windows.vibration.lookback_ms, config_.windows.vibration.max_gap_ms);

    ch.has_last = true;
    ch.last_uptime_ms = uptime_ms;
    ch.last_valid = valid;
    ch.last_accel = valid ? accel_mps2 : std::array<double, 3>{};
    return true;
}

void FeaturePipeline::eval_soil_at(std::int64_t end_uptime_ms,
                                   std::array<std::optional<double>, 3>& out_values,
                                   std::array<SoilProbeStatus, 3>& out_status,
                                   std::optional<double>& out_avg) const {
    out_values = {};
    out_avg.reset();
    const auto& w = config_.windows.soil_growth;

    std::size_t time_count = 0;
    std::int64_t min_t = 0;
    std::int64_t max_t = 0;
    for (unsigned p = 0; p < 3; ++p) {
        if (!soil_present_[p]) {
            out_status[p] = SoilProbeStatus::Missing;
            continue;
        }
        const auto& row = soil_[p];
        if (time_count == 0) {
            min_t = row.uptime_ms;
            max_t = row.uptime_ms;
        } else {
            min_t = std::min(min_t, row.uptime_ms);
            max_t = std::max(max_t, row.uptime_ms);
        }
        ++time_count;

        if (!row.valid) {
            out_status[p] = SoilProbeStatus::InvalidObs;
        } else if (end_uptime_ms < row.uptime_ms ||
                   static_cast<std::uint64_t>(end_uptime_ms - row.uptime_ms) > w.max_age_ms) {
            out_status[p] = SoilProbeStatus::StaleOrFuture;
        } else {
            const auto& cal = config_.soil.calibration[p];
            const auto rel = math::relative_wetness_index(
                static_cast<double>(row.raw), cal.dry_raw, cal.wet_raw);
            if (!rel) {
                out_status[p] = SoilProbeStatus::CalRangeExceeded;
            } else {
                const double pct = 100.0 * (*rel);
                if (pct >= 0.0 && pct <= 100.0) {
                    out_values[p] = pct;
                    out_status[p] = SoilProbeStatus::Valid;
                } else {
                    out_status[p] = SoilProbeStatus::CalRangeExceeded;
                }
            }
        }
    }

    const bool aligned = (time_count == 3U) &&
                         (static_cast<std::uint64_t>(max_t - min_t) <= config_.soil.alignment_ms);
    if (aligned && out_values[0] && out_values[1] && out_values[2]) {
        out_avg = (*out_values[0] + *out_values[1] + *out_values[2]) / 3.0;
    }
}

bool FeaturePipeline::ingest_soil_group(std::int64_t group_uptime_ms,
                                        const std::array<std::optional<SoilRawObs>, 3>& updates) {
    if (!configured_ || group_uptime_ms < 0) return false;
    bool updated = false;
    for (unsigned p = 0; p < 3; ++p) {
        if (!updates[p]) continue;
        const auto& row = *updates[p];
        if (row.uptime_ms != group_uptime_ms) return false;
        if (soil_present_[p]) {
            if (row.uptime_ms < soil_[p].uptime_ms) return false;
            if (row.uptime_ms == soil_[p].uptime_ms) {
                const bool same = (row.valid == soil_[p].valid) && (!row.valid || row.raw == soil_[p].raw);
                if (!same) return false;
                continue;
            }
        }
        soil_[p] = row;
        soil_present_[p] = true;
        updated = true;
    }
    if (!updated) return true;

    std::array<std::optional<double>, 3> values{};
    std::array<SoilProbeStatus, 3> status{};
    std::optional<double> mean{};
    eval_soil_at(group_uptime_ms, values, status, mean);

    bool fault = false;
    for (const auto s : status) {
        if (s == SoilProbeStatus::InvalidObs || s == SoilProbeStatus::CalRangeExceeded) {
            fault = true;
            break;
        }
    }
    if (fault) {
        soil_growth_buf_.reset_all();
        has_last_soil_tuple_ = false;
        return true;
    }

    if (mean.has_value() && soil_present_[0] && soil_present_[1] && soil_present_[2]) {
        const std::array<std::int64_t, 3> stamp{
            soil_[0].uptime_ms, soil_[1].uptime_ms, soil_[2].uptime_ms};
        const bool all_changed = !has_last_soil_tuple_ ||
            (stamp[0] != last_soil_tuple_[0] &&
             stamp[1] != last_soil_tuple_[1] &&
             stamp[2] != last_soil_tuple_[2]);
        if (all_changed) {
            soil_growth_buf_.add(group_uptime_ms, mean, true,
                                 config_.windows.soil_growth.lookback_ms,
                                 config_.windows.soil_growth.max_gap_ms);
            last_soil_tuple_ = stamp;
            has_last_soil_tuple_ = true;
        }
    }
    return true;
}

PipelineProjection FeaturePipeline::evaluate_at(std::int64_t end_uptime_ms) const {
    PipelineProjection out{};
    if (!configured_ || end_uptime_ms < 0) return out;
    out.risk.calibration = risk_runtime::Calibration::Ready;
    out.risk.fault = risk_runtime::Fault::InputUnavailable;

    bool imu_complete = true;
    for (unsigned p = 0; p < 2; ++p) {
        const auto& ch = imu_[p];
        std::size_t ts_count = 0;
        const bool ts_ok = ch.tilt_buf.slice(
            end_uptime_ms,
            config_.windows.tilt.lookback_ms,
            config_.windows.tilt.max_gap_ms,
            config_.windows.tilt.max_age_ms,
            config_.windows.tilt.min_samples,
            config_.windows.tilt.min_span_ms,
            scratch_.data(), scratch_.size(), ts_count);
        if (ch.has_last && ch.last_valid && ts_ok && ts_count > 0) {
            out.imu[p].tilt_deg = scratch_[ts_count - 1].value;
            out.imu[p].tilt_rate_dps = math::causal_slope_per_second(scratch_.data(), ts_count);
        }

        std::size_t es_count = 0;
        const bool es_ok = ch.energy_buf.slice(
            end_uptime_ms,
            config_.windows.vibration.lookback_ms,
            config_.windows.vibration.max_gap_ms,
            config_.windows.vibration.max_age_ms,
            config_.windows.vibration.min_samples,
            config_.windows.vibration.min_span_ms,
            scratch_.data(), scratch_.size(), es_count);
        if (ch.has_last && ch.last_valid && es_ok && es_count > 0) {
            double e_sum = 0.0;
            for (std::size_t i = 0; i < es_count; ++i) e_sum += scratch_[i].value;
            out.imu[p].vibration_rms = std::sqrt(e_sum / static_cast<double>(es_count));
        }

        if (!ch.has_last || !out.imu[p].tilt_deg || !out.imu[p].tilt_rate_dps || !out.imu[p].vibration_rms) {
            imu_complete = false;
        }
    }

    const bool imu_aligned = imu_[0].has_last && imu_[1].has_last &&
        (static_cast<std::uint64_t>(
            std::max(imu_[0].last_uptime_ms, imu_[1].last_uptime_ms) -
            std::min(imu_[0].last_uptime_ms, imu_[1].last_uptime_ms)) <= config_.imu.alignment_ms);

    std::array<std::optional<double>, 3> soil_vals{};
    std::array<SoilProbeStatus, 3> soil_status{};
    std::optional<double> avg_pct{};
    eval_soil_at(end_uptime_ms, soil_vals, soil_status, avg_pct);
    out.soil.top_pct = soil_vals[0];
    out.soil.middle_pct = soil_vals[1];
    out.soil.toe_pct = soil_vals[2];
    out.soil.avg_pct = avg_pct;

    std::size_t gs_count = 0;
    const bool gs_ok = soil_growth_buf_.slice(
        end_uptime_ms,
        config_.windows.soil_growth.lookback_ms,
        config_.windows.soil_growth.max_gap_ms,
        config_.windows.soil_growth.max_age_ms,
        config_.windows.soil_growth.min_samples,
        config_.windows.soil_growth.min_span_ms,
        scratch_.data(), scratch_.size(), gs_count);
    if (avg_pct.has_value() && gs_ok && gs_count >= 2) {
        if (const auto slope_s = math::causal_slope_per_second(scratch_.data(), gs_count)) {
            out.soil.growth_pct_min = (*slope_s) * 60.0;
        }
    }

    if (out.imu[0].tilt_deg && out.imu[1].tilt_deg) {
        out.dual_imu_tilt_difference_deg = std::abs(*out.imu[0].tilt_deg - *out.imu[1].tilt_deg);
    }

    if (imu_complete && imu_aligned && avg_pct.has_value() && out.soil.growth_pct_min.has_value()) {
        FeatureInputs fin{};
        fin.imu_tilt_deg = {out.imu[0].tilt_deg, out.imu[1].tilt_deg};
        fin.imu_vibration_rms = {out.imu[0].vibration_rms, out.imu[1].vibration_rms};
        fin.soil_moisture_pct = {out.soil.top_pct, out.soil.middle_pct, out.soil.toe_pct};
        fin.soil_growth_pct_min = out.soil.growth_pct_min;
        out.risk = risk_engine_.evaluate(fin);
    }
    return out;
}

ButtonEvent LocalButtonGesture::update(
    std::uint64_t now_ms, bool raw_pressed, bool recovery_ready_and_acked) {
    if (!initialized_) {
        initialized_ = true;
        last_now_ms_ = now_ms;
        last_raw_ = raw_pressed;
        raw_since_ms_ = now_ms;
        debounced_pressed_ = raw_pressed;
        boot_suppress_until_release_ = raw_pressed;
        return ButtonEvent::None;
    }

    if (now_ms < last_now_ms_) return ButtonEvent::None;
    last_now_ms_ = now_ms;

    if (raw_pressed != last_raw_) {
        last_raw_ = raw_pressed;
        raw_since_ms_ = now_ms;
    }

    const bool debounce_elapsed = (now_ms - raw_since_ms_) >= config_.debounce_ms;
    if (debounce_elapsed && (last_raw_ != debounced_pressed_)) {
        const bool was_pressed = debounced_pressed_;
        debounced_pressed_ = last_raw_;
        if (!was_pressed && debounced_pressed_) {
            // Debounced rising edge: begin fresh press gesture.
            press_start_ms_ = now_ms;
            press_consumed_by_clear_ = false;
            clear_eligible_for_this_press_ = recovery_ready_and_acked;
            if (!recovery_ready_and_acked) {
                clear_eligible_for_this_press_ = false;
            }
            return ButtonEvent::None;
        }
        if (was_pressed && !debounced_pressed_) {
            // Debounced falling edge.
            if (boot_suppress_until_release_) {
                boot_suppress_until_release_ = false;
                press_consumed_by_clear_ = false;
                clear_eligible_for_this_press_ = false;
                return ButtonEvent::None;
            }
            const bool short_press = !press_consumed_by_clear_ &&
                ((now_ms - press_start_ms_) < config_.clear_hold_ms);
            press_consumed_by_clear_ = false;
            clear_eligible_for_this_press_ = false;
            return short_press ? ButtonEvent::Ack : ButtonEvent::None;
        }
    }

    if (debounced_pressed_) {
        if (boot_suppress_until_release_) return ButtonEvent::None;
        if (!recovery_ready_and_acked) {
            clear_eligible_for_this_press_ = false;
        }
        if (clear_eligible_for_this_press_ && !press_consumed_by_clear_ &&
            (now_ms - press_start_ms_) >= config_.clear_hold_ms) {
            press_consumed_by_clear_ = true;
            clear_eligible_for_this_press_ = false;
            return ButtonEvent::Clear;
        }
    }
    return ButtonEvent::None;
}

} // namespace node::logic
