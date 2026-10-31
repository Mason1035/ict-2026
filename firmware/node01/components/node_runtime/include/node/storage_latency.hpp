#pragma once
#include <array>
#include <cstdint>

namespace node::runtime::policy {
struct QuantileInterval { std::uint64_t lower_us=0, upper_us=0; bool available=false, unbounded=false; };
class LatencyHistogram {
public:
    inline static constexpr std::array<std::uint32_t,16> limits{{100,250,500,1000,2000,4000,8000,16000,32000,64000,100000,200000,300000,500000,750000,1000000}};
    void observe(std::uint64_t us) {
        unsigned bin=0; while(bin<limits.size() && us>limits[bin]) ++bin;
        ++bins_[bin]; ++samples_; if(us>max_) max_=us;
        if(us>100000) ++over100_;
        if(us>300000) ++over300_;
        if(us>500000) ++over500_;
    }
    QuantileInterval quantile(unsigned percent) const {
        if(!samples_ || !percent || percent>100) return {};
        const auto rank=(samples_/100)*percent+((samples_%100)*percent+99)/100;
        std::uint64_t cumulative=0;
        for(unsigned i=0;i<bins_.size();++i) {
            cumulative+=bins_[i];
            if(cumulative>=rank) return {i?static_cast<std::uint64_t>(limits[i-1])+1:0,
                i<limits.size()?limits[i]:0,true,i==limits.size()};
        }
        return {};
    }
    std::uint64_t samples() const { return samples_; }
    std::uint64_t maximum() const { return max_; }
    std::uint64_t over100() const { return over100_; }
    std::uint64_t over300() const { return over300_; }
    std::uint64_t over500() const { return over500_; }
private:
    std::array<std::uint64_t,17> bins_{};
    std::uint64_t samples_=0,max_=0,over100_=0,over300_=0,over500_=0;
};
struct StoragePhaseDelta {
    std::uint64_t format_us=0, fwrite_us=0, fflush_us=0, fsync_us=0, accepted_bytes=0;
    bool available=false;
};
struct IoSpan {
    std::uint64_t id=0, started_us=0, previous_id=0, previous_started_us=0, catchups=0;
    unsigned operation=7, previous_operation=7, queue_before=0;
};
struct StorageLongEvent {
    std::uint64_t sequence=0, span_id=0, started_us=0, finished_us=0, wall_us=0, catchups=0;
    StoragePhaseDelta phases{};
    unsigned operation=7, queue_before=0, queue_after=0, priority=0, core=0, rows=0, action=0;
    bool success=false; // CPU execution time is deliberately unavailable.
};
// Caller serializes short mutations and copy_into; no clock, allocation, I/O,
// scheduler call or sensor record is retained here. Ring eviction is explicit.
class StorageLatency {
public:
    static constexpr unsigned capacity=16, none=7;
    IoSpan begin(unsigned operation,std::uint64_t now,unsigned queue,std::uint64_t catchups) {
        IoSpan span{++next_id_,now,active_id_,active_started_,catchups,operation,active_operation_,queue};
        active_id_=span.id; active_started_=now; active_operation_=operation; return span;
    }
    void end(const IoSpan& span,std::uint64_t finished,unsigned queue,bool ok,
             StoragePhaseDelta phases={},unsigned priority=0,unsigned core=0) {
        if(active_id_!=span.id || finished<span.started_us) { ++context_errors_; return; }
        const auto wall=finished-span.started_us;
        if(span.operation==2) append_.observe(wall);
        if(span.operation==3) flush_.observe(wall);
        if(span.operation!=6 && wall>=100000) {
            auto& event=events_[total_events_%capacity];
            event={++total_events_,span.id,span.started_us,finished,wall,span.catchups,phases,
                span.operation,span.queue_before,queue,priority,core,(span.operation==2 && ok)?1U:0U,0,ok};
        }
        last_completed_id_=span.id;
        active_id_=span.previous_id; active_started_=span.previous_started_us; active_operation_=span.previous_operation;
    }
    void attach_action(unsigned action) {
        for(auto& event:events_) if(event.sequence && event.span_id==last_completed_id_) event.action=action;
    }
    void copy_into(StorageLatency& destination) const { destination=*this; }
    const LatencyHistogram& append() const { return append_; }
    const LatencyHistogram& flush() const { return flush_; }
    std::uint64_t total_events() const { return total_events_; }
    std::uint64_t overwritten_history() const { return total_events_>capacity?total_events_-capacity:0; }
    std::uint64_t context_errors() const { return context_errors_; }
    unsigned active_operation() const { return active_operation_; }
    std::uint64_t active_started() const { return active_started_; }
    const StorageLongEvent* event(std::uint64_t sequence) const {
        if(!sequence || sequence>total_events_ || total_events_-sequence>=capacity) return nullptr;
        const auto& value=events_[(sequence-1)%capacity]; return value.sequence==sequence?&value:nullptr;
    }
private:
    LatencyHistogram append_{},flush_{};
    std::array<StorageLongEvent,capacity> events_{};
    std::uint64_t next_id_=0,active_id_=0,active_started_=0,last_completed_id_=0,total_events_=0,context_errors_=0;
    unsigned active_operation_=none;
};
} // namespace node::runtime::policy
