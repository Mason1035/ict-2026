#pragma once
#include "node/protocol.hpp"
#include "node/sampling.hpp"

namespace node::comm {
class V2Serializer final : public protocol::TelemetrySerializer {
public:
    protocol::SerializeResult encode(const protocol::TelemetryDraft&, char*, std::size_t) override;
};
// Only map valid observations. No feature, moisture, time or risk fabrication.
protocol::TelemetryDraft make_draft(const sampling::SensorSnapshot&, std::uint64_t now_us);
bool topic_segment(std::string_view);
}
