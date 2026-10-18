#include "node/logic.hpp"

namespace node::features {
Snapshot evaluate(const sampling::SensorSnapshot&) {
    return {}; // TODO_CALIBRATION: no guessed filter/window/physical threshold.
}
}
namespace node::risk_runtime {
Snapshot evaluate(const features::Snapshot&) {
    return {}; // B's calibrated config/reference not integrated. All Risk fields null.
}
bool same_state(const Snapshot& a, const Snapshot& b) {
    return a.calibration == b.calibration && a.fault == b.fault &&
           a.risk.sensor_score == b.risk.sensor_score && a.risk.level == b.risk.level &&
           a.risk.reason_mask == b.risk.reason_mask;
}
}
namespace node::alarm {
void Controller::consume(const risk_runtime::Snapshot& input) {
    const auto classified = protocol::classify(input.risk.sensor_score);
    state_.input_fault = input.calibration != risk_runtime::Calibration::Ready ||
        input.fault != risk_runtime::Fault::None || !classified || classified != input.risk.level;
    if (state_.input_fault) return; // Missing input never clears an existing high alarm.
    if (*classified == protocol::RiskLevel::Warning || *classified == protocol::RiskLevel::Emergency) {
        if (!state_.latched_level || *classified > *state_.latched_level)
            state_.latched_level = classified;
    }
    // No release policy until B supplies calibrated hysteresis; hardware stays disabled.
}
}
