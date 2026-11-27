#include "node/imu_irq_policy.hpp"
#include <cassert>
#include <cstdint>
#include <limits>

int main() {
    using node::drivers::ImuIrqGate;
    ImuIrqGate failed, peer;
    assert(!failed.may_arm() && !failed.may_notify());
    failed.arm_result(true); // a GPIO call alone cannot authorize an unready sensor
    assert(!failed.may_notify());
    failed.initialized(false);
    peer.initialized(true);
    assert(peer.may_arm() && !peer.may_notify());
    peer.arm_result(false); // failed stale-status/GPIO enable stays polling-only
    assert(!peer.may_notify());
    peer.arm_result(true);
    assert(peer.may_notify());
    unsigned unready_notifications = 0, ready_notifications = 0;
    for (unsigned edge = 0; edge < 40799; ++edge) {
        if (failed.may_notify()) ++unready_notifications;
        if (peer.may_notify()) ++ready_notifications;
    }
    assert(unready_notifications == 0 && ready_notifications == 40799);
    // may_notify remains the armed-state observation, not a notification
    // budget. Raw ISR edges remain visible during a storm; claim_notification
    // below coalesces only the task notification within each service frame.
    peer.begin_capture(3107);
    assert(peer.startup_edges() == 3107);
    assert(peer.capture_edges(15180) == 12073);
    assert(peer.startup_edges() == 3107); // lifetime evidence is not reset
    peer.stop();
    assert(!peer.may_notify());
    peer.initialized(false);
    peer.arm_result(true);
    assert(!peer.may_notify());
    peer.initialized(true);
    assert(!peer.may_notify()); // a new init must explicitly rearm
    peer.begin_capture(std::numeric_limits<std::uint32_t>::max() - 1);
    assert(peer.capture_edges(1) == 3);

    // TEST_ONLY: the caller models the ISR's raw count BEFORE asking whether
    // to notify. Notification coalescence never changes that lifetime count.
    ImuIrqGate storm;
    storm.initialized(true); storm.arm_result(true); storm.begin_capture(0);
    std::uint32_t raw_edges = 0, sent = 0, coalesced = 0;
    for (unsigned frame = 0; frame < 1000; ++frame) {
        storm.begin_service_frame();
        for (unsigned edge = 0; edge < 200; ++edge) {
            ++raw_edges;
            assert(storm.may_notify()); // ready/armed does not turn off on quota use
            if (storm.claim_notification()) ++sent;
            else ++coalesced;
        }
    }
    assert(raw_edges == 200000 && sent == 1000 && coalesced == 199000);
    assert(storm.capture_edges(raw_edges) == raw_edges);
    assert(sent + coalesced == raw_edges);

    // A normal one-edge-per-frame source keeps every notification. TOP's
    // repeated edges cannot consume TOE's independent notification budget.
    ImuIrqGate top, toe;
    top.initialized(true); top.arm_result(true);
    toe.initialized(true); toe.arm_result(true);
    unsigned top_sent = 0, toe_sent = 0, top_raw = 0, toe_raw = 0;
    for (unsigned frame = 0; frame < 100; ++frame) {
        top.begin_service_frame(); toe.begin_service_frame();
        for (unsigned edge = 0; edge < 400; ++edge) {
            ++top_raw;
            if (top.claim_notification()) ++top_sent;
        }
        ++toe_raw;
        if (toe.claim_notification()) ++toe_sent;
        assert(!top.claim_notification() && !toe.claim_notification());
    }
    assert(top_raw == 40000 && toe_raw == 100);
    assert(top_sent == 100 && toe_sent == 100);

    // Lifecycle operations clear the old latch but cannot authorize an
    // uninitialized/unarmed sensor. A frame reset never rearms a stopped pin.
    ImuIrqGate lifecycle;
    lifecycle.begin_service_frame();
    assert(!lifecycle.claim_notification());
    lifecycle.arm_result(true);
    assert(!lifecycle.claim_notification());
    lifecycle.initialized(true);
    assert(!lifecycle.claim_notification());
    lifecycle.arm_result(true);
    assert(lifecycle.claim_notification() && !lifecycle.claim_notification());
    lifecycle.begin_service_frame();
    assert(lifecycle.claim_notification() && !lifecycle.claim_notification());
    lifecycle.stop();
    assert(!lifecycle.may_notify() && !lifecycle.claim_notification());
    lifecycle.begin_service_frame();
    assert(!lifecycle.claim_notification());
    lifecycle.arm_result(true); // ready site may explicitly arm again
    assert(lifecycle.claim_notification());
    lifecycle.arm_result(false);
    assert(!lifecycle.claim_notification());
    lifecycle.arm_result(true);
    assert(lifecycle.claim_notification() && !lifecycle.claim_notification());
    lifecycle.initialized(false);
    lifecycle.begin_service_frame(); lifecycle.arm_result(true);
    assert(!lifecycle.may_arm() && !lifecycle.claim_notification());
    lifecycle.initialized(true);
    assert(!lifecycle.claim_notification());
    lifecycle.arm_result(true);
    assert(lifecycle.claim_notification() && !lifecycle.claim_notification());
}
