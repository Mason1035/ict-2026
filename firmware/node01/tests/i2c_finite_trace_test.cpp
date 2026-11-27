#include "node/i2c_finite_trace.hpp"
#include <cassert>
#include <algorithm>
#include <cstdint>
#include <iostream>
#include <limits>
#include <vector>
using namespace node::runtime::lock_diagnostic;
using node::drivers::I2cTraceOperation;
Stamp stamp(std::uint64_t us,std::uint8_t task=0,std::uint8_t holder=254) {
    return {us,static_cast<std::uint32_t>(us/10000),task,static_cast<std::uint8_t>(task==3?5:7),1,holder};
}
std::vector<Event> events(const FiniteTrace& t,unsigned bank=0) {
    std::vector<Event> value;Event e{};
    for(std::size_t i=0;t.get(bank,i,e);++i)value.push_back(e);
    std::sort(value.begin(),value.end(),[](const Event& a,const Event& b){return a.seq<b.seq;});
    return value;
}
void finish(FiniteTrace& t,Request& r,std::uint64_t us,bool gave=true) {
    t.sdk_return(r,stamp(us),0,true);
    t.give_begin(r,stamp(us+1));t.give_end(r,stamp(us+2),gave);
}
int main() {
    const I2cTraceOperation imu{1,0x68,0x2d,'R'},soil{2,0x48,0x01,'R'};
    {
        FiniteTrace t;auto r=t.request(stamp(100),imu,2,0);
        assert(r.id==0 && t.summary().last_seq==0); // unarmed: no diagnostic events
        t.begin(1000);r=t.request(stamp(1001),imu,2,0);t.returned(r,stamp(1002),true);finish(t,r,1003);t.seal();
        const auto v=events(t);assert(v.size()==5);
        assert(v[0].kind==Kind::Request && v[1].kind==Kind::Acquired && v[2].kind==Kind::SdkReturn);
        assert(v[3].kind==Kind::GiveBegin && v[4].kind==Kind::GiveEnd);
        assert(v[1].link==v[0].seq && v[3].link==v[1].seq && v[4].link==v[3].seq);
        assert(v[1].generation && v[1].generation==v[4].generation);
        assert(t.summary().active==0 && t.missing_links()==0);
        assert((v[2].flags & SdkEntered) && (v[4].flags & Success));
        auto after=t.request(stamp(2000),imu,2,0);assert(after.id==0);
    }
    {
        FiniteTrace t;t.begin(1000);
        auto holder=t.request(stamp(1001),imu,2,0);t.returned(holder,stamp(1002),true);
        auto waiter=t.request(stamp(1010,3,0),soil,2,2);
        t.sdk_return(holder,stamp(1020),0,true);t.give_begin(holder,stamp(1021));
        // Give can preempt: another generation acquired before old Give returns.
        t.returned(waiter,stamp(1022,3,3),true);
        t.give_end(holder,stamp(1023),true);finish(t,waiter,1030);
        assert(waiter.generation!=holder.generation);
        assert(t.summary().metadata_errors==0 && t.summary().active==0 && t.missing_links()==0);
        for(const auto&e:events(t))if(e.kind==Kind::Acquired && e.request==waiter.id)assert(e.previous_release==0);
    }
    {
        FiniteTrace t;t.begin(1000);
        auto a=t.request(stamp(1001),imu,2,0);t.returned(a,stamp(1002),true);
        auto b=t.request(stamp(1003,3,0),soil,2,2);
        t.give_begin(a,stamp(1004));t.returned(b,stamp(1005,3,3),true);finish(t,b,1006);
        const auto release_b=events(t).back().seq;
        t.give_end(a,stamp(1010),true);
        auto c=t.request(stamp(1011),imu,2,0);t.returned(c,stamp(1012),true);
        assert(events(t).back().previous_release==release_b);
        finish(t,c,1013);assert(t.summary().metadata_errors==0);
    }
    {
        FiniteTrace t;t.begin(1000);
        auto a=t.request(stamp(1001),imu,2,0);t.returned(a,stamp(1002),true);
        auto b=t.request(stamp(1003,3,0),soil,2,2);
        t.returned(b,stamp(12345,3,0),false);finish(t,a,12350);t.seal();
        const auto anomalies=events(t,2);assert(anomalies.size()==1);
        assert(anomalies[0].kind==Kind::TakeFailed && anomalies[0].request==b.id);
        assert(anomalies[0].wait_us==11342 && anomalies[0].wait_ticks==1 && anomalies[0].budget_ticks==2);
        assert(anomalies[0].owner_generation==a.generation);
        assert(!(anomalies[0].flags & SdkEntered) && anomalies[0].result==263);
        for(const auto&e:events(t))assert(!(e.request==b.id && (e.kind==Kind::SdkReturn || e.kind==Kind::GiveBegin)));
    }
    {
        FiniteTrace t;t.begin(1000);
        auto a=t.request(stamp(1001),imu,2,0);t.returned(a,stamp(1002),true);
        auto b=t.request(stamp(1003,3,0),soil,2,2);finish(t,a,1010);
        auto a2=t.request(stamp(1015),imu,2,0);t.returned(a2,stamp(1016),true);
        t.returned(b,stamp(12345,3,0),false);finish(t,a2,12350);
        assert(a2.generation>a.generation && a2.id!=a.id);
        for(const auto&e:events(t,2))assert(e.owner_generation==a2.generation);
    }
    {
        FiniteTrace t;t.begin(1000);auto a=t.request(stamp(1001),imu,2,0);t.returned(a,stamp(1002),true);
        finish(t,a,1010,false);assert(t.summary().first_anomaly && events(t,2).size()==1);
        assert(!(events(t,2)[0].flags & Success));
    }
    {
        FiniteTrace t;t.begin(1000);auto a=t.request(stamp(1001),imu,2,0);t.returned(a,stamp(1002),true);
        ++a.generation;t.give_begin(a,stamp(1003));assert(t.summary().metadata_errors==1);
    }
    {
        FiniteTrace t;t.begin(1000);
        for(unsigned i=0;i<100;++i){auto a=t.request(stamp(1001+i*10),imu,2,0);t.returned(a,stamp(1002+i*10),true);finish(t,a,1003+i*10);}
        assert(t.summary().selected==FiniteTrace::prehistory_capacity && t.summary().trace_overflow==0);
        assert(t.summary().filtered_events>0 && t.summary().first_anomaly==0);
        // A later timeout freezes intact recent requests, then retains post context.
        auto b=t.request(stamp(2000000,3,0),soil,2,2);t.returned(b,stamp(2011500,3,0),false);
        assert(events(t,2).back().request==b.id && events(t,2).back().result==263);
        assert(t.summary().history<=FiniteTrace::history_capacity);
        t.seal(); // bounded reference scan explicitly detects missing selected links if any
        assert(t.summary().history_evicted>0);
    }
    {
        FiniteTrace t;t.begin(1000);
        for(unsigned i=0;i<9;++i){const auto us=2000000ULL+i*500000;
            t.ads_begin(stamp(us,3),static_cast<std::uint8_t>(i%3));auto a=t.request(stamp(us+1,3),soil,2,2);
            t.returned(a,stamp(us+2,3,3),true);finish(t,a,us+3);t.ads_end(stamp(us+6,3),0,4);}
        unsigned starts=0;for(const auto&e:events(t,1))if(e.kind==Kind::AdsBegin){++starts;assert(e.ads_request>=1 && e.ads_request<=9);}
        assert(starts==9); // recent request contexts retained together, not arbitrary first-eight selection
        for(const auto&e:events(t))assert(e.channel<3 || e.channel==unavailable);
    }
    {
        FiniteTrace t(std::numeric_limits<std::uint32_t>::max()-2);t.begin(1000);
        auto a=t.request(stamp(1001),imu,2,0);t.returned(a,stamp(1002),true);finish(t,a,1003);
        assert(t.summary().id_exhausted && t.summary().last_seq==std::numeric_limits<std::uint32_t>::max());
        for(const auto&e:events(t))assert(e.seq!=0);
        FiniteTrace ids(0,std::numeric_limits<std::uint32_t>::max());ids.begin(1000);
        assert(ids.request(stamp(1001),imu,2,0).id==0 && ids.summary().id_exhausted);
    }
    std::cout<<"HOST_I2C_FINITE_TRACE_TEST_PASS TEST_ONLY ordered lifecycles/contention/timeouts/give-failure/generations/caps/ID-exhaustion; sizeof(Event)="<<sizeof(Event)<<" sizeof(Recorder)="<<sizeof(FiniteTrace)<<" hardware NOT_RUN\n";
}
