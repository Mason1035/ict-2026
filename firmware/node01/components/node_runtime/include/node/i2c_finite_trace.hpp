#pragma once
#include <array>
#include <cstddef>
#include <cstdint>
#include <limits>
#include "node/i2c_trace_operation.hpp"

namespace node::runtime::lock_diagnostic {
// Caller serializes these fixed-bound hot-path methods. No kernel calls, allocation,
// UART, FILE, delay, yield or string formatting occur in this recorder.
enum class Kind : std::uint8_t { Request, Acquired, TakeFailed, SdkReturn, GiveBegin, GiveEnd, AdsBegin, AdsEnd };
enum Flag : std::uint8_t { Success=1, SdkEntered=2, Anomaly=4 };
inline constexpr std::uint8_t unavailable = 255;
struct Stamp {
    std::uint64_t us = 0;
    std::uint32_t tick = 0;
    std::uint8_t task = unavailable, priority = unavailable, core = unavailable, holder = unavailable;
};
struct Event {
    std::uint64_t us = 0;
    std::uint32_t seq = 0, request = 0, generation = 0, tick = 0, link = 0, previous_release = 0;
    std::uint32_t wait_us = 0, wait_ticks = 0, budget_ticks = 0, ads_request = 0, owner_generation = 0;
    std::int32_t result = 0;
    std::uint16_t length = 0;
    Kind kind = Kind::Request;
    std::uint8_t task = unavailable, priority = unavailable, core = unavailable, holder = unavailable;
    std::uint8_t owner_priority = unavailable, address = 0, reg = 0, operation = '?';
    std::uint8_t channel = unavailable, stage = 0, flags = 0;
};
static_assert(sizeof(Event) <= 80, "Reassess internal RAM/critical-copy cost if event grows");
struct Request {
    Stamp started{};
    drivers::I2cTraceOperation operation{};
    std::uint32_t id = 0, request_seq = 0, generation = 0, acquire_seq = 0, give_seq = 0;
    std::uint32_t budget = 0, ads = 0;
    std::uint8_t channel = unavailable, stage = 0;
    bool selected = false, taken = false, intentionally_filtered = false;
    std::uint16_t slot = std::numeric_limits<std::uint16_t>::max();
};

struct Owner { std::uint32_t request=0, generation=0, acquired_seq=0; std::uint8_t priority=unavailable; };
struct Summary {
    std::size_t selected=0, history=0, anomalies=0;
    std::uint32_t trace_overflow=0, history_evicted=0, last_seq=0;
    std::uint32_t requests=0, generations=0, first_anomaly=0, active=0, metadata_errors=0;
    bool sealed=false, id_exhausted=false;
    std::uint32_t filtered_events=0, anomalies_total=0, anomalies_outside_window=0;
    std::uint32_t incomplete_requests=0;
    bool ads_active=false;
};

// V2: complete request bundles, not an ever-growing union of early/ADS/long
// wait selections. Keep the latest 24 requests until first anomaly, then freeze
// those slots and admit 24 more requests. All admitted in-flight requests keep
// their tail even after admission closes. No evicting active request bundles.
class FiniteTrace {
public:
    static constexpr std::size_t pre_requests=24, post_requests=24, request_capacity=pre_requests+post_requests;
    static constexpr std::size_t selected_capacity=request_capacity*5, history_capacity=request_capacity*2;
    static constexpr std::size_t prehistory_capacity=pre_requests*5, anomaly_capacity=selected_capacity;
    static constexpr std::uint64_t long_wait_us=2000;
    static constexpr std::uint32_t mutex_id=1;
    explicit FiniteTrace(std::uint32_t sequence_seed=0,std::uint32_t request_seed=0,std::uint32_t generation_seed=0)
        : sequence_(sequence_seed),requests_(request_seed),generations_(generation_seed) {}
    void begin(std::uint64_t epoch) { if(!epoch_) {epoch_=epoch;enabled_=true;} }
    bool recording() const {return enabled_ && !sealed_;}
    Request request(Stamp s,drivers::I2cTraceOperation op,std::uint32_t budget,std::uint8_t stage) {
        Request r{};if(!recording())return r;
        r.id=next(requests_);if(!r.id)return r;
        r.started=s;r.operation=op;r.budget=budget;r.stage=stage;
        if(op.address==0x48){r.ads=ads_;r.channel=channel_;}
        r.slot=reserve();r.selected=r.slot<request_capacity;
        r.intentionally_filtered=!r.selected && first_anomaly_ && post_used_==post_requests;
        if(r.selected){bundles_[r.slot]={};bundles_[r.slot].id=r.id;}
        ++active_;
        auto e=event(r,s,Kind::Request);e.owner_generation=owner_.generation;e.owner_priority=owner_.priority;
        r.request_seq=put(e,r);return r;
    }
    void returned(Request& r,Stamp s,bool taken) {
        if(!r.id || !recording())return;
        r.taken=taken;auto e=event(r,s,taken?Kind::Acquired:Kind::TakeFailed);
        e.link=r.request_seq;e.wait_us=elapsed(s.us,r.started.us);e.wait_ticks=s.tick-r.started.tick;
        e.owner_generation=owner_.generation;e.owner_priority=owner_.priority;
        if(taken){r.generation=next(generations_);e.generation=r.generation;e.flags|=Success;e.previous_release=owner_.generation?0:last_release_;}
        else e.result=263;
        r.acquire_seq=put(e,r,!taken || e.wait_us>=long_wait_us);
        if(taken)owner_={r.id,r.generation,r.acquire_seq,s.priority};
        else {close(r);if(active_)--active_;}
    }
    void sdk_return(const Request& r,Stamp s,std::int32_t result,bool entered) {
        if(!r.id || !recording())return;
        auto e=event(r,s,Kind::SdkReturn);e.link=r.acquire_seq;e.result=result;
        if(entered)e.flags|=SdkEntered;
        if(result==0)e.flags|=Success;
        if(r.ads && entered)ads_sdk_entered_=true;
        put(e,r,result!=0);
    }
    void give_begin(Request& r,Stamp s) {
        if(!r.id || !recording())return;
        const bool mismatch=!r.taken || !r.generation || owner_.generation!=r.generation;
        if(mismatch)increment(metadata_errors_);
        auto e=event(r,s,Kind::GiveBegin);e.link=r.acquire_seq;r.give_seq=put(e,r,mismatch);
    }
    void give_end(const Request& r,Stamp s,bool gave) {
        if(!r.id || !recording())return;
        auto e=event(r,s,Kind::GiveEnd);e.link=r.give_seq;e.result=gave?1:0;if(gave)e.flags|=Success;
        const auto seq=put(e,r,!gave);
        if(gave){if(r.generation>last_released_generation_){last_released_generation_=r.generation;last_release_=seq;}
            if(owner_.generation==r.generation)owner_={};}
        close(r);if(active_)--active_;
    }
    void ads_begin(Stamp s,std::uint8_t channel) {
        if(!recording())return;
        if(ads_)increment(metadata_errors_);
        ads_=next(ads_counter_);channel_=channel;ads_sdk_entered_=false;
        ads_slot_=std::numeric_limits<std::uint16_t>::max();ads_filtered_=false;
        if(!first_anomaly_){
            ads_slot_=ads_next_;ads_next_=(ads_next_+1)%pre_requests;
            if(ads_context_[ads_slot_].id){increment(filtered_,ads_context_[ads_slot_].ended?2:1);}
        }else if(post_used_<post_requests && ads_post_used_<post_requests){ads_slot_=pre_requests+ads_post_used_++;}
        else ads_filtered_=post_used_==post_requests;
        if(ads_slot_<ads_context_.size()){ads_context_[ads_slot_]={};ads_context_[ads_slot_].id=ads_;}
        Request r{};r.ads=ads_;r.channel=channel_;r.operation.address=0x48;
        auto e=event(r,s,Kind::AdsBegin);e.seq=next(sequence_);
        if(ads_slot_<ads_context_.size() && e.seq)ads_context_[ads_slot_].begin=e;
        else if(ads_filtered_)increment(filtered_);else increment(overflow_);
    }
    void ads_end(Stamp s,std::int32_t error,std::uint8_t status) {
        if(!recording())return;
        Request r{};r.ads=ads_;r.channel=channel_;r.operation.address=0x48;
        auto e=event(r,s,Kind::AdsEnd);e.seq=next(sequence_);e.result=error;e.stage=status;
        if(!error)e.flags|=Success;
        if(ads_sdk_entered_)e.flags|=SdkEntered;
        if(error){e.flags|=Anomaly;anomaly(e.seq,ads_slot_<ads_context_.size());}
        if(ads_slot_<ads_context_.size() && e.seq){ads_context_[ads_slot_].end=e;ads_context_[ads_slot_].ended=true;}
        else if(ads_filtered_)increment(filtered_);else increment(overflow_);
        ads_=0;channel_=unavailable;
    }
    void seal(){sealed_=true;}
    Summary summary() const {
        Summary s{};for(const auto& b:bundles_)for(unsigned i=0;i<b.count;++i){++s.selected;if(b.events[i].flags&Anomaly)++s.anomalies;}
        for(const auto& a:ads_context_)if(a.id && a.begin.seq){s.history+=a.ended?2:1;if(a.ended && (a.end.flags&Anomaly))++s.anomalies;}
        s.trace_overflow=overflow_;s.history_evicted=evicted_;s.last_seq=sequence_;s.requests=requests_;s.generations=generations_;
        s.first_anomaly=first_anomaly_;s.active=active_;s.metadata_errors=metadata_errors_;s.sealed=sealed_;s.id_exhausted=id_exhausted_;
        s.filtered_events=filtered_;s.anomalies_total=anomalies_;s.anomalies_outside_window=anomalies_outside_;
        s.ads_active=ads_!=0;
        for(const auto& b:bundles_)if(b.id) {
            const bool failed=b.count==2 && b.events[1].kind==Kind::TakeFailed;
            const bool taken=b.count==5 && b.events[1].kind==Kind::Acquired && b.events[2].kind==Kind::SdkReturn && b.events[3].kind==Kind::GiveBegin && b.events[4].kind==Kind::GiveEnd;
            if(!b.closed || b.events[0].kind!=Kind::Request || (!failed && !taken))++s.incomplete_requests;
        }
        return s;
    }
    // Dense immutable views after seal. Bank0=request lifecycles, bank1=ADS
    // contexts; bank2 is a derived anomaly view, NOT a duplicated storage pool.
    bool get(unsigned bank,std::size_t i,Event& out) const {
        if(bank==0){for(const auto& b:bundles_){if(i<b.count){out=b.events[i];return true;}i-=b.count;}}
        else if(bank==1){for(const auto& a:ads_context_)if(a.id && a.begin.seq){if(!i--){out=a.begin;return true;}if(a.ended && !i--){out=a.end;return true;}}}
        else if(bank==2){for(const auto& b:bundles_)for(unsigned n=0;n<b.count;++n)if((b.events[n].flags&Anomaly) && !i--){out=b.events[n];return true;}
            for(const auto& a:ads_context_)if(a.ended && (a.end.flags&Anomaly) && !i--){out=a.end;return true;}}
        return false;
    }
    // Raw unavailable references remain visible. A previous-release before
    // the retained window is reported separately, never silently nulled out.
    std::uint32_t missing_links() const {
        std::uint32_t n=0;for(const auto& b:bundles_)for(unsigned i=0;i<b.count;++i){const auto& e=b.events[i];
            if(e.link && !contains(e.link))++n;
            if(e.previous_release && !contains(e.previous_release))++n;
            if(e.owner_generation && !contains_generation(e.owner_generation))++n;
            if(e.kind==Kind::Request && e.ads_request && !contains_ads(e.ads_request))++n;}
        return n;
    }
    std::uint32_t boundary_links() const {
        const auto first=first_seq();std::uint32_t n=0;
        for(const auto& b:bundles_)for(unsigned i=0;i<b.count;++i){const auto& e=b.events[i];
            if(e.previous_release && e.previous_release<first && !contains(e.previous_release))++n;}
        return n;
    }
private:
    struct Bundle {std::array<Event,5> events{};std::uint32_t id=0;std::uint8_t count=0;bool closed=false;};
    struct Ads {Event begin{},end{};std::uint32_t id=0;bool ended=false;};
    static void increment(std::uint32_t& n,std::uint32_t by=1){n=by>std::numeric_limits<std::uint32_t>::max()-n?std::numeric_limits<std::uint32_t>::max():n+by;}
    std::uint32_t next(std::uint32_t& n){if(n==std::numeric_limits<std::uint32_t>::max()){id_exhausted_=true;return 0;}return ++n;}
    std::uint16_t reserve(){
        if(first_anomaly_){if(post_used_<post_requests)return static_cast<std::uint16_t>(pre_requests+post_used_++);return std::numeric_limits<std::uint16_t>::max();}
        for(unsigned n=0;n<pre_requests;++n){const auto i=pre_next_;pre_next_=(pre_next_+1)%pre_requests;
            if(!bundles_[i].id || bundles_[i].closed){increment(evicted_,bundles_[i].count);increment(filtered_,bundles_[i].count);return static_cast<std::uint16_t>(i);}}
        return std::numeric_limits<std::uint16_t>::max();
    }
    void close(const Request& r){if(r.slot<request_capacity && bundles_[r.slot].id==r.id)bundles_[r.slot].closed=true;}
    void anomaly(std::uint32_t seq,bool retained){increment(anomalies_);if(!first_anomaly_)first_anomaly_=seq;if(!retained)increment(anomalies_outside_);}
    std::uint32_t put(Event e,const Request& r,bool is_anomaly=false){
        e.seq=next(sequence_);if(!e.seq)return 0;
        const bool retained=r.slot<request_capacity && bundles_[r.slot].id==r.id;
        if(is_anomaly){e.flags|=Anomaly;anomaly(e.seq,retained);}
        if(retained){auto& b=bundles_[r.slot];if(b.count<b.events.size())b.events[b.count++]=e;else increment(overflow_);}
        else if(r.intentionally_filtered)increment(filtered_);else increment(overflow_);
        return e.seq;
    }
    static std::uint32_t elapsed(std::uint64_t e,std::uint64_t b){return e>=b && e-b<=std::numeric_limits<std::uint32_t>::max()?static_cast<std::uint32_t>(e-b):std::numeric_limits<std::uint32_t>::max();}
    Event event(const Request& r,Stamp s,Kind k) const {
        Event e{};e.us=s.us;e.tick=s.tick;e.kind=k;e.request=r.id;e.generation=r.generation;e.task=s.task;e.priority=s.priority;e.core=s.core;e.holder=s.holder;
        e.address=r.operation.address;e.reg=r.operation.reg;e.length=r.operation.length;e.operation=r.operation.operation;e.budget_ticks=r.budget;e.ads_request=r.ads;e.channel=r.channel;e.stage=r.stage;return e;
    }
    bool contains(std::uint32_t seq) const {for(const auto& b:bundles_)for(unsigned i=0;i<b.count;++i)if(b.events[i].seq==seq)return true;return false;}
    bool contains_generation(std::uint32_t g) const {for(const auto& b:bundles_)for(unsigned i=0;i<b.count;++i)if(b.events[i].kind==Kind::Acquired && b.events[i].generation==g)return true;return false;}
    bool contains_ads(std::uint32_t id) const {for(const auto& a:ads_context_)if(a.id==id && a.begin.seq)return true;return false;}
    std::uint32_t first_seq() const {std::uint32_t first=0;for(const auto& b:bundles_)for(unsigned i=0;i<b.count;++i)if(!first || b.events[i].seq<first)first=b.events[i].seq;return first;}
    std::array<Bundle,request_capacity> bundles_{};
    std::array<Ads,request_capacity> ads_context_{};
    unsigned pre_next_=0,post_used_=0,ads_next_=0,ads_post_used_=0;
    std::uint16_t ads_slot_=std::numeric_limits<std::uint16_t>::max();
    std::uint32_t sequence_=0,requests_=0,generations_=0,first_anomaly_=0,active_=0,metadata_errors_=0;
    std::uint32_t overflow_=0,filtered_=0,evicted_=0,anomalies_=0,anomalies_outside_=0;
    std::uint32_t ads_counter_=0,ads_=0,last_release_=0,last_released_generation_=0;
    std::uint8_t channel_=unavailable;std::uint64_t epoch_=0;Owner owner_{};
    bool enabled_=false,sealed_=false,id_exhausted_=false,ads_sdk_entered_=false,ads_filtered_=false;
};
static_assert(sizeof(FiniteTrace)<32000,"Do not grow the former 48.5KiB recorder");
inline const char* kind_name(Kind k) {
    switch(k){case Kind::Request:return "REQUEST";case Kind::Acquired:return "ACQUIRED";
    case Kind::TakeFailed:return "TAKE_FAILED";case Kind::SdkReturn:return "SDK_RETURN";
    case Kind::GiveBegin:return "GIVE_BEGIN";case Kind::GiveEnd:return "GIVE_END";
    case Kind::AdsBegin:return "ADS_BEGIN";case Kind::AdsEnd:return "ADS_END";}
    return "UNKNOWN";
}
}
