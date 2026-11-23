#pragma once
#include "node/protocol.hpp"
#include "node/sampling.hpp"

namespace node::features {
struct Snapshot {
    std::array<std::optional<float>, 2> tilt_deg{}, tilt_rate_dps{}, vibration_rms{};
    std::array<std::optional<float>, 3> moisture_pct{};
    std::optional<float> moisture_growth_pct_min{};
    bool configured = false;
};
// Integration point for B's versioned formulas/windows/validity, currently unavailable.
Snapshot evaluate(const sampling::SensorSnapshot&);
}
namespace node::risk_runtime {
enum class Calibration { NotReady, Ready };
enum class Fault { Uncalibrated, InputUnavailable, None };
struct Snapshot {
    protocol::Risk risk{};
    Calibration calibration = Calibration::NotReady;
    Fault fault = Fault::Uncalibrated;
};
Snapshot evaluate(const features::Snapshot&);
bool same_state(const Snapshot&, const Snapshot&);
}
namespace node::alarm {
struct State {
    std::optional<protocol::RiskLevel> latched_level{};
    bool input_fault = true;
    bool hardware_enabled = false;
};
class Controller {
public:
    void consume(const risk_runtime::Snapshot&);
    const State& state() const { return state_; }
private:
    State state_{}; // AlarmTask owns this object; no GPIO or network dependency.
};
}
