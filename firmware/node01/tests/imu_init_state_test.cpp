#include "node/sensors.hpp"
#include <array>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <functional>
#include <map>
#include <tuple>

// TEST_ONLY register boundary. This executes the production initializer with
// injected register replies/callback reentry; no GPIO, SDK bus or hardware I/O.
namespace {
using namespace node;

struct RegisterModel final : drivers::RegisterBus {
    std::map<std::tuple<unsigned, unsigned, unsigned>, std::uint8_t> registers;
    std::array<unsigned, 128> bank{}, requests{};
    std::uint64_t clock = 1;
    unsigned fail_who_address = 0;
    esp_err_t who_error = ESP_ERR_INVALID_STATE;
    std::function<void()> first_write_hook;

    RegisterModel() {
        registers[{0x68, 0, 0x75}] = registers[{0x69, 0, 0x75}] = 0x47;
    }
    esp_err_t read(std::uint8_t address, std::uint8_t reg,
            std::uint8_t* destination, std::size_t length) override {
        ++requests[address]; clock += 100;
        if (reg == 0x75 && address == fail_who_address) return who_error;
        for (std::size_t i = 0; i < length; ++i)
            destination[i] = reg == 0x76 ? static_cast<std::uint8_t>(bank[address]) :
                registers[{address, bank[address], reg + static_cast<unsigned>(i)}];
        return ESP_OK;
    }
    esp_err_t write(std::uint8_t address, std::uint8_t reg,
            const std::uint8_t* data, std::size_t length) override {
        ++requests[address]; clock += 100;
        if (first_write_hook) {
            // Clear before invoking: an unsafe nested call cannot recurse
            // forever and hide the initializer's actual reentry behaviour.
            auto callback = std::move(first_write_hook);
            first_write_hook = {};
            callback();
        }
        if (reg == 0x76) { assert(length == 1); bank[address] = data[0]; }
        else {
            for (std::size_t i = 0; i < length; ++i)
                registers[{address, bank[address], reg + static_cast<unsigned>(i)}] = data[i];
            if (reg == 0x11 && length == 1 && data[0] == 1) bank[address] = 0;
        }
        return ESP_OK;
    }
    void delay_ms(unsigned ms) override { clock += ms * 1000ULL; }
    std::uint64_t now_us() const override { return clock; }
};

bool same_access(const drivers::ImuInitAccess& a, const drivers::ImuInitAccess& b) {
    return std::tie(a.phase, a.operation, a.reg, a.length, a.value,
                    a.value_observed, a.validation_error, a.error, a.started_us, a.finished_us) ==
        std::tie(b.phase, b.operation, b.reg, b.length, b.value,
                    b.value_observed, b.validation_error, b.error, b.started_us, b.finished_us);
}
void assert_same_trace(const drivers::ImuInitTrace& a, const drivers::ImuInitTrace& b) {
    assert(a.critical_size == b.critical_size && a.transfers == b.transfers && a.phase == b.phase);
    assert(a.first_failure_present == b.first_failure_present && a.who_observed == b.who_observed);
    assert(a.bank_restore_attempted == b.bank_restore_attempted && a.actual_who == b.actual_who);
    assert(same_access(a.first_failure, b.first_failure));
    for (unsigned i = 0; i < a.critical.size(); ++i) assert(same_access(a.critical[i], b.critical[i]));
}
void assert_failed_not_ready(drivers::DualIcm42688& device, RegisterModel& bus,
        sampling::ImuSite site, unsigned address) {
    const auto calls = bus.requests[address];
    sampling::ImuSample sample;
    assert(device.prepare_drdy(site) == ESP_ERR_INVALID_STATE);
    assert(device.read(site, sample) == PortStatus::Error);
    assert(sample.validity == sampling::Validity::Error && !sample.acquired_uptime_us);
    assert(bus.requests[address] == calls); // software Error is not an SDK request
}

void independent_sites_and_failed_snapshot() {
    RegisterModel bus;
    drivers::DualIcm42688 device(bus);
    assert(device.initialize(sampling::ImuSite::Top, 100, true) == ESP_OK);
    const auto top = device.initialization_diagnostic(sampling::ImuSite::Top);
    const auto top_diagnostic = device.diagnostic(sampling::ImuSite::Top);
    assert(top.phase == drivers::ImuInitPhase::Complete && top.transfers == 50);
    assert(top.who_observed && top.actual_who == 0x47 && !top.first_failure_present);
    bus.fail_who_address = 0x69;
    const auto result = device.initialize(sampling::ImuSite::Toe, 100, true);
    const auto failed = device.initialization_diagnostic(sampling::ImuSite::Toe);
    const auto diagnostic = device.diagnostic(sampling::ImuSite::Toe);
    assert(result == ESP_ERR_INVALID_STATE && diagnostic.init_error == result);
    assert(!diagnostic.init_readback.complete && !failed.who_observed && failed.actual_who == 0);
    assert(failed.transfers == 3 && failed.phase == drivers::ImuInitPhase::WhoAmI);
    assert(failed.first_failure_present && !failed.first_failure.validation_error);
    assert(failed.first_failure.operation == 'R' && failed.first_failure.reg == 0x75);
    assert(failed.first_failure.error == result);
    assert_same_trace(top, device.initialization_diagnostic(sampling::ImuSite::Top));
    assert(device.diagnostic(sampling::ImuSite::Top).init_error == top_diagnostic.init_error);
    assert_failed_not_ready(device, bus, sampling::ImuSite::Toe, 0x69);
    // Reading failed TOE modifies its live acquisition diagnostic, never the
    // completed initialization trace or a previously copied value snapshot.
    assert_same_trace(failed, device.initialization_diagnostic(sampling::ImuSite::Toe));
    assert_same_trace(top, device.initialization_diagnostic(sampling::ImuSite::Top));
    bus.registers[{0x68, 0, 0x2d}] = 0x08;
    bus.registers[{0x68, 0, 0x1f}] = 1;
    sampling::ImuSample sample;
    assert(device.read(sampling::ImuSite::Top, sample) == PortStatus::Ready);
    assert(sample.validity == sampling::Validity::Valid && sample.acquired_uptime_us);
}

void real_wrong_who_is_not_a_failed_read_placeholder() {
    RegisterModel bus;
    bus.registers[{0x69, 0, 0x75}] = 0x08;
    drivers::DualIcm42688 device(bus);
    assert(device.initialize(sampling::ImuSite::Toe, 100, true) == ESP_ERR_INVALID_RESPONSE);
    const auto trace = device.initialization_diagnostic(sampling::ImuSite::Toe);
    assert(trace.who_observed && trace.actual_who == 0x08 && trace.transfers == 3);
    assert(trace.first_failure_present && trace.first_failure.validation_error);
    assert(trace.first_failure.value_observed && trace.first_failure.value == 0x08);
    assert(trace.critical[2].error == ESP_OK); // SDK reply succeeded, identity check failed
    assert_failed_not_ready(device, bus, sampling::ImuSite::Toe, 0x69);
}

void serial_retry_resets_only_the_requested_site() {
    RegisterModel bus;
    drivers::DualIcm42688 device(bus);
    assert(device.initialize(sampling::ImuSite::Top, 100, true) == ESP_OK);
    const auto top = device.initialization_diagnostic(sampling::ImuSite::Top);
    assert(device.initialize(sampling::ImuSite::Toe, 100, true) == ESP_OK);
    assert(device.status() == PortStatus::Ready);
    const auto success_snapshot = device.initialization_diagnostic(sampling::ImuSite::Toe);
    bus.fail_who_address = 0x69;
    assert(device.initialize(sampling::ImuSite::Toe, 100, true) == ESP_ERR_INVALID_STATE);
    const auto failure_snapshot = device.initialization_diagnostic(sampling::ImuSite::Toe);
    assert(failure_snapshot.transfers == 3 && failure_snapshot.first_failure_present);
    assert(!failure_snapshot.who_observed && failure_snapshot.actual_who == 0);
    assert(device.status() == PortStatus::Error);
    assert_failed_not_ready(device, bus, sampling::ImuSite::Toe, 0x69);
    bus.fail_who_address = 0;
    // The deterministic clock has zero transfer duration. Explicitly advance
    // it for this distinct attempt; equal adjacent microseconds are legal in
    // production and must not be mistaken for a stale diagnostic snapshot.
    ++bus.clock;
    assert(device.initialize(sampling::ImuSite::Toe, 100, true) == ESP_OK);
    const auto& retried = device.initialization_diagnostic(sampling::ImuSite::Toe);
    assert(device.status() == PortStatus::Ready && retried.phase == drivers::ImuInitPhase::Complete);
    assert(retried.transfers == 50 && retried.who_observed && retried.actual_who == 0x47);
    assert(!retried.first_failure_present && retried.first_failure.operation == '?');
    assert_same_trace(top, device.initialization_diagnostic(sampling::ImuSite::Top));
    // Value snapshots keep the actual old attempt, even after another retry.
    assert(success_snapshot.transfers == 50 && !success_snapshot.first_failure_present);
    assert(failure_snapshot.transfers == 3 && failure_snapshot.first_failure.error == ESP_ERR_INVALID_STATE);
    assert(retried.critical[0].started_us > failure_snapshot.first_failure.finished_us);
}

void same_site_reentry_must_not_reset_outer_attempt() {
    RegisterModel bus;
    drivers::DualIcm42688 device(bus);
    esp_err_t inner = ESP_OK;
    unsigned nested_bus_requests = 0;
    bus.first_write_hook = [&] {
        const auto before = bus.requests[0x68];
        inner = device.initialize(sampling::ImuSite::Top, 100, true);
        nested_bus_requests = bus.requests[0x68] - before;
    };
    const auto outer = device.initialize(sampling::ImuSite::Top, 100, true);
    const auto& trace = device.initialization_diagnostic(sampling::ImuSite::Top);
    std::fprintf(stderr, "INIT_REENTRY_TEST_ONLY outer=%d inner=%d nested_bus_requests=%u outer_transfers=%u\n",
        outer, inner, nested_bus_requests, trace.transfers);
    assert(inner == ESP_ERR_INVALID_STATE);
    assert(nested_bus_requests == 0);
    assert(outer == ESP_OK && device.diagnostic(sampling::ImuSite::Top).init_error == ESP_OK);
    assert(trace.phase == drivers::ImuInitPhase::Complete && trace.transfers == 50);
    assert(trace.who_observed && trace.actual_who == 0x47 && !trace.first_failure_present);
    // Entry guard must release on normal return and not block a later retry.
    assert(device.initialize(sampling::ImuSite::Top, 100, true) == ESP_OK);
}

void different_sites_have_independent_entry_guards() {
    RegisterModel bus;
    drivers::DualIcm42688 device(bus);
    esp_err_t inner = ESP_ERR_INVALID_STATE;
    bus.first_write_hook = [&] { inner = device.initialize(sampling::ImuSite::Toe, 100, true); };
    assert(device.initialize(sampling::ImuSite::Top, 100, true) == ESP_OK);
    assert(inner == ESP_OK && device.status() == PortStatus::Ready);
    const auto& top = device.initialization_diagnostic(sampling::ImuSite::Top);
    const auto& toe = device.initialization_diagnostic(sampling::ImuSite::Toe);
    assert(top.transfers == 50 && toe.transfers == 50);
    assert(top.phase == drivers::ImuInitPhase::Complete && toe.phase == drivers::ImuInitPhase::Complete);
    assert(!top.first_failure_present && !toe.first_failure_present);
    assert(top.who_observed && toe.who_observed && top.actual_who == 0x47 && toe.actual_who == 0x47);
    // This is deterministic cross-site callback nesting, not a general proof
    // that read/diagnostic/init APIs may be concurrently used by arbitrary tasks.
}
} // namespace

int main() {
    independent_sites_and_failed_snapshot();
    real_wrong_who_is_not_a_failed_read_placeholder();
    serial_retry_resets_only_the_requested_site();
    same_site_reentry_must_not_reset_outer_attempt();
    different_sites_have_independent_entry_guards();
    std::puts("HOST_IMU_INIT_STATE_TEST_PASS (TEST_ONLY real initializer/register injection/reentry; HARDWARE_NOT_RUN)");
}
