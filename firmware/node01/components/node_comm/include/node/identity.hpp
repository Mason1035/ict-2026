#pragma once
#include "node/protocol.hpp"

namespace node::comm {
class BootCounterStore {
public:
    virtual ~BootCounterStore() = default;
    virtual bool load(protocol::Integer&) = 0;
    virtual bool commit(protocol::Integer) = 0;
};
// One CommSupervisorTask owns this allocator; future original record producers
// must use that same owner/queue, never instantiate a second sequence allocator.
class DurableIdentity final : public protocol::IdentityAllocator {
public:
    bool start(BootCounterStore&, std::string_view device_id);
    std::optional<protocol::MessageIdentity> next_original() override;
private:
    bool attempted_ = false, ready_ = false;
    protocol::MessageIdentity next_{};
};
}
