#include "node/storage_latency.hpp"
#include <cassert>
#include <cstdio>

// TEST_ONLY clock inputs; no SD hardware or operating-system sleep.
int main() {
    using namespace node::runtime::policy;
    LatencyHistogram empty;
    assert(!empty.quantile(50).available);
    for(unsigned i=1;i<=100;++i) empty.observe(i*1000);
    const auto p50=empty.quantile(50),p95=empty.quantile(95),p99=empty.quantile(99);
    assert(p50.available && p50.lower_us==32001 && p50.upper_us==64000);
    assert(p95.lower_us==64001 && p95.upper_us==100000 && p99.upper_us==100000);
    assert(!empty.quantile(0).available && !empty.quantile(101).available);
    LatencyHistogram tails;
    for(auto us:{100000U,100001U,300000U,300001U,500000U,500001U,2000000U}) tails.observe(us);
    assert(tails.samples()==7 && tails.over100()==6 && tails.over300()==4 && tails.over500()==2);
    const auto huge=tails.quantile(99);assert(huge.unbounded && huge.lower_us==1000001 && huge.upper_us==0);
    StorageLatency trace;
    const auto recover=trace.begin(0,100,0,0);
    const auto open=trace.begin(1,150,0,0);
    trace.end(open,250,0,true);
    // Production recover() -> open_next(): open end must preserve outer context.
    assert(trace.active_operation()==0 && trace.active_started()==100);
    trace.end(recover,300,0,true);
    assert(trace.active_operation()==7 && trace.context_errors()==0);
    for(unsigned i=0;i<20;++i) {
        const auto span=trace.begin(2,1000000ULL+i*1000000ULL,100+i,7);
        trace.end(span,span.started_us+708202,147,true,{500,707689,0,0,150,true},3,0);
        trace.attach_action(3);
    }
    assert(trace.total_events()==20 && trace.overwritten_history()==4 && !trace.event(1));
    assert(trace.event(5) && trace.event(20) && trace.event(20)->phases.accepted_bytes==150);
    assert(trace.event(20)->queue_before==119 && trace.event(20)->queue_after==147 && trace.event(20)->action==3);
    StorageLatency snapshot;trace.copy_into(snapshot);
    const auto next=trace.begin(3,30000000,147,7);trace.end(next,30153859,110,true,{0,0,18000,135000,0,true});
    assert(snapshot.total_events()==20 && trace.total_events()==21);
    assert(trace.append().samples()==20 && trace.flush().samples()==1);
    const auto idle=trace.begin(6,40000000,0,7);trace.end(idle,41000000,0,true);
    assert(trace.total_events()==21); // blocking empty-queue wait is not SD latency
    const auto invalid=trace.begin(2,50000000,0,7);trace.end(invalid,49999999,0,false);
    assert(trace.context_errors()==1 && trace.append().samples()==20);
    std::puts("HOST_STORAGE_LATENCY_TEST_PASS (TEST_ONLY fixed ring/histogram intervals/nested recover-open/eviction; CPU/card timing HARDWARE_NOT_RUN)");
}
