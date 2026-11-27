#include "node/timeout_budget.hpp"
#include "node/i2c_diagnostics.hpp"
#include <atomic>
#include <cassert>
#include <mutex>
#include <thread>

// TEST_ONLY: tick-phase arithmetic and the production counter registry. This
// does not execute an ESP-IDF transaction, clear a real bus, or prove hardware.
int main() {
    using namespace node::drivers;
    using namespace timing;
    static_assert(guarded_wait_ticks(10, 100) == 2);
    static_assert(guarded_timeout_ms(10, 100) == 20);
    static_assert(guarded_wait_ticks(10, 1000) == 11);
    static_assert(guarded_timeout_ms(10, 1000) == 11);
    static_assert(guarded_wait_ticks(0, 100) == 0);
    static_assert(guarded_timeout_ms(10, 0) == 0);
    static_assert(guarded_wait_ticks(UINT32_MAX, UINT32_MAX) == 0);
    static_assert(minimum_delay_ticks(0, 100) == 1); // preserve old one-tick block, not vTaskDelay(0) yield
    static_assert(minimum_delay_ticks(0, 0) == 0);
    static_assert(minimum_delay_ticks(2, 0) == 0);
    static_assert(minimum_delay_ticks(1, 100) == 2);
    static_assert(minimum_delay_ticks(2, 100) == 2);
    static_assert(minimum_delay_ticks(9, 100) == 2);
    static_assert(minimum_delay_ticks(10, 100) == 2);
    static_assert(minimum_delay_ticks(11, 100) == 3);
    static_assert(minimum_delay_ticks(49, 100) == 6);
    static_assert(minimum_delay_ticks(50, 100) == 6);
    static_assert(minimum_delay_ticks(51, 100) == 7);
    static_assert(minimum_delay_ticks(UINT32_MAX, 100) == 429496731U);
    static_assert(minimum_delay_ticks(UINT32_MAX, 1000) == 0); // guard cannot fit uint32, no wrap to a short wait
    static_assert(minimum_delay_ticks(UINT32_MAX, UINT32_MAX) == 0);
    // The old one-tick wait can expire before a healthy 1.35 ms transfer;
    // the guarded wait retains the requested minimum even near a tick edge.
    constexpr unsigned tick_us = 10000;
    assert(tick_us - 9500 < 1350);
    assert(guarded_wait_ticks(10, 100) * tick_us - 9500 >= 10000);
    for (unsigned phase = 0; phase < tick_us; ++phase)
        assert(guarded_wait_ticks(10, 100) * tick_us - phase >= 10000);
    // Execute the exact production delay helper across every microsecond
    // starting phase in a 100Hz tick. The old 2ms floor+1 admits a 1us wait.
    // TEST_ONLY schedule model: not a measurement of a physical reset/SDK.
    constexpr auto old_reset_ticks = 2U * 100U / 1000U + 1U;
    constexpr auto old_warmup_ticks = 50U * 100U / 1000U + 1U;
    assert(old_reset_ticks * tick_us - (tick_us - 1) == 1);
    assert(old_reset_ticks * tick_us - (tick_us - 1) < 1000); // DS reset minimum is not guaranteed by old code
    for (unsigned phase = 0; phase < tick_us; ++phase) {
        for (unsigned ms : {1U,2U,9U,10U,11U,49U,50U,51U,1000U,1001U,UINT32_MAX}) {
            const auto ticks = minimum_delay_ticks(ms, 100);
            const auto earliest_us = static_cast<std::uint64_t>(ticks) * tick_us - phase;
            assert(earliest_us >= static_cast<std::uint64_t>(ms) * 1000);
        }
        assert(minimum_delay_ticks(50, 100) * tick_us - phase == old_warmup_ticks * tick_us - phase);
        // Existing init call sequence: each site requests reset 2ms, then
        // power warmup 50ms. Use the SAME production helper at each boundary;
        // this does not substitute a nominal exact-ms sleep for an RTOS wait.
        std::uint64_t clock = phase;
        for (unsigned site = 0; site < 2; ++site) {
            for (unsigned requested_ms : {2U,50U}) {
                const auto started = clock;
                const auto ticks = minimum_delay_ticks(requested_ms, 100);
                clock = (clock / tick_us + ticks) * tick_us;
                assert(clock - started >= static_cast<std::uint64_t>(requested_ms) * 1000);
            }
        }
    }
    // FreeRTOS's delayed lists handle unsigned tick wrap. The selected delay
    // stays the same even when the calculated wake tick wraps through zero.
    for (unsigned ms : {2U,50U,UINT32_MAX}) {
        const std::uint32_t start_tick = UINT32_MAX - 1U;
        const auto ticks = minimum_delay_ticks(ms, 100);
        const auto wake_tick = static_cast<std::uint32_t>(start_tick + ticks);
        assert(static_cast<std::uint32_t>(wake_tick - start_tick) == ticks);
    }
    for (unsigned hz : {100U, 128U, 250U, 1000U, 1024U}) {
        for (unsigned minimum : {1U, 5U, 10U, 13U, 50U}) {
            const auto requested = guarded_timeout_ms(minimum, hz);
            const auto sdk_ticks = static_cast<std::uint64_t>(requested) * hz / 1000;
            assert(sdk_ticks >= guarded_wait_ticks(minimum, hz));
            // Avoid integer microsecond approximations for non-divisor tick rates.
            assert((sdk_ticks - 1) * 1000 >= static_cast<std::uint64_t>(minimum) * hz);
            const auto delay_ticks = minimum_delay_ticks(minimum, hz);
            assert(delay_ticks != 0);
            assert(static_cast<std::uint64_t>(delay_ticks - 1) * 1000 >= static_cast<std::uint64_t>(minimum) * hz);
        }
    }
    // Generic SDK INVALID_STATE does not prove a dead handle or no hardware
    // timeout; it is kept separate from application preconditions. Boundary
    // pad observations never repair/classify the failed transaction.
    I2cDiagnosticRegistry<std::mutex> sources({0x68, 0x69, 0x48});
    sources.record(0x68, 0x2d, 1, true, true, ESP_ERR_INVALID_STATE, 250,
                   I2cLineLevels{1, 1, 0, 1});
    sources.record(0x68, 0x1f, 12, true, false, ESP_ERR_INVALID_STATE, 1);
    sources.record(0x68, 0x1f, 12, true, false, ESP_ERR_TIMEOUT, 19990);
    auto classified = sources.snapshot();
    assert(classified[0].sdk_errors == 1 && classified[0].local_errors == 2);
    assert(classified[0].sdk_invalid_states == 1 && classified[0].local_invalid_states == 1);
    assert(classified[0].timeouts == 1 && classified[0].invalid_states == 2);
    assert(classified[0].last_failed_lines.before_sda == -1);
    sources.record(0x68, 0x1f, 12, true, true, ESP_ERR_INVALID_STATE, 400,
                   I2cLineLevels{1, 1, 1, 1});
    sources.record(0x68, 0x1f, 12, true, true, ESP_OK, 1400);
    sources.record_probe(0x68, true, ESP_ERR_NOT_FOUND);
    sources.record_probe(0x68, false, ESP_ERR_TIMEOUT);
    classified = sources.snapshot();
    assert(classified[0].sdk_errors == 2 && classified[0].local_errors == 2);
    assert(classified[0].last_failed_lines.before_sda == 1 && classified[0].last_failed_lines.after_scl == 1);
    assert(classified[0].last_failed_error == ESP_ERR_INVALID_STATE);
    assert(classified[0].transfers == 5 && classified[0].sdk_calls == 3);
    assert(classified[0].probes == 2 && classified[0].probe_sdk_calls == 1);
    assert(classified[0].last_probe_error == ESP_ERR_TIMEOUT);
    assert(classified[1].probes == 0 && classified[2].transfers == 0);
    std::array<I2cDeviceDiagnostics, 3> copied{};
    sources.snapshot_into(copied);
    assert(copied[0].sdk_invalid_states == classified[0].sdk_invalid_states);
    assert(copied[0].last_failed_lines.after_sda == classified[0].last_failed_lines.after_sda);
    assert(copied[0].probes == 2 && copied[1].address == 0x69);

    I2cDiagnosticRegistry<std::mutex> registry({0x68, 0x69, 0x48});
    registry.record(0x68, 0x1f, 12, true, true, ESP_OK, 1400);
    registry.record(0x68, 0x2d, 1, true, false, ESP_ERR_TIMEOUT, 19990); // outer lock failed
    registry.record(0x68, 0x2d, 1, true, true, ESP_ERR_INVALID_STATE, 500);
    registry.record(0x48, 1, 2, false, true, ESP_ERR_TIMEOUT, 10100);
    auto copy = registry.snapshot();
    assert(copy[0].transfers == 3 && copy[0].sdk_calls == 2 && copy[0].reads == 3 && !copy[0].writes);
    assert(copy[0].errors == 2 && copy[0].timeouts == 1 && copy[0].invalid_states == 1);
    assert(copy[0].max_wall_us == 19990 && copy[0].total_wall_us == 21890);
    assert(copy[0].last_error == ESP_ERR_INVALID_STATE && copy[0].last_executed);
    registry.record(0x68, 0x1f, 12, true, true, ESP_OK, 1300);
    copy = registry.snapshot();
    assert(copy[0].last_error == ESP_OK && copy[0].last_reg == 0x1f);
    assert(copy[0].last_failed_error == ESP_ERR_INVALID_STATE && copy[0].last_failed_reg == 0x2d);
    assert(copy[0].last_failed_size == 1 && copy[0].last_failed_read && copy[0].last_failed_executed);
    assert(copy[0].last_failed_wall_us == 500);
    assert(copy[2].writes == 1 && copy[2].last_reg == 1 && copy[2].last_size == 2 && !copy[2].last_read);
    assert(copy[1].address == 0x69 && copy[1].transfers == 0);
    assert(copy[1].last_failed_error == ESP_OK); // no failure has occurred for this address
    registry.record(0x48, 0, 2, true, true, ESP_OK, 600);
    copy = registry.snapshot();
    assert(copy[2].last_error == ESP_OK && copy[2].last_read);
    assert(copy[2].last_failed_error == ESP_ERR_TIMEOUT && copy[2].last_failed_reg == 1);
    assert(copy[2].last_failed_size == 2 && !copy[2].last_failed_read && copy[2].last_failed_executed);
    assert(copy[2].last_failed_wall_us == 10100);
    registry.record(0x69, 0x2d, 1, true, false, ESP_ERR_TIMEOUT, 19999);
    registry.record(0x69, 0x1f, 12, true, true, ESP_OK, 1350);
    copy = registry.snapshot();
    assert(copy[1].last_error == ESP_OK && copy[1].last_failed_error == ESP_ERR_TIMEOUT);
    assert(!copy[1].last_failed_executed && copy[1].last_failed_reg == 0x2d);
    assert(copy[1].last_failed_wall_us == 19999);
    copy[0].errors = 1000;
    assert(registry.snapshot()[0].errors == 2); // returned snapshot has value ownership
    std::atomic<bool> finished{false};
    std::thread reader([&] {
        while (!finished.load()) {
            const auto s = registry.snapshot();
            for (const auto& d : s) {
                assert(d.transfers == d.reads + d.writes);
                assert(d.sdk_calls <= d.transfers && d.errors <= d.transfers);
                assert(d.max_wall_us <= d.total_wall_us);
            }
        }
    });
    std::thread top([&] {
        for (unsigned i = 0; i < 10000; ++i)
            registry.record(0x68, 0x1f, 12, true, true, ESP_OK, 1400);
    });
    std::thread toe([&] {
        for (unsigned i = 0; i < 10000; ++i)
            registry.record(0x69, 0x2d, 1, true, true, ESP_ERR_INVALID_STATE, 500);
    });
    top.join(); toe.join(); finished = true; reader.join();
    copy = registry.snapshot();
    assert(copy[0].transfers == 10004 && copy[1].transfers == 10002);
    assert(copy[1].errors == 10001 && copy[1].invalid_states == 10000);
}
