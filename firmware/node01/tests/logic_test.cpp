#include "node/logic.hpp"
#include "node/ports.hpp"
#include <cassert>
#include <limits>

int main() {
    using namespace node;
    using protocol::RiskLevel;
    assert(!protocol::classify(std::nullopt));
    assert(!protocol::classify(-1));
    assert(!protocol::classify(100.1f));
    assert(!protocol::classify(std::numeric_limits<float>::quiet_NaN()));
    assert(!protocol::classify(std::numeric_limits<float>::infinity()));
    assert(protocol::classify(0) == RiskLevel::Normal);
    assert(protocol::classify(29.9f) == RiskLevel::Normal);
    assert(protocol::classify(30) == RiskLevel::Watch);
    assert(protocol::classify(59.9f) == RiskLevel::Watch);
    assert(protocol::classify(60) == RiskLevel::Warning);
    assert(protocol::classify(79.9f) == RiskLevel::Warning);
    assert(protocol::classify(80) == RiskLevel::Emergency);
    assert(protocol::classify(100) == RiskLevel::Emergency);
    const auto empty = risk_runtime::evaluate(features::evaluate({}));
    assert(!empty.risk.sensor_score && !empty.risk.level && !empty.risk.reason_mask);
    assert(empty.calibration == risk_runtime::Calibration::NotReady);
    features::Snapshot injected{};
    injected.configured = true;
    injected.tilt_deg[0] = 90;
    assert(!risk_runtime::evaluate(injected).risk.sensor_score);
    alarm::Controller alarm;
    alarm.consume(empty);
    assert(!alarm.state().latched_level && alarm.state().input_fault);
    // TEST_ONLY state input, never a sensor/Real observation.
    risk_runtime::Snapshot test_input{};
    test_input.risk.sensor_score = 90;
    test_input.risk.level = RiskLevel::Emergency;
    alarm.consume(test_input); // reject score without calibrated source
    assert(!alarm.state().latched_level);
    test_input.calibration = risk_runtime::Calibration::Ready;
    test_input.fault = risk_runtime::Fault::None;
    test_input.risk.level = RiskLevel::Normal; // inconsistent score/level
    alarm.consume(test_input);
    assert(!alarm.state().latched_level);
    test_input.risk.level = RiskLevel::Emergency;
    alarm.consume(test_input);
    assert(alarm.state().latched_level == RiskLevel::Emergency);
    alarm.consume(empty); // no release on sensor loss
    assert(alarm.state().latched_level == RiskLevel::Emergency);
    assert(!alarm.state().hardware_enabled);
    protocol::TelemetryDraft draft{};
    assert(!draft.identity && !draft.timestamp_ms && !draft.time_synced);
    assert(!draft.imu[0].valid && !draft.imu[1].valid);
    assert(!draft.soil.top_raw && !draft.soil.top_pct);
    assert(!draft.risk.level && draft.system.sensor_degraded);
}
