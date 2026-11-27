#include "node/acquisition_policy.hpp"
#include "node/imu_irq_policy.hpp"
#include "node/toe_status_trace.hpp"
#include <array>
#include <cassert>
#include <cstdint>
#include <cstdio>

// TEST_ONLY cooperative model using the production gate/cursor/frame budget.
// It injects GPIO callbacks, task notification hints and status/raw responses;
// it does not execute FreeRTOS, physical GPIO/I2C, sensor clocks or SD writes.
namespace {
using node::drivers::ImuIrqGate;
using node::runtime::policy::EdgeCursor;
using node::runtime::policy::ImuFrameBudget;

struct Site {
    ImuIrqGate gate;
    EdgeCursor cursor;
    bool initialized = false, new_data = false;
    unsigned generation = 0, last_valid_generation = 0, unread_overwrites = 0;
    int injected_status_error = 0, last_error = 0;
    std::uint32_t raw = 0, notification_claims = 0, notification_coalesced = 0, unarmed = 0;
    std::uint32_t consumed = 0, edge_coalesced = 0, irq_services = 0, stale = 0, deferred = 0;
    unsigned attempts = 0, valid = 0, unavailable = 0, error_records = 0, sdk_calls = 0;
};

struct Model {
    std::array<Site, 2> sites;
    ImuFrameBudget budget;
    unsigned notification_bits = 0;
    bool stopped = false;

