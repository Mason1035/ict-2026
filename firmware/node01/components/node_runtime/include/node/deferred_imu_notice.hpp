#pragma once
#include <cstdint>
#include <mutex>

namespace node::runtime::policy {
struct ImuNotice {
    std::uint64_t observed_us = 0;
    std::int32_t error = 0;
    bool initialized = false;
};

// One capture per boot: ImuTask records the first observation per site/kind.
// Both paths use the SAME existing Runtime snapshot spinlock adapter (host:
// std::mutex). Only the fixed payload/flag copy is protected; no I/O under it.
// This avoids assuming byte/64-bit atomics are lock-free with Xtensa's actual
// -mdisable-hardware-atomics flags. No new mutex, queue, delay or allocation.
class DeferredImuNotice {
public:
    template<class Lock> bool record(Lock& lock, std::uint64_t us, std::int32_t error, bool initialized) {
        const std::lock_guard<Lock> guard(lock);
        if (ready_) return false;
        payload_ = {us, error, initialized};
        ready_ = true;
        return true;
    }
    template<class Lock> bool read(Lock& lock, ImuNotice& out) const {
        const std::lock_guard<Lock> guard(lock);
        if (!ready_) return false;
        out = payload_;
        return true;
    }
private:
    ImuNotice payload_{};
    bool ready_ = false;
};
}
