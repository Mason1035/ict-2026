#include "node/i2c_trace_output.hpp"
#include <cassert>
#include <fstream>
#include <iostream>
#include <iterator>
#include <limits>
#include <mutex>
#include <string>
#include <thread>
#include <vector>
using namespace node::runtime::lock_diagnostic;
const node::drivers::I2cTraceOperation imu{1,0x68,0x2d,'R'},soil{2,0x48,0x01,'R'};
Stamp at(std::uint64_t us,std::uint8_t task=0){return {us,static_cast<std::uint32_t>(us/10000),task,static_cast<std::uint8_t>(task==3?5:7),1,254};}
void done(FiniteTrace& t,Request& r,std::uint64_t us,bool give=true){t.sdk_return(r,at(us),0,true);t.give_begin(r,at(us+1));t.give_end(r,at(us+2),give);}
Request request(FiniteTrace& t,std::uint64_t us){auto r=t.request(at(us),imu,2,0);t.returned(r,at(us+1),true);return r;}
std::vector<Event> retained(const FiniteTrace& t){std::vector<Event> es;Event e{};for(unsigned b=0;b<2;++b)for(unsigned i=0;t.get(b,i,e);++i)es.push_back(e);return es;}
void normal_and_empty(){
    FiniteTrace empty;empty.begin(1);empty.seal();TraceOutput out;
    assert(out.begin(empty,8));unsigned lines=0;std::uint64_t clock=0;
    assert(out.pump([&](const OutputLine& l){assert(l.kind==OutputKind::Begin || l.kind==OutputKind::End);++lines;},[&]{return clock;})==2);
    assert(lines==2 && !out.pending() && !out.begin(empty,8));
    FiniteTrace steady;steady.begin(1);
    for(unsigned i=0;i<12000;++i){auto r=request(steady,10ULL+i*2000);done(steady,r,20ULL+i*2000);}
    auto s=steady.summary();assert(s.first_anomaly==0 && s.trace_overflow==0 && s.selected==120 && s.filtered_events>50000);
    steady.seal();TraceOutput short_out;assert(short_out.begin(steady,8));
    unsigned events=0;while(short_out.pending())short_out.pump([&](const OutputLine& l){if(l.kind==OutputKind::Event)++events;},[&]{return clock;});
    assert(events==0 && std::string(short_out.integrity())=="SUMMARY_ONLY");
}
void first_window_and_links(){
    FiniteTrace t;t.begin(1);
    for(unsigned i=0;i<100;++i){auto r=request(t,100+i*100);done(t,r,105+i*100);}
    auto holder=request(t,11000);
    t.ads_begin(at(11002,3),0);
    auto waiter=t.request(at(11003,3),soil,2,2);
    t.returned(waiter,at(23003,3),false); // first anomaly, captured Request must exist
    done(t,holder,23004);t.ads_end(at(23007,3),263,5);
    const auto frozen_seq=t.summary().first_anomaly;
    for(unsigned i=0;i<6000;++i){auto r=request(t,24000ULL+i*5000);done(t,r,24005ULL+i*5000);}
    t.seal();const auto s=t.summary();assert(s.first_anomaly==frozen_seq && s.trace_overflow==0 && s.active==0);
    bool pre=false,fail=false,post=false,ads=false,req=false,tail=false;
    for(const auto& e:retained(t)){
        pre|=e.seq<frozen_seq;fail|=e.kind==Kind::TakeFailed && e.request==waiter.id;
        post|=e.seq>frozen_seq;ads|=e.kind==Kind::AdsBegin && e.ads_request==1;
        req|=e.kind==Kind::Request && e.request==waiter.id;
        tail|=e.kind==Kind::GiveEnd && e.generation==holder.generation;
    }
    assert(pre && fail && post && ads && req && tail);
    assert(s.selected<=FiniteTrace::selected_capacity && s.history<=FiniteTrace::history_capacity);
    assert(t.missing_links()==t.boundary_links()); // no missing lifecycle interior
    TraceOutput out;assert(out.begin(t,8));assert(std::string(out.integrity())!="INCOMPLETE");
    // Request tail remains admitted when post request budget is exhausted.
    FiniteTrace tails;tails.begin(1);auto a=request(tails,10);done(tails,a,20,false);
    std::vector<Request> active;
    for(unsigned i=0;i<FiniteTrace::post_requests;++i)active.push_back(request(tails,30+i*10));
    auto filtered=request(tails,500);done(tails,filtered,501);
    for(auto& r:active)done(tails,r,600+r.id*10);
    assert(tails.summary().active==0 && tails.summary().trace_overflow==0);
    for(auto& r:active){bool end=false;for(const auto& e:retained(tails))end|=e.request==r.id && e.kind==Kind::GiveEnd;assert(end);}
}
void overflow_missing_anomalies(){
    FiniteTrace full;full.begin(1);std::vector<Request> active;
    for(unsigned i=0;i<FiniteTrace::pre_requests+1;++i)active.push_back(full.request(at(10+i),imu,2,0));
    assert(full.summary().trace_overflow>0);full.seal();TraceOutput bad;assert(bad.begin(full,8));assert(std::string(bad.integrity())=="INCOMPLETE");
    FiniteTrace missing;missing.begin(1);auto a=missing.request(at(10),imu,2,0);a.request_seq=999999;
    missing.returned(a,at(3000),true);done(missing,a,3010);missing.seal();
    assert(missing.missing_links()>missing.boundary_links());TraceOutput partial;assert(partial.begin(missing,8));assert(std::string(partial.integrity())=="INCOMPLETE");
    FiniteTrace repeated;repeated.begin(1);
    for(unsigned i=0;i<100;++i){auto r=repeated.request(at(10+i*5000),soil,2,2);repeated.returned(r,at(3010+i*5000),false);}
    assert(repeated.summary().anomalies_total==100 && repeated.summary().anomalies_outside_window>0);
    assert(repeated.summary().first_anomaly && repeated.summary().trace_overflow==0); // selection cutoff != dropped required event
    FiniteTrace sdk_error;sdk_error.begin(1);auto r=request(sdk_error,10);sdk_error.sdk_return(r,at(20),259,true);
    assert(sdk_error.summary().first_anomaly);sdk_error.give_begin(r,at(21));sdk_error.give_end(r,at(22),true);
    FiniteTrace ids(0,std::numeric_limits<std::uint32_t>::max());ids.begin(1);assert(ids.request(at(10),imu,2,0).id==0 && ids.summary().id_exhausted);
}
void output_budgets(){
    FiniteTrace t;t.begin(1);auto r=request(t,10);done(t,r,20,false);t.seal();
    TraceOutput out;assert(out.begin(t,8));std::uint64_t clock=0,last_seq=0;unsigned begin=0,end=0,lines=0,batches=0;
    while(out.pending()){
        const auto n=out.pump([&](const OutputLine& l){
            ++lines;if(l.kind==OutputKind::Begin)++begin;if(l.kind==OutputKind::End)++end;
            if(l.kind==OutputKind::Event){assert(l.event.seq>last_seq);last_seq=l.event.seq;}
            clock+=100; // interruption simulated BETWEEN complete output lines
        },[&]{return clock;});
        assert(n>0 && n<=TraceOutput::batch_lines);++batches;clock+=1000000; // other tasks run; cursor retained
    }
    assert(begin==1 && end==1 && batches>1 && lines==15);
    TraceOutput slow;assert(slow.begin(t,8));
    const auto n=slow.pump([&](const OutputLine&){clock+=50000;},[&]{return clock;});
    assert(n==1 && slow.pending()); // cannot cancel a slow log, stops before next
    TraceOutput unsealed;FiniteTrace running;running.begin(1);assert(!unsealed.begin(running,8));
    running.ads_begin(at(10,3),0);running.seal();assert(unsealed.begin(running,8));
    assert(std::string(unsealed.integrity())=="INCOMPLETE"); // never call an open ADS context complete
}
void concurrency_and_source(){
    FiniteTrace t;t.begin(1);std::mutex recorder,bus;std::uint64_t time=10;
    auto worker=[&](std::uint8_t task){for(unsigned n=0;n<1000;++n){Request r;
        {std::lock_guard<std::mutex> lock(recorder);r=t.request(at(time+=10,task),imu,2,0);}
        bus.lock();{std::lock_guard<std::mutex> lock(recorder);t.returned(r,at(time+=10,task),true);t.sdk_return(r,at(time+=10,task),0,true);t.give_begin(r,at(time+=10,task));}
        bus.unlock();{std::lock_guard<std::mutex> lock(recorder);t.give_end(r,at(time+=10,task),true);}
    }};
    std::thread a(worker,0),b(worker,3);a.join();b.join();t.seal();
    assert(t.summary().requests==2000 && t.summary().active==0 && t.summary().metadata_errors==0 && t.summary().trace_overflow==0);
    std::ifstream f("components/node_runtime/runtime.cpp");assert(f.good());std::string s((std::istreambuf_iterator<char>(f)),{});
    assert(s.find("service_finite_i2c_trace(); // <=4")!=std::string::npos);
    assert(s.find("vTaskDelay(1); // real Blocked")!=std::string::npos);
    assert(s.find("esp_task_wdt_delete(")==std::string::npos && s.find("esp_task_wdt_reconfigure(")==std::string::npos);
    std::ifstream inc("components/node_runtime/i2c_diagnostic_runtime.inc");assert(inc.good());s.assign(std::istreambuf_iterator<char>(inc),{});
    const auto seal=s.find("finite_locked([&]{finite_i2c_trace.seal();});");
    const auto prepare=s.find("finite_output.begin");assert(seal<prepare);
    for(const auto* field:{"req=%lu","gen=%lu","owner_gen=%lu","wait_us=%lu","addr=0x%02x","stage=%u","result=%ld","flags=%u"})assert(s.find(field)!=std::string::npos);
}
int main(){normal_and_empty();first_window_and_links();overflow_missing_anomalies();output_budgets();concurrency_and_source();
    std::cout<<"HOST_I2C_TRACE_OUTPUT_PASS (TEST_ONLY 12000 normal requests, first anomaly/tails/boundary/overflow, resumable 4-line/20ms pump, threads; RTOS/WDT HARDWARE_NOT_RUN) sizeof(Recorder)="<<sizeof(FiniteTrace)<<" sizeof(Output)="<<sizeof(TraceOutput)<<"\n";}
