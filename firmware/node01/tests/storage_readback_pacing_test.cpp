#include "node/storage_recovery.hpp"
#include "node/runtime_policy.hpp"
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <deque>
#include <set>
#include <string>
#include <vector>

// TEST_ONLY deterministic virtual time. Injected I/O is NOT an SD measurement.
// Runs the production RecoveryWriter and index/queue-send policy unchanged.
namespace {
using namespace node;
namespace policy=runtime::policy;
struct Lock {void lock(){} void unlock(){}};
struct Plan {
    const char* name;unsigned verify_us=35000,capacity=512,initial=0;
    unsigned append_tail_us=0,flush_tail_us=0,fsync_tail_us=0;
    bool fast_producer=false;
};
struct Backend final : storage::Backend {
    const Plan& plan;std::uint64_t us=0;
    unsigned rows=0,remaining=0,append_calls=0,flush_calls=0,verify_calls=0;
    unsigned max_append_us=0,max_flush_us=0;
    std::vector<std::uint64_t> accepted;
    explicit Backend(const Plan& p):plan(p){}
    bool recover() override{return true;}
    bool append(const sampling::AcquisitionRecord& r) override {
        const unsigned wall=++append_calls==1000 && plan.append_tail_us?plan.append_tail_us:1000;
        max_append_us=std::max(max_append_us,wall);us+=wall;++rows;
        accepted.push_back(r.acquisition_index);return true;
    }
    bool flush() override {
        ++flush_calls;const unsigned wall=flush_calls==5?30000+plan.flush_tail_us+plan.fsync_tail_us:30000;
        max_flush_us=std::max(max_flush_us,wall);us+=wall;return true;
    }
    bool close_and_verify() override{assert(false);return false;}
    bool open_next() override{us+=10000;return true;}
    void abandon() override{assert(false);}
    bool deferred_verification() const override{return true;}
    bool begin_verify() override {
        assert(remaining==0);remaining=(rows*140+1392+4095)/4096;rows=0;us+=30000;return true;
    }
    storage::VerifyResult verify_step() override {
        ++verify_calls;us+=plan.verify_us;
        if(remaining){--remaining;return storage::VerifyResult::Pending;}
        return storage::VerifyResult::Passed;
    }
};
struct Result {unsigned produced=0,enqueued=0,dequeued=0,dropped=0,peak=0;std::uint64_t elapsed=0;};
Result simulate(const Plan& plan) {
    Backend backend(plan);storage::RecoveryWriter writer(backend,256,4000,16);
    policy::DiagnosticSequence<Lock> ids;std::deque<sampling::AcquisitionRecord> queue;
    std::set<std::uint64_t> failed_ids;Result r;
    constexpr std::uint64_t duration=65000000;
    std::uint64_t next_imu=10000,next_soil=500000;
    writer.step(0);
    auto send=[&](unsigned channel,bool soil){
        sampling::AcquisitionRecord value;value.kind=soil?sampling::RecordKind::Soil:sampling::RecordKind::Imu;
        value.channel=channel;value.soil.validity=sampling::Validity::Valid;value.soil.raw=0;
        ++r.produced;const auto outcome=policy::enqueue_record(value,ids,[&](const auto& x){
            if(queue.size()==plan.capacity)return false;
            queue.push_back(x);return true;
        });
        if(outcome==policy::QueueResult::Accepted){++r.enqueued;r.peak=std::max(r.peak,static_cast<unsigned>(queue.size()));}
        else {assert(outcome==policy::QueueResult::QueueFull);++r.dropped;failed_ids.insert(value.acquisition_index);}
    };
    for(unsigned i=0;i<plan.initial;++i)send(i%2,false);
    auto produce_due=[&]{
        while(next_imu<=backend.us && next_imu<=duration){send(0,false);send(1,false);next_imu+=plan.fast_producer?2000:10000;}
        while(next_soil<=backend.us && next_soil<=duration){for(unsigned c=0;c<3;++c)send(c,true);next_soil+=500000;}
    };
    for(unsigned guard=0;guard<5000000 && !writer.finished();++guard){
        produce_due();
        if(writer.can_take_record() && !queue.empty()){
            const auto value=queue.front();queue.pop_front();++r.dequeued;assert(writer.take_record(value));
        }
        if(backend.us>=duration && queue.empty() && !writer.has_pending())writer.request_finish();
        const auto prior=backend.us;writer.step(backend.us/1000);
        if(backend.us==prior)backend.us+=100;
    }
    produce_due();assert(writer.finished() && queue.empty());
    const auto& s=writer.stats();assert(s.errors==0 && s.uncertain_records==0 && s.replayed_records==0);
    assert(r.produced==r.enqueued+r.dropped && r.enqueued==r.dequeued && r.dequeued==s.append_accepted && s.append_accepted==s.verified_rows);
    std::set<std::uint64_t> accepted(backend.accepted.begin(),backend.accepted.end());
    assert(accepted.size()==backend.accepted.size());
    for(std::uint64_t i=0;i<r.produced;++i)assert(accepted.count(i)+failed_ids.count(i)==1);
    assert(failed_ids.size()==r.dropped && r.peak<=plan.capacity);
    r.elapsed=backend.us;
    std::printf("STORAGE_READBACK_MODEL {\"scenario\":\"%s\",\"TEST_ONLY\":true,\"produced\":%u,\"enqueued\":%u,\"dequeued\":%u,\"appended\":%llu,\"verified\":%llu,\"drop\":%u,\"peak\":%u,\"capacity\":%u,\"verify_steps\":%u,\"max_append_us\":%u,\"max_flush_us\":%u,\"elapsed_us\":%llu}\n",plan.name,r.produced,r.enqueued,r.dequeued,static_cast<unsigned long long>(s.append_accepted),static_cast<unsigned long long>(s.verified_rows),r.dropped,r.peak,plan.capacity,backend.verify_calls,backend.max_append_us,backend.max_flush_us,static_cast<unsigned long long>(r.elapsed));
    return r;
}
}
int main(int argc,char** argv){
    if(argc==2 && std::string(argv[1])=="--legacy"){
        const auto r=simulate({"legacy_one_append_per_verify35ms"});assert(r.dropped>0);
        std::puts("LEGACY_BOTTLENECK_REPRODUCED_TEST_ONLY; not proof of N32 physical cause");return 0;
    }
    assert(simulate({"normal_verify500us",500}).dropped==0);
    assert(simulate({"readback35ms"}).dropped==0);
    assert(simulate({"near_full",35000,512,511}).dropped==0);
    const auto full=simulate({"initial_full",35000,512,513});assert(full.peak==512 && full.dropped==1);
    const auto append=simulate({"append_tail3s",35000,512,0,3000000});assert(append.dropped>0);
    const auto flush=simulate({"flush_tail3s",35000,512,0,0,3000000});assert(flush.dropped>0);
    const auto fsync=simulate({"fsync_tail3s",35000,512,0,0,0,3000000});assert(fsync.dropped>0);
    const auto fast=simulate({"producer_faster_than_storage",35000,512,0,0,0,0,true});assert(fast.dropped>0);
    std::puts("STORAGE_READBACK_PACING_HOST_PASS cases=8; exact drop accounting; HARDWARE_NOT_RUN");
}
