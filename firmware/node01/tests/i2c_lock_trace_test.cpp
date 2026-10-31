#include "node/i2c_lock_trace.hpp"
#include "node/runtime_policy.hpp"
#include "node/timeout_budget.hpp"
#include "esp_err.h"
#include <cassert>
#include <cstdio>

int main() {
    using namespace node::runtime::policy;
    static_assert(node::drivers::timing::guarded_wait_ticks(10,100)==2);
    I2cLockTrace trace;
    const auto owner=trace.acquired(100,68,7);
    const auto wait=trace.before_wait(150,48,5);
    unsigned sdk=0,give=0;
    const auto error=locked_transaction([]{return false;},[&]{++give;},[&]{++sdk;return ESP_OK;},ESP_ERR_TIMEOUT);
    trace.timeout(wait,11251,68);
    assert(error==ESP_ERR_TIMEOUT && !sdk && !give);
    assert(trace.first().wait.owner_before.task==68 && trace.first().kernel_holder_after==68);
    assert(trace.first().finished_us-trace.first().wait.started_us==11101);
    trace.before_give(owner,11500,7);trace.released(owner,true);
    assert(trace.max_observed_hold_us()==11400 && trace.owner().task==0);
    // A Give can immediately preempt to a higher-priority waiter. Late metadata
    // cleanup by the old task must not erase the new ownership generation.
    const auto old=trace.acquired(12000,48,5);
    trace.before_give(old,12100,7); // injected priority observation, not RTOS PI proof
    const auto handoff=trace.acquired(12101,68,7);
    trace.released(old,true);
    assert(trace.owner().generation==handoff && trace.owner().task==68);
    trace.before_give(handoff,12200,7);trace.released(handoff,true);
    const auto second=trace.before_wait(13000,48,5);trace.timeout(second,24000,0);
    assert(trace.timeouts()==2 && trace.first().wait.started_us==150 && trace.last().wait.started_us==13000);
    const auto recover=trace.acquired(25000,48,5);trace.before_give(recover,25500,5);trace.released(recover,true);
    I2cLockTrace snapshot;trace.copy_into(snapshot);
    assert(snapshot.acquisitions()==4 && snapshot.releases()==4 && snapshot.give_failures()==0 && snapshot.metadata_errors()==0);
    const auto failed=trace.acquired(26000,48,5);trace.before_give(failed,26100,5);trace.released(failed,false);
    assert(trace.give_failures()==1 && trace.owner().task==48 && snapshot.give_failures()==0);
    std::puts("HOST_I2C_LOCK_TRACE_TEST_PASS (TEST_ONLY ownership generations/local timeout/handoff; actual FreeRTOS priority inheritance HARDWARE_NOT_RUN)");
}
