#include "node/protocol.hpp"
#include <cmath>

namespace node::protocol {
std::optional<RiskLevel> classify(std::optional<float> score) {
    if (!score || !std::isfinite(*score) || *score < 0 || *score > 100)
        return std::nullopt;
    if (*score < 30) return RiskLevel::Normal;
    if (*score < 60) return RiskLevel::Watch;
    if (*score < 80) return RiskLevel::Warning;
    return RiskLevel::Emergency;
}
} // namespace node::protocol
