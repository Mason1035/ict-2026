#include "node/acquisition_policy.hpp"
#include <cassert>
#include <cstdint>
#include <limits>

int main() {
    using namespace node::runtime::policy;
    StorageServiceBudget budget(32, 50000);
    for (unsigned i = 0; i < 31; ++i) budget.observe(10, true);
    assert(!budget.yield_due());
    budget.observe(10, true);
    assert(budget.yield_due());
    budget.reset(); // queue wait / explicit yield starts a fresh service burst
    budget.observe(49999, false);
    assert(!budget.yield_due());
    budget.observe(1, false);
    assert(budget.yield_due()); // flush and verification also consume the quota
    budget.reset();
    budget.observe(841299, true);
    assert(budget.yield_due()); // can only yield AFTER blocking I/O returns
    budget.reset();
    assert(!budget.yield_due()); // idle waiting does not tax the next operation
    CaptureWindow capture(120);
    assert(!capture.poll(999999999)); // a clock value alone cannot start capture
    capture.begin(0); // zero is a legitimate real monotonic start
    capture.begin(1000); // another producer cannot move the shared start
    assert(!capture.poll(119999999));
    assert(capture.poll(120000000));
    assert(capture.observation().requested_stop_us == 120000000);
    assert(capture.poll(130000000)); // stop time is sticky
    capture.producer_done(1);
    assert(!capture.drained_producers(3)); // never finalize before slow producer stops
    capture.producer_done(2);
    assert(capture.drained_producers(3));
    assert(capture.observation().started_us == 0);
    CaptureWindow continuous(0);
    continuous.begin(10);
    assert(!continuous.poll(std::numeric_limits<std::uint64_t>::max()));
    CaptureWindow backwards(1);
    backwards.begin(100);
    assert(!backwards.poll(99)); // no unsigned underflow can cause a fake stop
    assert(backwards.poll(1000100));
    EdgeCursor edges;
    assert(edges.consume(1) == 1);
    assert(edges.consume(1) == 0); // repeated notification is not a new edge/sample
    assert(edges.consume(4) == 3); // caller records coalescence, reads only latest real data
    EdgeCursor wrap;
    wrap.consume(std::numeric_limits<std::uint32_t>::max());
    assert(wrap.consume(0) == 1);
    IrqFallback fallback;
    unsigned polls = 0;
    for (unsigned frame = 1; frame <= 100; ++frame)
        if (fallback.poll_needed(frame * 10000ULL, (frame - 1) * 10000ULL, 15000)) ++polls;
    assert(polls == 100); // unknown/unwired IRQ retains old polling cadence
    fallback.observed_edge();
    assert(!fallback.poll_needed(1005000, 1000000, 15000));
    assert(fallback.poll_needed(1020000, 1000000, 15000));
    assert(fallback.poll_needed(1030000, 1020000, 15000)); // remains in polling until real edge
    fallback.observed_edge();
    assert(!fallback.poll_needed(1031000, 1030000, 15000));
    // TEST_ONLY service admission. Raw ISR counters remain independent: even
    // noisy IRQs and fallback together can read each site only once per frame.
    ImuFrameBudget frame;
    assert(frame.may_read(0) && frame.may_read(1));
    assert(!frame.may_read(2) && !frame.may_read(std::numeric_limits<unsigned>::max()));
    assert(!frame.awaiting(0) && !frame.awaiting(4));
    assert(frame.awaiting(1) && frame.awaiting(2) && frame.awaiting(3));
    assert(!frame.claim(2));
    assert(frame.claim(0)); // IRQ owns this site's allowance
    assert(!frame.may_read(0) && frame.may_read(1));
    assert(!frame.claim(0)); // fallback cannot duplicate the service
    assert(!frame.awaiting(1) && frame.awaiting(3));
    assert(frame.claim(1));
    assert(!frame.claim(1) && !frame.awaiting(3));
    assert(!frame.awaiting(std::numeric_limits<std::uint32_t>::max()));
    for (unsigned period = 0; period < 1000; ++period) {
        ImuFrameBudget next_frame;
        unsigned services = 0;
        assert(next_frame.claim(1)); // fallback-first shares allowance with IRQ
        for (unsigned notification = 0; notification < 100; ++notification)
            if (next_frame.claim(0)) ++services;
        assert(services == 1 && !next_frame.claim(1));
        assert(!next_frame.awaiting(3));
    }

    // Capture rate excludes warmup before the epoch and verification after stop.
    CaptureObservation not_started;
    assert(capture_overlap_us(10, 20, not_started) == 0);
    CaptureObservation running;
    running.started = true;
    running.started_us = 100;
    assert(capture_overlap_us(0, 200, running) == 0); // no previous observation
    assert(capture_overlap_us(50, 99, running) == 0);
    assert(capture_overlap_us(50, 100, running) == 0);
    assert(capture_overlap_us(50, 150, running) == 50);
    assert(capture_overlap_us(100, 200, running) == 100);
    assert(capture_overlap_us(150, 200, running) == 50);
    assert(capture_overlap_us(150, 150, running) == 0);
    assert(capture_overlap_us(200, 150, running) == 0); // reversed clock
    running.stop_requested = true;
    running.requested_stop_us = 200;
    assert(capture_overlap_us(50, 300, running) == 100); // clip both boundaries
    assert(capture_overlap_us(150, 300, running) == 50);
    assert(capture_overlap_us(200, 300, running) == 0);
    assert(capture_overlap_us(201, 300, running) == 0);
    running.requested_stop_us = 99; // inconsistent state must not underflow
    assert(capture_overlap_us(50, 300, running) == 0);
    CaptureObservation zero_start;
    zero_start.started = true;
    assert(capture_overlap_us(1, 20, zero_start) == 19); // zero epoch is valid

    // Log-derived TEST_ONLY replay: actual first/final Health and CAPTURE_BEGIN
    // timestamps from both logs. An exact 10s stop is injected from configuration,
    // not claimed as an observed hardware requested_stop_us timestamp.
    struct RateReplay {
        std::uint64_t previous_health, final_health, begin;
        unsigned valid;
    };
    constexpr RateReplay replay[] {
        {249091, 11161478, 989849, 1001}, // control 20261029173524
        {271719, 11241467, 1074194, 999}  // probe   20261029174228
    };
    for (const auto& log : replay) {
        CaptureObservation window;
        window.started = true;
        window.started_us = log.begin;
        window.stop_requested = true;
        window.requested_stop_us = log.begin + 10000000;
        const auto elapsed_health = log.final_health - log.previous_health;
        const auto elapsed_capture = capture_overlap_us(log.previous_health, log.final_health, window);
        assert(elapsed_capture == 10000000 && elapsed_health > elapsed_capture);
        const double interval_rate = log.valid * 1000000.0 / elapsed_health;
        const double capture_rate = log.valid * 1000000.0 / elapsed_capture;
        assert(interval_rate > 91.0 && interval_rate < 92.0);
        assert(capture_rate > 99.8 && capture_rate < 100.2);
        assert(capture_overlap_us(log.final_health, log.final_health + 10000000, window) == 0);
    }
    assert(remaining_ticks<std::uint32_t>(10, 11) == 1);
    assert(remaining_ticks<std::uint32_t>(11, 11) == 0);
    assert(remaining_ticks<std::uint32_t>(12, 11) == 0);
    assert(remaining_ticks<std::uint32_t>(std::numeric_limits<std::uint32_t>::max(), 0) == 1);
}
