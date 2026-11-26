#include "node/risk_framework.hpp"
#include <array>
#include <cassert>
#include <cmath>
#include <limits>

namespace {
using namespace node;
using namespace node::logic;
using protocol::RiskLevel;

bool near(double actual, double expected, double tol = 1e-12) {
    return std::isfinite(actual) && std::abs(actual - expected) <= tol;
}

math::Curve make_curve(std::initializer_list<math::CurvePoint> pts) {
    math::Curve c{};
    c.count = pts.size();
    std::size_t idx = 0;
    for (const auto& p : pts) {
        c.points[idx++] = p;
    }
    return c;
}

RiskConfig make_calibrated_config() {
    RiskConfig c{};
    c.mode = ConfigMode::Calibrated;
    c.validated_for_runtime = true;
    c.review_a = true;
    c.review_b = true;
    c.review_c = true;
    c.has_config_hash = true;
    c.has_config_version = true;
    c.has_feature_version = true;
    c.has_calibration_version = true;
    c.has_frame_id = true;
    c.has_device_identity = true;
    c.has_sensor_ids = true;
    c.has_reason_mask_version = true;
    c.has_reason_bits = true;
    c.reason_bits = {0, 1, 2, 3, 4};
    c.weights = {0.30, 0.25, 0.25, 0.20};
    c.imu_odr_hz = 100.0;
    c.soil_odr_hz = 2.0;
    c.missing_policy = MissingPolicy::RequireBothImuAndAllThreeSoilV1;

    c.imu.gravity_tau_ms = 2000.0;
    c.imu.warmup_ms = 5000;
    c.imu.alignment_ms = 100;
    c.imu.baseline_gravity_mps2[0] = {0.0, 0.0, 9.80665};
    c.imu.baseline_gravity_mps2[1] = {0.0, 0.0, 9.80665};

    c.soil.alignment_ms = 1500;
    for (auto& probe : c.soil.calibration) {
        probe.dry_raw = 20000.0;
        probe.wet_raw = 10000.0;
        probe.min_span_raw = 2000.0;
    }

    const RiskConfig::WindowSpec win{5000, 500, 1000, 2, 1000};
    c.windows.tilt = win;
    c.windows.vibration = win;
    c.windows.soil_growth = win;

    c.curves.tilt = make_curve({{0.0, 0.0}, {10.0, 50.0}, {20.0, 100.0}});
    c.curves.vibration = make_curve({{0.0, 0.0}, {2.0, 100.0}});
    c.curves.moisture = make_curve({{0.0, 0.0}, {100.0, 100.0}});
    c.curves.growth = make_curve({{0.0, 0.0}, {10.0, 100.0}});

    c.consensus.tilt_threshold_deg = 8.0;
    c.consensus.max_tilt_difference_deg = 3.0;
    c.consensus.bonus = 5.0;
    c.config_hash_tag = 0x123456789ABCDEF0ULL;
    return c;
}

AlarmPolicy make_calibrated_alarm_policy() {
    AlarmPolicy p{};
    p.mode = ConfigMode::Calibrated;
    p.validated_for_runtime = true;
    p.review_a = true;
    p.review_b = true;
    p.review_c = true;
    p.has_alarm_policy_version = true;
    p.has_risk_config_hash = true;
    p.has_reason_mask_version = true;
    p.has_hardware_profile = true;
    p.has_device_identity = true;
    p.entry_dwell_ms = 2000;
    p.clear_score_exclusive = 45.0;
    p.clear_dwell_ms = 3000;
    p.max_valid_result_age_ms = 500;
    p.auto_clear = false;
    p.clear_requires_ack = true;
    p.persist_latch = true;
    p.unknown_keeps_latch = true;
    p.risk_config_tag = 0xAABBCCDDULL;
    p.alarm_policy_tag = 0x11223344ULL;
    return p;
}

void test_math_vectors() {
    // Matches golden_vectors.TEST_ONLY.json within 1e-12.
    const auto right_angle = math::gravity_tilt_change_deg({0.0, 1.0, 0.0}, {0.0, 0.0, 1.0});
    assert(right_angle && near(*right_angle, 90.0));
    assert(!math::gravity_tilt_change_deg({0.0, 1.0, 0.0}, {0.0, 0.0, 0.0}));
    assert(!math::gravity_tilt_change_deg({std::numeric_limits<double>::quiet_NaN(), 0.0, 1.0}, {0.0, 0.0, 1.0}));

    const std::array<math::TimedSample, 2> s1{{{0, 1.0}, {1000, 3.0}}};
    const auto slope1 = math::causal_slope_per_second(s1.data(), s1.size());
    assert(slope1 && near(*slope1, 2.0));

    const std::array<math::TimedSample, 2> s2{{{0, 3.0}, {60000, 1.0}}};
    const auto slope2 = math::causal_slope_per_second(s2.data(), s2.size());
    assert(slope2 && near(*slope2, -0.03333333333333333));

    const std::array<math::TimedSample, 2> bad_order{{{1000, 3.0}, {0, 1.0}}};
    assert(!math::causal_slope_per_second(bad_order.data(), bad_order.size()));
    const std::array<math::TimedSample, 2> dup_time{{{1000, 3.0}, {1000, 4.0}}};
    assert(!math::causal_slope_per_second(dup_time.data(), dup_time.size()));

    const std::array<std::array<double, 3>, 1> dyn{{{3.0, 4.0, 0.0}}};
    const auto rms = math::dynamic_accel_rms_mps2(dyn.data(), dyn.size());
    assert(rms && near(*rms, 5.0));

    assert(near(*math::relative_wetness_index(150.0, 100.0, 200.0), 0.5));
    assert(near(*math::relative_wetness_index(100.0, 100.0, 200.0), 0.0));
    assert(near(*math::relative_wetness_index(200.0, 100.0, 200.0), 1.0));
    assert(!math::relative_wetness_index(150.0, 100.0, 100.0));

    assert(near(*math::sensor_score(100.0, 0.0, 0.0, 0.0, 0.0), 30.0));
    assert(near(*math::sensor_score(0.0, 0.0, 0.0, 0.0, 5.0), 5.0));
    assert(near(*math::sensor_score(100.0, 100.0, 100.0, 100.0, 5.0), 100.0));
    assert(!math::sensor_score(-0.1, 0.0, 0.0, 0.0, 0.0));
    assert(!math::sensor_score(0.0, 0.0, 0.0, 0.0, 3.0));

    // Exact unrounded double boundaries (zero epsilon tolerance).
    assert(math::classify_double(0.0) == RiskLevel::Normal);
    assert(math::classify_double(std::nextafter(30.0, 0.0)) == RiskLevel::Normal);
    assert(math::classify_double(30.0) == RiskLevel::Watch);
    assert(math::classify_double(std::nextafter(60.0, 0.0)) == RiskLevel::Watch);
    assert(math::classify_double(60.0) == RiskLevel::Warning);
    assert(math::classify_double(std::nextafter(80.0, 0.0)) == RiskLevel::Warning);
    assert(math::classify_double(80.0) == RiskLevel::Emergency);
    assert(math::classify_double(100.0) == RiskLevel::Emergency);
    assert(!math::classify_double(-0.000001));
    assert(!math::classify_double(100.000001));
    assert(!math::classify_double(std::numeric_limits<double>::quiet_NaN()));
    assert(!math::classify_double(std::numeric_limits<double>::infinity()));
}

void test_config_and_risk_engine() {
    RiskEngine engine;
    assert(!engine.configured());
    const auto unconf = engine.evaluate({});
    assert(!unconf.valid && !unconf.score && !unconf.level && !unconf.reason_mask);
    assert(unconf.calibration == risk_runtime::Calibration::NotReady);
    assert(unconf.fault == risk_runtime::Fault::Uncalibrated);

    RiskConfig draft = make_calibrated_config();
    draft.mode = ConfigMode::Draft;
    assert(validate_risk_config(draft) == ValidationError::DraftRejected);
    assert(engine.load_config(draft) == ValidationError::DraftRejected);
    assert(!engine.configured());

    RiskConfig bad_testonly = make_calibrated_config();
    bad_testonly.mode = ConfigMode::TestOnly;
    bad_testonly.validated_for_runtime = false;
    assert(validate_risk_config(bad_testonly) == ValidationError::InvalidReasonBits);

    RiskConfig good_testonly = bad_testonly;
    good_testonly.has_reason_mask_version = false;
    good_testonly.has_reason_bits = false;
    assert(validate_risk_config(good_testonly) == ValidationError::Ok);

    RiskConfig bad_reviews = make_calibrated_config();
    bad_reviews.review_c = false;
    assert(validate_risk_config(bad_reviews) == ValidationError::MissingReviewRefs);

    RiskConfig bad_bits = make_calibrated_config();
    bad_bits.reason_bits = {0, 1, 2, 3, 3}; // duplicate bit
    assert(validate_risk_config(bad_bits) == ValidationError::InvalidReasonBits);
    bad_bits.reason_bits = {0, 1, 2, 3, 32}; // > 31
    assert(validate_risk_config(bad_bits) == ValidationError::InvalidReasonBits);

    RiskConfig bad_weights = make_calibrated_config();
    bad_weights.weights = {0.40, 0.20, 0.20, 0.20};
    assert(validate_risk_config(bad_weights) == ValidationError::InvalidWeights);

    RiskConfig bad_curve = make_calibrated_config();
    bad_curve.curves.tilt = make_curve({{0.0, 0.0}, {10.0, 50.0}, {10.0, 60.0}}); // x not strictly increasing
    assert(validate_risk_config(bad_curve) == ValidationError::InvalidCurve);

    RiskConfig bad_soil = make_calibrated_config();
    bad_soil.soil.calibration[1].wet_raw = 19000.0; // span 1000 < min_span 2000
    assert(validate_risk_config(bad_soil) == ValidationError::InvalidCalibration);

    RiskConfig bad_base = make_calibrated_config();
    bad_base.imu.baseline_gravity_mps2[1] = {0.0, 0.0, 0.0};
    assert(validate_risk_config(bad_base) == ValidationError::InvalidBaseline);

    // Load TEST_ONLY, verify score & null reason_mask.
    assert(engine.load_config(good_testonly) == ValidationError::Ok);
    assert(engine.configured());
    FeatureInputs full{};
    full.imu_tilt_deg = {10.0, 10.0};        // max=10 -> tilt_c=50 (0.3*50=15)
    full.imu_vibration_rms = {0.0, 0.0};    // vib_c=0
    full.soil_moisture_pct = {0.0, 0.0, 0.0}; // moist_c=0
    full.soil_growth_pct_min = -5.0;        // clamped to 0 -> growth_c=0
    // consensus: min=10>=8, diff=0<=3 -> bonus=5 => score=20.0 (NORMAL)
    const auto to_res = engine.evaluate(full);
    assert(to_res.valid && near(*to_res.score, 20.0));
    assert(to_res.level == RiskLevel::Normal);
    assert(!to_res.reason_mask.has_value()); // TEST_ONLY must NOT populate formal reason_mask

    // Failed reload preserves prior valid config!
    assert(engine.load_config(bad_curve) == ValidationError::InvalidCurve);
    assert(engine.active_config().mode == ConfigMode::TestOnly);
    assert(engine.evaluate(full).valid);

    // Load CALIBRATED config.
    const auto cal = make_calibrated_config();
    assert(engine.load_config(cal) == ValidationError::Ok);

    // Missing any channel triggers REQUIRE_BOTH_IMU_AND_ALL_THREE_SOIL_V1 block.
    FeatureInputs missing_toe = full;
    missing_toe.imu_tilt_deg[1] = std::nullopt;
    const auto mr1 = engine.evaluate(missing_toe);
    assert(!mr1.valid && !mr1.score && !mr1.level && !mr1.reason_mask);
    assert(mr1.calibration == risk_runtime::Calibration::Ready);
    assert(mr1.fault == risk_runtime::Fault::InputUnavailable);

    FeatureInputs missing_soil = full;
    missing_soil.soil_moisture_pct[2] = std::numeric_limits<double>::quiet_NaN();
    const auto mr2 = engine.evaluate(missing_soil);
    assert(!mr2.valid && !mr2.score && mr2.fault == risk_runtime::Fault::InputUnavailable);

    // Full valid CALIBRATED evaluation with all contributions == 0 and no consensus gives score=0.0, mask=0.
    FeatureInputs all_zero{};
    all_zero.imu_tilt_deg = {0.0, 0.0};
    all_zero.imu_vibration_rms = {0.0, 0.0};
    all_zero.soil_moisture_pct = {0.0, 0.0, 0.0};
    all_zero.soil_growth_pct_min = -1.0;
    const auto zero_res = engine.evaluate(all_zero);
    assert(zero_res.valid && near(*zero_res.score, 0.0));
    assert(zero_res.level == RiskLevel::Normal);
    assert(zero_res.reason_mask.has_value() && *zero_res.reason_mask == 0U);

    // Full valid CALIBRATED evaluation with negative growth clamped to 0.
    const auto cal_res = engine.evaluate(full);
    assert(cal_res.valid && near(*cal_res.score, 20.0));
    assert(cal_res.level == RiskLevel::Normal);
    const std::uint32_t expected_mask1 = reason_bit::tilt_contribution | reason_bit::dual_imu_consensus;
    assert(cal_res.reason_mask == expected_mask1);
    assert((*cal_res.reason_mask & ~reason_bit::v1_mask) == 0U);

    // Exact boundary test: 0.30*100 + 0.25*80 + 0.25*100 + 0.20*25 + 0 = 80.0 (no consensus) -> EMERGENCY.
    FeatureInputs emergency{};
    emergency.imu_tilt_deg = {20.0, 0.0};          // min=0 < 8 -> no consensus bonus; max=20 -> 100
    emergency.imu_vibration_rms = {1.6, 1.0};      // max=1.6 -> 80
    emergency.soil_moisture_pct = {100.0, 100.0, 100.0}; // avg=100 -> 100
    emergency.soil_growth_pct_min = 2.5;           // 2.5/10*100 = 25
    const auto em_res = engine.evaluate(emergency);
    assert(em_res.valid && near(*em_res.score, 80.0));
    assert(em_res.level == RiskLevel::Emergency);
    const std::uint32_t expected_mask2 =
        reason_bit::tilt_contribution |
        reason_bit::vibration_contribution |
        reason_bit::moisture_contribution |
        reason_bit::growth_contribution;
    assert(em_res.reason_mask == expected_mask2);

    const auto snap = em_res.to_runtime_snapshot();
    assert(snap.calibration == risk_runtime::Calibration::Ready);
    assert(snap.fault == risk_runtime::Fault::None);
    assert(snap.risk.level == RiskLevel::Emergency);
    assert(snap.risk.reason_mask == expected_mask2);
}

void test_alarm_state_machine_and_persistence() {
    AlarmPolicy draft = make_calibrated_alarm_policy();
    draft.mode = ConfigMode::Draft;
    assert(validate_alarm_policy(draft) == ValidationError::DraftRejected);

    AlarmPolicy bad_hyst = make_calibrated_alarm_policy();
    bad_hyst.clear_score_exclusive = 60.0; // must be strictly < 60.0
    assert(validate_alarm_policy(bad_hyst) == ValidationError::InvalidPolicyConstraint);

    AlarmPolicy bad_autoclear = make_calibrated_alarm_policy();
    bad_autoclear.auto_clear = true;
    assert(validate_alarm_policy(bad_autoclear) == ValidationError::InvalidPolicyConstraint);

    AlarmStateMachine fsm;
    assert(fsm.restore_persisted(nullptr, 0) == PersistStatus::EmptyFirstBoot);
    assert(fsm.state().mode == AlarmMode::Unarmed && !fsm.state().persistence_fault);

    const auto policy = make_calibrated_alarm_policy();
    assert(fsm.load_policy(policy, false) == ValidationError::Ok);
    assert(fsm.state().mode == AlarmMode::Unarmed); // still waiting warmup

    // Warmup complete arms FSM; Normal does not trigger.
    AlarmObservation obs{1, 1000, 7, true, true, false, 15.0, RiskLevel::Normal, 0U};
    fsm.step(1000, obs);
    assert(fsm.state().mode == AlarmMode::Armed);
    assert(!fsm.state().input_fault && fsm.state().safe_to_ignore());

    // Warning dwell must be continuous >= 2000ms.
    obs = {2, 2000, 7, true, true, false, 65.0, RiskLevel::Warning, reason_bit::tilt_contribution};
    fsm.step(2000, obs);
    assert(fsm.state().mode == AlarmMode::Armed);

    // Duplicate packet breaks continuity and never advances timer.
    fsm.step(3500, obs);
    assert(fsm.state().mode == AlarmMode::Armed);

    // Restart Warning dwell -> t=4000 (not ready at 5999, triggers at 6000).
    obs = {3, 4000, 7, true, true, false, 65.0, RiskLevel::Warning, reason_bit::tilt_contribution};
    fsm.step(4000, obs);
    obs = {4, 5999, 7, true, true, false, 68.0, RiskLevel::Warning, reason_bit::tilt_contribution};
    fsm.step(5999, obs);
    assert(fsm.state().mode == AlarmMode::Armed);

    // Replay flag must NOT trigger alarm!
    AlarmObservation replay = {5, 6500, 7, true, true, true, 90.0, RiskLevel::Emergency, reason_bit::tilt_contribution};
    fsm.step(6500, replay);
    assert(fsm.state().mode == AlarmMode::Armed);

    // Restart clean continuous Warning dwell from 7000..9000ms.
    obs = {5, 7000, 7, true, true, false, 68.0, RiskLevel::Warning, reason_bit::tilt_contribution};
    fsm.step(7000, obs);
    obs = {6, 9000, 7, true, true, false, 70.0, RiskLevel::Warning,
           reason_bit::tilt_contribution | reason_bit::vibration_contribution};
    fsm.step(9000, obs);
    assert(fsm.state().mode == AlarmMode::ActiveLatched);
    assert(fsm.state().buzzer_on && fsm.state().led_on && !fsm.state().acked);
    assert(fsm.state().trigger_level == RiskLevel::Warning);
    assert(fsm.state().highest_level == RiskLevel::Warning);
    assert(fsm.state().trigger_seq == 6 && fsm.state().trigger_uptime_ms == 9000);
    const auto init_mask = fsm.state().trigger_reason_mask;

    // Upgrade to Emergency preserves initial trigger record while updating highest_level.
    obs = {7, 9200, 7, true, true, false, 85.0, RiskLevel::Emergency, reason_bit::v1_mask};
    fsm.step(9200, obs);
    assert(fsm.state().highest_level == RiskLevel::Emergency);
    assert(fsm.state().trigger_level == RiskLevel::Warning);
    assert(fsm.state().trigger_reason_mask == init_mask);
    assert(fsm.state().trigger_seq == 6 && fsm.state().trigger_uptime_ms == 9000);
    assert(fsm.state().latest_reason_mask == reason_bit::v1_mask);

    // Missing / stale input never clears latch; remote ACK/CLEAR strictly forbidden.
    assert(!fsm.remote_ack());
    assert(!fsm.remote_clear());
    AlarmObservation stale = {8, 9300, 7, true, true, false, 10.0, RiskLevel::Normal, 0U};
    fsm.step(10000, stale); // age = 700 > max_age 500
    assert(fsm.state().input_fault && fsm.state().mode == AlarmMode::ActiveLatched);
    assert(fsm.state().buzzer_on && fsm.state().led_on);

    // Local CLEAR forbidden before ACK and before RecoveryPending.
    assert(!fsm.local_clear(10100));

    // Local ACK silences buzzer, preserves LED and latch.
    assert(fsm.local_ack(10200));
    assert(fsm.state().mode == AlarmMode::AckedLatched);
    assert(fsm.state().acked && !fsm.state().buzzer_on && fsm.state().led_on);
    assert(!fsm.local_clear(10250)); // Still AckedLatched, not RecoveryPending yet

    // Persist & restore into a rebooted state machine!
    const auto exported = fsm.export_persisted();
    std::array<std::uint8_t, PersistedLatch::encoded_bytes> blob{};
    assert(encode_persisted_latch(exported, blob));

    AlarmStateMachine rebooted;
    assert(rebooted.restore_persisted(blob.data(), blob.size()) == PersistStatus::ValidRestored);
    assert(rebooted.state().mode == AlarmMode::AckedLatched);
    assert(rebooted.state().highest_level == RiskLevel::Emergency);
    assert(rebooted.state().trigger_seq == 6 && rebooted.state().trigger_reason_mask == init_mask);
    assert(rebooted.state().acked && !rebooted.state().buzzer_on && rebooted.state().led_on);
    assert(rebooted.load_policy(policy, true) == ValidationError::Ok);
    assert(rebooted.state().mode == AlarmMode::AckedLatched); // policy reload preserves latch

    // Recovery condition score < 45.0 for 3000ms -> RecoveryPending (never auto-clear).
    rebooted.step(1000, {1, 1000, 8, true, true, false, 45.0, RiskLevel::Watch, 0U}); // equal is NOT < clear_score_exclusive
    assert(rebooted.state().mode == AlarmMode::AckedLatched);
    rebooted.step(2000, {2, 2000, 8, true, true, false, 20.0, RiskLevel::Normal, 0U});
    assert(rebooted.state().mode == AlarmMode::AckedLatched);
    rebooted.step(4999, {3, 4999, 8, true, true, false, 20.0, RiskLevel::Normal, 0U});
    assert(rebooted.state().mode == AlarmMode::AckedLatched);
    rebooted.step(5000, {4, 5000, 8, true, true, false, 20.0, RiskLevel::Normal, 0U});
    assert(rebooted.state().mode == AlarmMode::RecoveryPending);
    assert(rebooted.state().latched() && rebooted.state().led_on); // no auto-clear!

    // Input fault while RecoveryPending drops back to AckedLatched & requires fresh recovery dwell.
    rebooted.step(5800, {5, 5100, 8, true, true, false, 10.0, RiskLevel::Normal, 0U}); // stale 700ms > 500ms
    assert(rebooted.state().mode == AlarmMode::AckedLatched);
    assert(!rebooted.local_clear(5850));

    // Complete recovery dwell again, then local_clear transitions back to Armed!
    rebooted.step(6000, {6, 6000, 8, true, true, false, 10.0, RiskLevel::Normal, 0U});
    rebooted.step(9000, {7, 9000, 8, true, true, false, 10.0, RiskLevel::Normal, 0U});
    assert(rebooted.state().mode == AlarmMode::RecoveryPending);
    assert(rebooted.local_clear(9050));
    assert(rebooted.state().mode == AlarmMode::Armed);
    assert(!rebooted.state().acked && !rebooted.state().buzzer_on && !rebooted.state().led_on);

    // Corrupted persisted blob sets persistence_fault & cannot be ignored.
    blob[10] ^= 0xFFU;
    AlarmStateMachine broken;
    assert(broken.restore_persisted(blob.data(), blob.size()) == PersistStatus::CorruptFault);
    assert(broken.state().persistence_fault && !broken.state().safe_to_ignore());
    assert(broken.load_policy(policy, true) == ValidationError::Ok);
    assert(broken.state().mode == AlarmMode::Unarmed && broken.state().persistence_fault);

    std::array<std::uint8_t, 5> short_blob{1, 2, 3, 4, 5};
    AlarmStateMachine truncated;
    assert(truncated.restore_persisted(short_blob.data(), short_blob.size()) == PersistStatus::CorruptFault);
    assert(truncated.state().persistence_fault);

    // Entering RecoveryPending without prior ACK still rejects local_clear until local_ack.
    AlarmStateMachine unacked_rec;
    assert(unacked_rec.load_policy(policy, true) == ValidationError::Ok);
    unacked_rec.step(1000, {1, 1000, 9, true, true, false, 70.0, RiskLevel::Warning, reason_bit::tilt_contribution});
    unacked_rec.step(3000, {2, 3000, 9, true, true, false, 70.0, RiskLevel::Warning, reason_bit::tilt_contribution});
    assert(unacked_rec.state().mode == AlarmMode::ActiveLatched);
    unacked_rec.step(4000, {3, 4000, 9, true, true, false, 10.0, RiskLevel::Normal, 0U});
    unacked_rec.step(7000, {4, 7000, 9, true, true, false, 10.0, RiskLevel::Normal, 0U});
    assert(unacked_rec.state().mode == AlarmMode::RecoveryPending && !unacked_rec.state().acked);
    assert(!unacked_rec.local_clear(7050)); // MUST fail without ACK
    assert(unacked_rec.local_ack(7100));
    assert(unacked_rec.local_clear(7150));
    assert(unacked_rec.state().mode == AlarmMode::Armed);
}

} // namespace

int main() {
    test_math_vectors();
    test_config_and_risk_engine();
    test_alarm_state_machine_and_persistence();
    return 0;
}
