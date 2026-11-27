#pragma once
#include <cstdint>

namespace node::runtime::policy {
struct LockOwner {
    std::uint64_t generation=0, acquired_us=0, before_give_us=0;
    std::uintptr_t task=0;
    unsigned priority=0;
};
struct LockWait {
    std::uint64_t started_us=0;
    std::uintptr_t waiter=0;
    unsigned priority=0;
    LockOwner owner_before{};
};
struct LockFailure {
    LockWait wait{};
    LockOwner owner_after{},last_give_attempt{};
    std::uint64_t finished_us=0;
    std::uintptr_t kernel_holder_after=0;
};
// Serialized by caller. Observed ownership metadata is not an atomic snapshot
// of the FreeRTOS mutex. Successful Give can preempt before released() runs.
class I2cLockTrace {
public:
    LockWait before_wait(std::uint64_t now,std::uintptr_t task,unsigned priority) const {
        return {now,task,priority,owner_};
    }
    std::uint64_t acquired(std::uint64_t now,std::uintptr_t task,unsigned priority) {
        ++acquisitions_; owner_={++generation_,now,0,task,priority}; return owner_.generation;
    }
    void before_give(std::uint64_t generation,std::uint64_t now,unsigned priority) {
        if(owner_.generation!=generation) { ++metadata_errors_; return; }
        owner_.before_give_us=now; owner_.priority=priority;
        if(now>=owner_.acquired_us && now-owner_.acquired_us>max_observed_hold_us_)
            max_observed_hold_us_=now-owner_.acquired_us;
        last_give_attempt_=owner_; // observed BEFORE Give, not proof of Give success
    }
    void released(std::uint64_t generation,bool gave) {
        if(!gave) { ++give_failures_; return; }
        ++releases_;
        // A higher-priority waiter may have acquired before Give returns.
        // Never erase that new owner's diagnostic state with the old release.
        if(owner_.generation==generation) owner_={};
    }
    void timeout(const LockWait& wait,std::uint64_t now,std::uintptr_t holder) {
        LockFailure value{wait,owner_,last_give_attempt_,now,holder};
        if(++timeouts_==1) first_=value;
        last_=value;
    }
    void copy_into(I2cLockTrace& destination) const { destination=*this; }
    const LockFailure& first() const { return first_; }
    const LockFailure& last() const { return last_; }
    const LockOwner& owner() const { return owner_; }
    std::uint64_t acquisitions() const { return acquisitions_; }
    std::uint64_t releases() const { return releases_; }
    std::uint64_t timeouts() const { return timeouts_; }
    std::uint64_t max_observed_hold_us() const { return max_observed_hold_us_; }
    std::uint64_t give_failures() const { return give_failures_; }
    std::uint64_t metadata_errors() const { return metadata_errors_; }
private:
    LockOwner owner_{},last_give_attempt_{};
    LockFailure first_{},last_{};
    std::uint64_t generation_=0,acquisitions_=0,releases_=0,timeouts_=0,max_observed_hold_us_=0,give_failures_=0,metadata_errors_=0;
};
} // namespace node::runtime::policy