    void initialize(unsigned i, bool ready) {
        auto& s = sites[i]; s.initialized = ready;
        s.gate.initialized(ready); s.gate.arm_result(ready);
        s.gate.begin_capture(s.raw);
    }
    void produce(unsigned i) {
        auto& s = sites[i];
        if (s.new_data) ++s.unread_overwrites;
        ++s.generation; s.new_data = true;
    }
    void edge(unsigned i) {
        auto& s = sites[i]; ++s.raw; // mirrors raw ISR accounting BEFORE the gate
        if (!s.gate.may_notify()) ++s.unarmed;
        else if (s.gate.claim_notification()) {
            ++s.notification_claims; notification_bits |= 1U << i;
        } else ++s.notification_coalesced;
    }
    void read(unsigned i) {
        auto& s = sites[i]; ++s.attempts;
        if (!s.initialized) {
            ++s.error_records; s.last_error = 259;
            return; // a not-ready software Error is NOT an SDK transaction
        }
        ++s.sdk_calls; // injected INT_STATUS response
        if (s.injected_status_error) {
            ++s.error_records; s.last_error = s.injected_status_error;
            s.injected_status_error = 0; return;
        }
        s.last_error = 0;
        if (!s.new_data) { ++s.unavailable; return; }
        ++s.sdk_calls; // only a successful data-ready status permits the raw read
        assert(s.generation > s.last_valid_generation);
        s.last_valid_generation = s.generation;
        ++s.valid; s.new_data = false;
    }
    void service_hint(unsigned i) {
        auto& s = sites[i];
        if (stopped || !s.gate.may_notify() || !s.initialized) return;
        if (!budget.may_read(i)) { ++s.deferred; return; }
        const auto delta = s.cursor.consume(s.raw);
        if (!delta) { ++s.stale; return; }
        assert(budget.claim(i)); s.consumed += delta;
        s.edge_coalesced += delta - 1;
        ++s.irq_services; read(i);
    }
    void begin_frame() {
        budget = ImuFrameBudget{};
        if (stopped) return;
        for (auto& s : sites) s.gate.begin_service_frame();
        // A latched DRDY may have arrived after the previous frame's read and
        // been notification-coalesced. A latch reset creates no new GPIO edge.
        for (unsigned i = 0; i < sites.size(); ++i)
            if (sites[i].gate.may_notify() && sites[i].cursor.pending(sites[i].raw))
                service_hint(i);
    }
    void drain_notification_hints() {
        const auto bits = notification_bits; notification_bits = 0;
        for (unsigned i = 0; i < sites.size(); ++i)
            if (bits & (1U << i)) service_hint(i);
    }
    bool fallback(unsigned i) {
        if (stopped || !budget.claim(i)) return false;
        read(i); return true;
    }
    void stop() {
        stopped = true;
        for (auto& s : sites) s.gate.stop();
    }
    void assert_accounting() const {
        for (const auto& s : sites) {
            assert(s.raw == s.notification_claims + s.notification_coalesced + s.unarmed);
            assert(s.consumed + s.cursor.pending(s.raw) == s.raw);
            assert(s.irq_services + s.edge_coalesced == s.consumed);
            assert(s.attempts == s.valid + s.unavailable + s.error_records);
        }
    }
};

void tail_edge_without_a_new_notification() {
    Model m; m.initialize(0, true); m.initialize(1, false);
    m.begin_frame();
    m.produce(0); m.edge(0); m.drain_notification_hints();
    assert(m.sites[0].valid == 1 && m.notification_bits == 0);
    // Next real observation arrives at the tail of this same service frame.
    // Its edge is counted but the one-per-frame notification latch is spent.
    m.produce(0); m.edge(0);
    assert(m.notification_bits == 0 && m.sites[0].cursor.pending(m.sites[0].raw) == 1);
    assert(m.sites[0].notification_coalesced == 1 && m.sites[0].attempts == 1);
    m.begin_frame(); // no new edge or task hint is injected in the new frame
    assert(m.sites[0].valid == 2 && m.sites[0].attempts == 2);
    assert(m.sites[0].cursor.pending(m.sites[0].raw) == 0);
    assert(!m.fallback(0)); // pending service and fallback share the quota
    m.assert_accounting();
}

void stale_hints_error_and_shared_fallback_budget() {
    Model m; m.initialize(0, true); m.initialize(1, false);
    m.begin_frame(); m.produce(0); m.edge(0); m.drain_notification_hints();
    // Simulate a delayed old eSetBits hint after its raw edge was consumed.
    m.notification_bits |= 1U;
    m.begin_frame(); m.drain_notification_hints();
    assert(m.sites[0].stale == 1 && m.sites[0].attempts == 1);
    assert(m.budget.may_read(0)); // stale hint does not spend an I2C attempt
    m.produce(0); m.edge(0); m.sites[0].injected_status_error = 259;
    m.drain_notification_hints();
    assert(m.sites[0].error_records == 1 && m.sites[0].last_error == 259);
    assert(!m.fallback(0) && m.sites[0].attempts == 2);
    assert(m.sites[0].valid == 1); // no success invented after the status failure
    // Unready TOE still gets one explicit Error when the caller requests its
    // existing polling fallback. It must not produce fake SDK traffic/Valid.
    assert(m.fallback(1) && !m.fallback(1));
    assert(m.sites[1].error_records == 1 && m.sites[1].sdk_calls == 0 && m.sites[1].valid == 0);
    m.assert_accounting();
}

void dual_sites_at_different_phases() {
    Model m; m.initialize(0, true); m.initialize(1, true);
    for (unsigned frame = 0; frame < 500; ++frame) {
        m.begin_frame();
        // Injection order represents TOP near 1ms and TOE near 6ms, without
        // claiming any real RTOS timing or sensor clock precision.
        m.produce(0); m.edge(0); m.drain_notification_hints();
        assert(m.budget.awaiting(3U));
        m.produce(1); m.edge(1); m.drain_notification_hints();
        assert(!m.budget.awaiting(3U));
        assert(!m.fallback(0) && !m.fallback(1));
    }
    for (const auto& s : m.sites) {
        assert(s.valid == 500 && s.attempts == 500 && s.sdk_calls == 1000);
        assert(s.unavailable == 0 && s.error_records == 0 && s.unread_overwrites == 0);
    }
    m.assert_accounting();
}

void noisy_top_keeps_raw_evidence_without_flooding_reads() {
    Model m; m.initialize(0, true); m.initialize(1, true);
    for (unsigned frame = 0; frame < 500; ++frame) {
        m.begin_frame();
        const auto before = m.sites[0].attempts;
        m.produce(0); m.edge(0); m.drain_notification_hints();
        for (unsigned noise = 0; noise < 200; ++noise) {
            m.edge(0); m.drain_notification_hints(); // raw callbacks, no new status data
        }
        m.produce(1); m.edge(1); m.drain_notification_hints();
        assert(m.sites[0].attempts <= before + 1);
        assert(!m.fallback(0) && !m.fallback(1));
    }
    m.begin_frame(); // drain the final unconsumed real observation, no new data
    assert(m.sites[0].raw == 100500);
    assert(m.sites[0].valid == 500 && m.sites[0].unavailable == 1);
    assert(m.sites[0].attempts == 501 && m.sites[0].sdk_calls == 1001);
    assert(m.sites[1].valid == 500 && m.sites[1].attempts == 500);
    assert(m.sites[0].unread_overwrites == 0 && m.sites[1].unread_overwrites == 0);
    m.assert_accounting();
}

void stop_keeps_late_raw_but_never_services_again() {
    Model m; m.initialize(0, true); m.initialize(1, false);
    m.begin_frame(); m.produce(0); m.edge(0); m.drain_notification_hints();
    m.produce(0); m.edge(0); // leaves an unread edge before the stop
    m.stop();
    for (unsigned edge = 0; edge < 100; ++edge) m.edge(0);
    m.begin_frame(); m.drain_notification_hints();
    assert(!m.fallback(0) && !m.fallback(1));
    assert(m.sites[0].attempts == 1 && m.sites[0].valid == 1);
    assert(m.sites[0].unarmed == 100 && m.sites[0].cursor.pending(m.sites[0].raw) == 101);
    m.assert_accounting();
}


void toe_edge_bursts_preserve_status_gate(unsigned edges_per_frame) {
    Model m;
    m.initialize(0, true);
    m.initialize(1, true);
    node::drivers::toe_trace::Trace trace;
    constexpr unsigned frames = 100;
    for (unsigned frame = 0; frame < frames; ++frame) {
        m.begin_frame();
        m.produce(0);
        m.edge(0);
        for (unsigned edge = 0; edge < edges_per_frame; ++edge) {
            m.edge(1);
            trace.note_edge({frame*10000ULL + edge, m.sites[1].raw, true});
        }
        m.drain_notification_hints();
        assert(!m.fallback(0) && !m.fallback(1));
    }
    assert(m.sites[0].valid == frames);
    assert(m.sites[1].raw == frames*edges_per_frame);
    assert(m.sites[1].attempts == frames && m.sites[1].unavailable == frames && m.sites[1].valid == 0);
    assert(m.sites[1].consumed == m.sites[1].raw);
    assert(m.sites[1].edge_coalesced == m.sites[1].raw - frames);
    assert(trace.edge_count == 128 && trace.edges.back().irq_number == 128);
    assert(node::drivers::toe_trace::Trace::rate_abnormal(m.sites[1].raw, 1000000));
    m.assert_accounting();
}

void toe_trace_is_bounded_and_keeps_first_sdk_failure() {
    using node::drivers::toe_trace::Request;
    using node::drivers::toe_trace::Trace;
    assert(!Trace::rate_abnormal(100, 1000000));
    assert(!Trace::rate_abnormal(900, 100000));
    Trace trace;
    for (unsigned i = 1; i <= 70; ++i) {
        Request r;
        r.sdk_entered = i != 35;
        r.status_present = i != 35 && i != 40 && i != 41;
        r.status = r.status_present ? 8 : 0;
        r.result = r.status_present ? 0 : 259;
        trace.note_request(r);
    }
    assert(trace.total_requests == 70 && trace.first_count == 32);
    assert(trace.first[0].seq == 1 && trace.first.back().seq == 32);
    assert(trace.first_error_seq == 40 && trace.first_error.sdk_entered && !trace.first_error.status_present);
    assert(trace.before_count == 8 && trace.before[0].seq == 32 && trace.before.back().seq == 39);
    assert(trace.after_count == 8 && trace.after[0].seq == 41 && trace.after.back().seq == 48);
}

void duplicate_gpio_callback_does_not_duplicate_sample() {
    Model m;
    m.initialize(0, true);
    m.initialize(1, true);
    m.begin_frame();
    m.produce(1);
    m.edge(1);
    m.edge(1); // simulate duplicate callbacks, not the ESP-IDF registration API
    m.drain_notification_hints();
    assert(m.sites[1].raw == 2 && m.sites[1].attempts == 1 && m.sites[1].valid == 1);
    assert(m.sites[1].edge_coalesced == 1);
    m.assert_accounting();
}

void one_read_clear_consumer_per_frame() {
    Model m;
    m.initialize(0, true);
    m.initialize(1, true);
    m.begin_frame();
    m.produce(1);
    m.edge(1);
    m.drain_notification_hints();
    assert(m.sites[1].valid == 1 && m.sites[1].attempts == 1);
    // An IRQ and fallback scheduled for the same site and frame cannot
    // independently consume the same latch.
    assert(!m.fallback(1));
    m.begin_frame();
    assert(m.fallback(1));
    assert(m.sites[1].valid == 1 && m.sites[1].unavailable == 1);
    m.assert_accounting();
}

} // namespace

int main() {
    tail_edge_without_a_new_notification();
    stale_hints_error_and_shared_fallback_budget();
    dual_sites_at_different_phases();
    noisy_top_keeps_raw_evidence_without_flooding_reads();
    stop_keeps_late_raw_but_never_services_again();
    toe_edge_bursts_preserve_status_gate(70);
    toe_edge_bursts_preserve_status_gate(90);
    toe_trace_is_bounded_and_keeps_first_sdk_failure();
    one_read_clear_consumer_per_frame();
    duplicate_gpio_callback_does_not_duplicate_sample();
    std::puts("HOST_IMU_SERVICE_POLICY_TEST_PASS (TEST_ONLY injected edges/notifications/status; HARDWARE_NOT_RUN)");
}
