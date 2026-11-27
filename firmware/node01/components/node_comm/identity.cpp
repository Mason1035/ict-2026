#include "node/identity.hpp"

namespace node::comm {
bool DurableIdentity::start(BootCounterStore& store, std::string_view device) {
    if (attempted_) return false;
    attempted_ = true;
    protocol::Integer old = 0, readback = 0;
    if (device.empty() || !store.load(old) || old >= protocol::json_safe_integer_max) return false;
    const auto reserved = old + 1;
    // Missing persisted state is NOT permission to start again from boot 0.
    if (!store.commit(reserved) || !store.load(readback) || readback != reserved) return false;
    next_ = {device, reserved, 1}; ready_ = true;
    return true;
}
std::optional<protocol::MessageIdentity> DurableIdentity::next_original() {
    if (!ready_) return std::nullopt;
    const auto result = next_;
    if (next_.seq == protocol::json_safe_integer_max) ready_ = false;
    else ++next_.seq;
    return result;
}
}
