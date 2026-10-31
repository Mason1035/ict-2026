#include "node/sensors.hpp"
#include <cassert>
#include <algorithm>
#include <cmath>
#include <cstring>
#include <map>
#include <utility>
#include <vector>

// TEST_ONLY register simulation. No hardware PASS, no production mock mode.
class FakeBus final : public node::drivers::RegisterBus {
public:
    struct Transfer { char operation; unsigned address, reg; std::size_t length; std::uint8_t requested; };
    std::vector<Transfer> transfers;
    std::array<unsigned, 128> requests{};
    unsigned injected_address = 0;
    std::vector<unsigned> injected_requests;
    esp_err_t injected_transfer_error = ESP_ERR_INVALID_STATE;
    std::vector<unsigned> delays;
    std::map<std::pair<unsigned, unsigned>, std::array<std::uint8_t, 12>> registers, bank1_registers;
    std::array<std::uint8_t, 128> bank{};
    std::uint64_t clock = 0;
    unsigned fail_address = 0, bad_readback_reg = 0, reads = 0, bad_readback_mask = 1;
    bool fail_bank_restore = false;
    unsigned fail_read_reg = 0x100, fail_write_reg = 0x100;
    std::uint64_t read_time_us = 0, write_time_us = 0;
    std::uint16_t adc_config = 0x8583, adc_value = 0;
    bool adc_busy = false, adc_bad_readback = false, clear_drdy_on_status = false;
    esp_err_t injected_read_error = ESP_ERR_TIMEOUT;
    std::vector<std::pair<unsigned, unsigned>> writes;
    bool injected_failure(unsigned address) {
        const auto ordinal = ++requests[address];
        return address == injected_address &&
            std::find(injected_requests.begin(), injected_requests.end(), ordinal) != injected_requests.end();
    }
    esp_err_t read(std::uint8_t a, std::uint8_t r, std::uint8_t* p, std::size_t n) override {
        ++reads;
        clock += read_time_us;
        transfers.push_back({'R', a, r, n, 0});
        if (injected_failure(a)) return injected_transfer_error;
        if (a == fail_address || r == fail_read_reg) return injected_read_error;
        if (a == 0x48) {
            assert(n == 2);
            const auto v = r == 1 ? ((adc_config | (adc_busy ? 0 : 0x8000)) ^
                (adc_bad_readback ? 0x1000 : 0)) : adc_value;
            p[0] = v >> 8; p[1] = v;
        } else {
            if (r == 0x76) { assert(n == 1); p[0] = bank[a]; }
            else std::memcpy(p, (bank[a] == 1 ? bank1_registers : registers)[{a, r}].data(), n);
            if (r == bad_readback_reg) p[0] ^= bad_readback_mask;
            if (r == 0x2d && clear_drdy_on_status && bank[a] == 0) registers[{a, r}][0] &= ~0x08;
        }
        return ESP_OK;
    }
    esp_err_t write(std::uint8_t a, std::uint8_t r, const std::uint8_t* p, std::size_t n) override {
        writes.emplace_back(a, r);
        clock += write_time_us;
        transfers.push_back({'W', a, r, n, static_cast<std::uint8_t>(n ? p[0] : 0)});
        if (injected_failure(a)) return injected_transfer_error;
        if (a == fail_address || r == fail_write_reg) return ESP_ERR_TIMEOUT;
        if (a == 0x48) adc_config = ((p[0] << 8) | p[1]) & 0x7fff;
        else if (r == 0x76) {
            if (fail_bank_restore && bank[a] == 1 && p[0] == 0) return ESP_ERR_TIMEOUT;
            assert(n == 1); bank[a] = p[0];
        } else {
            std::memcpy((bank[a] == 1 ? bank1_registers : registers)[{a, r}].data(), p, n);
            if (r == 0x11 && p[0] == 1) bank[a] = 0;
        }
        return ESP_OK;
    }
    void delay_ms(unsigned ms) override { delays.push_back(ms); clock += ms * 1000; }
    std::uint64_t now_us() const override { return clock; }
};
int main() {
    using namespace node;
    FakeBus b;
    b.registers[{0x68, 0x75}][0] = b.registers[{0x69, 0x75}][0] = 0x47;
    b.bank1_registers[{0x68, 0x7c}][0] = 0xff;
    b.bank1_registers[{0x68, 0x7a}][0] = 0xff;
    b.registers[{0x68, 0x13}][0] = 0xc0;
    drivers::DualIcm42688 imu(b);
    assert(imu.initialize(sampling::ImuSite::Top) == ESP_OK);
    assert(b.clock >= 52000);
    assert(b.bank[0x68] == 0);
    assert(b.bank1_registers.at({0x68, 0x7c})[0] == 0xfc);
    assert(b.bank1_registers.at({0x68, 0x7a})[0] == 0xbf);
    assert(b.registers.at({0x68, 0x13})[0] == 0xc9);
    assert(imu.diagnostic(sampling::ImuSite::Top).init_error == ESP_OK);
    assert(imu.diagnostic(sampling::ImuSite::Top).bank_restore_error == ESP_OK);
    b.registers[{0x69, 0x75}][0] = 0;
    assert(imu.initialize(sampling::ImuSite::Toe) == ESP_ERR_INVALID_RESPONSE);
    sampling::ImuSample sample;
    auto before = b.reads;
    assert(imu.read(sampling::ImuSite::Top, sample) == PortStatus::Unavailable);
    assert(b.reads == before + 1 && !sample.acquired_uptime_us);
    b.registers[{0x68, 0x2d}][0] = 8;
    b.registers[{0x68, 0x1f}] = {0x08,0, 0xf8,0, 0,0, 0,0xa4, 0xff,0x5c, 0,0};
    assert(imu.read(sampling::ImuSite::Top, sample) == PortStatus::Ready);
    assert(std::abs(sample.acceleration_mps2[0] - 9.80665f) < 1e-5f);
    assert(std::abs(sample.acceleration_mps2[1] + 9.80665f) < 1e-5f);
    assert(std::abs(sample.angular_rate_dps[0] - 10) < 1e-5f);
    assert(sample.angular_rate_dps[2] == 0 && sample.validity == sampling::Validity::Valid);
    assert(sample.acquired_uptime_us == b.clock);
    b.fail_address = 0x68;
    assert(imu.read(sampling::ImuSite::Top, sample) == PortStatus::Error);
    assert(!sample.acquired_uptime_us && sample.validity == sampling::Validity::Error);
    const std::array<std::int16_t, 6> empty_raw{};
    assert(imu.diagnostic(sampling::ImuSite::Top).raw == empty_raw);
    b.fail_address = 0;
    b.registers[{0x68, 0x1f}][0] = 0x80;
    assert(imu.read(sampling::ImuSite::Top, sample) == PortStatus::Error);
    assert(imu.diagnostic(sampling::ImuSite::Top).raw == empty_raw);
    b.bad_readback_reg = 0x4f;
    assert(imu.initialize(sampling::ImuSite::Top) == ESP_ERR_INVALID_RESPONSE);
    b.bad_readback_reg = 0;
    b.registers[{0x69, 0x75}][0] = 0x47;
    assert(imu.initialize(sampling::ImuSite::Toe, 200) == ESP_OK);
    assert(b.registers.at({0x69, 0x4f})[0] == 0x07 && b.registers.at({0x69, 0x50})[0] == 0x07);
    assert(imu.initialize(sampling::ImuSite::Top, 123) == ESP_ERR_INVALID_ARG);
    // Failed initialization is retryable per device and cannot poison its peer.
    b.fail_write_reg = 0x11;
    assert(imu.initialize(sampling::ImuSite::Top) == ESP_ERR_TIMEOUT);
    b.fail_write_reg = 0x100;
    b.fail_read_reg = 0x75;
    assert(imu.initialize(sampling::ImuSite::Top) == ESP_ERR_TIMEOUT);
    b.fail_read_reg = 0x100;
    assert(imu.initialize(sampling::ImuSite::Top) == ESP_OK);
    assert(imu.status() == PortStatus::Ready);
    // IDF 5.5.3 can return INVALID_STATE for a failed synchronous transfer.
    // Keep it as the actual transport result, distinct from local not-ready,
    // an empty DRDY poll and sensor invalid raw codes. No invisible retry.
    b.injected_read_error = ESP_ERR_INVALID_STATE;
    b.fail_read_reg = 0x2d;
    before = b.reads;
    assert(imu.read(sampling::ImuSite::Top, sample) == PortStatus::Error);
    assert(b.reads == before + 1);
    auto diagnostic = imu.diagnostic(sampling::ImuSite::Top);
    assert(diagnostic.error == ESP_ERR_INVALID_STATE);
    assert(diagnostic.stage == drivers::ImuReadStage::Status && !diagnostic.status_observed);
    assert(diagnostic.status_failures == 1 && diagnostic.ready_data_read_failures == 0);
    assert(!sample.acquired_uptime_us && sample.validity == sampling::Validity::Error);
    assert(diagnostic.raw == empty_raw);

    // A status read can consume DRDY before the following raw transaction
    // fails. A subsequent empty poll is not a recovered/valid observation.
    b.fail_read_reg = 0x1f;
    b.clear_drdy_on_status = true;
    b.registers[{0x68, 0x2d}][0] = 8;
    before = b.reads;
    assert(imu.read(sampling::ImuSite::Top, sample) == PortStatus::Error);
    assert(b.reads == before + 2);
    diagnostic = imu.diagnostic(sampling::ImuSite::Top);
    assert(diagnostic.error == ESP_ERR_INVALID_STATE);
    assert(diagnostic.stage == drivers::ImuReadStage::Raw && diagnostic.status_observed);
    assert(diagnostic.status == 8 && diagnostic.ready_data_read_failures == 1);
    assert(!sample.acquired_uptime_us && sample.validity == sampling::Validity::Error);
    assert(diagnostic.raw == empty_raw);
    b.fail_read_reg = 0x100;
    before = b.reads;
    assert(imu.read(sampling::ImuSite::Top, sample) == PortStatus::Unavailable);
    assert(b.reads == before + 1 && !sample.acquired_uptime_us);
    assert(sample.validity == sampling::Validity::Unavailable);
    assert(imu.diagnostic(sampling::ImuSite::Top).stage == drivers::ImuReadStage::NoData);
    assert(imu.diagnostic(sampling::ImuSite::Top).ready_data_read_failures == 1);
    b.clear_drdy_on_status = false;
    b.injected_read_error = ESP_ERR_TIMEOUT;
    b.registers[{0x68, 0x2d}][0] = 0;
    assert(imu.read(sampling::ImuSite::Top, sample) == PortStatus::Unavailable);
    assert(sample.validity == sampling::Validity::Unavailable && !sample.acquired_uptime_us);
    assert(imu.diagnostic(sampling::ImuSite::Top).raw == empty_raw);
    assert(imu.read(static_cast<sampling::ImuSite>(2), sample) == PortStatus::Error);
    assert(sample.validity == sampling::Validity::Error && !sample.acquired_uptime_us);

    // Interface-setting failures are bounded, preserve the actual error, and
    // attempt bank-0 restoration even when a bank-1 read/write/readback fails.
    for (unsigned failed_register : {0x7cU, 0x7aU}) {
        for (bool fail_write : {false, true}) {
            FakeBus transport;
            transport.registers[{0x68, 0x75}][0] = 0x47;
            if (fail_write) transport.fail_write_reg = failed_register;
            else transport.fail_read_reg = failed_register;
            drivers::DualIcm42688 broken(transport);
            assert(broken.initialize(sampling::ImuSite::Top) == ESP_ERR_TIMEOUT);
            assert(transport.bank[0x68] == 0);
            assert(broken.diagnostic(sampling::ImuSite::Top).init_error == ESP_ERR_TIMEOUT);
            assert(broken.diagnostic(sampling::ImuSite::Top).bank_restore_error == ESP_OK);
            before = transport.reads;
            assert(broken.read(sampling::ImuSite::Top, sample) == PortStatus::Error);
            assert(transport.reads == before && !sample.acquired_uptime_us);
            assert(broken.diagnostic(sampling::ImuSite::Top).init_error == ESP_ERR_TIMEOUT);
        }
    }
    {
        FakeBus mismatch;
        mismatch.registers[{0x68, 0x75}][0] = 0x47;
        mismatch.bad_readback_reg = 0x7a; mismatch.bad_readback_mask = 0x40;
        drivers::DualIcm42688 broken(mismatch);
        assert(broken.initialize(sampling::ImuSite::Top) == ESP_ERR_INVALID_RESPONSE);
        assert(mismatch.bank[0x68] == 0);
    }
    {
        FakeBus restore;
        restore.registers[{0x68, 0x75}][0] = 0x47;
        restore.fail_bank_restore = true;
        restore.fail_read_reg = 0x7c;
        restore.injected_read_error = ESP_ERR_INVALID_STATE;
        drivers::DualIcm42688 broken(restore);
        assert(broken.initialize(sampling::ImuSite::Top) == ESP_ERR_INVALID_STATE);
        assert(broken.diagnostic(sampling::ImuSite::Top).init_error == ESP_ERR_INVALID_STATE);
        assert(broken.diagnostic(sampling::ImuSite::Top).bank_restore_error == ESP_ERR_TIMEOUT);
        assert(restore.bank[0x68] == 1); // reported failure, never silently assumed bank 0
    }
    {
        FakeBus restore;
        restore.registers[{0x68, 0x75}][0] = 0x47;
        restore.fail_bank_restore = true;
        drivers::DualIcm42688 broken(restore);
        assert(broken.initialize(sampling::ImuSite::Top) == ESP_ERR_TIMEOUT);
        assert(broken.diagnostic(sampling::ImuSite::Top).bank_restore_error == ESP_ERR_TIMEOUT);
    }

    // The legacy call remains polling-compatible and does not silently route
    // INT1. The explicit mode changes only its documented register masks.
    for (const auto& write : b.writes)
        assert(write.second != 0x14 && write.second != 0x63 && write.second != 0x64 && write.second != 0x65);
    {
        FakeBus ready;
        ready.registers[{0x68, 0x75}][0] = 0x47;
        ready.registers[{0x68, 0x14}][0] = 0xa8;
        ready.registers[{0x68, 0x63}][0] = 0xff;
        ready.registers[{0x68, 0x64}][0] = 0xff;
        ready.registers[{0x68, 0x65}][0] = 0xff;
        ready.registers[{0x68, 0x4d}][0] = 0x91;
        drivers::DualIcm42688 event_imu(ready);
        assert(event_imu.initialize(sampling::ImuSite::Top, 100, true) == ESP_OK);
        const auto& rb = event_imu.diagnostic(sampling::ImuSite::Top).init_readback;
        assert(rb.complete && rb.drdy_requested);
        assert(rb.gyro_config0 == 0x08 && rb.accel_config0 == 0x08);
        assert(rb.pwr_mgmt0 == 0x0f && rb.intf_config1 == 0x91);
        assert(rb.int_config == 0xaf && rb.int_config0 == 0xcf);
        assert(rb.int_config1 == 0xef && rb.int_source0 == 0x88);
        ready.clear_drdy_on_status = true;
        ready.registers[{0x68, 0x2d}][0] = 8;
        ready.registers[{0x68, 0x1f}][1] = 1;
        ready.clock += 10000;
        assert(event_imu.read(sampling::ImuSite::Top, sample) == PortStatus::Ready);
        const auto first_time = sample.acquired_uptime_us;
        assert(event_imu.diagnostic(sampling::ImuSite::Top).raw[0] == 1);
        assert(event_imu.read(sampling::ImuSite::Top, sample) == PortStatus::Unavailable);
        assert(!sample.acquired_uptime_us && sample.validity == sampling::Validity::Unavailable);
        ready.registers[{0x68, 0x2d}][0] = 8;
        ready.registers[{0x68, 0x1f}][1] = 2;
        ready.clock += 10000;
        assert(event_imu.read(sampling::ImuSite::Top, sample) == PortStatus::Ready);
        assert(sample.acquired_uptime_us > first_time);
        assert(event_imu.diagnostic(sampling::ImuSite::Top).raw[0] == 2);
        // Equal numeric observations can still be distinct actual DRDY updates.
        // Never reject/duplicate a stationary reading solely by its raw value.
        const auto second_time = sample.acquired_uptime_us;
        ready.registers[{0x68, 0x2d}][0] = 8;
        ready.clock += 10000;
        assert(event_imu.read(sampling::ImuSite::Top, sample) == PortStatus::Ready);
        assert(sample.acquired_uptime_us > second_time);
        assert(event_imu.diagnostic(sampling::ImuSite::Top).raw[0] == 2);
    }
    for (unsigned failed_register : {0x14U, 0x63U, 0x64U, 0x65U}) {
        for (bool fail_write : {false, true}) {
            FakeBus transport;
            transport.registers[{0x68, 0x75}][0] = 0x47;
            if (fail_write) transport.fail_write_reg = failed_register;
            else transport.fail_read_reg = failed_register;
            drivers::DualIcm42688 broken(transport);
            assert(broken.initialize(sampling::ImuSite::Top, 100, true) == ESP_ERR_TIMEOUT);
            assert(!broken.diagnostic(sampling::ImuSite::Top).init_readback.complete);
            assert(broken.diagnostic(sampling::ImuSite::Top).init_readback.drdy_requested);
            before = transport.reads;
            assert(broken.read(sampling::ImuSite::Top, sample) == PortStatus::Error);
            assert(transport.reads == before && !sample.acquired_uptime_us);
            assert(broken.diagnostic(sampling::ImuSite::Top).init_error == ESP_ERR_TIMEOUT);
        }
    }
    {
        FakeBus mismatch;
        mismatch.registers[{0x68, 0x75}][0] = 0x47;
        mismatch.bad_readback_reg = 0x64; mismatch.bad_readback_mask = 0x10;
        drivers::DualIcm42688 broken(mismatch);
        assert(broken.initialize(sampling::ImuSite::Top, 100, true) == ESP_ERR_INVALID_RESPONSE);
        assert(!broken.diagnostic(sampling::ImuSite::Top).init_readback.complete);
    }
    {
        FakeBus failed_final_read;
        failed_final_read.registers[{0x68, 0x75}][0] = 0x47;
        failed_final_read.fail_read_reg = 0x4d; // final clock selection observation
        drivers::DualIcm42688 broken(failed_final_read);
        assert(broken.initialize(sampling::ImuSite::Top, 100, true) == ESP_ERR_TIMEOUT);
        const auto& rb = broken.diagnostic(sampling::ImuSite::Top).init_readback;
        assert(!rb.complete && rb.gyro_config0 == 0x08 && rb.pwr_mgmt0 == 0x0f);
    }

    {
        FakeBus stale;
        stale.registers[{0x68, 0x75}][0] = 0x47;
        stale.registers[{0x68, 0x2d}][0] = 8;
        stale.clear_drdy_on_status = true;
        drivers::DualIcm42688 device(stale);
        before = stale.reads;
        assert(device.prepare_drdy(sampling::ImuSite::Top) == ESP_ERR_INVALID_STATE);
        assert(stale.reads == before); // uninitialized never touches status/I2C
        assert(device.initialize(sampling::ImuSite::Top, 100, true) == ESP_OK);
        const auto before_clock = stale.clock;
        assert(device.prepare_drdy(sampling::ImuSite::Top) == ESP_OK);
        const auto& prepared = device.diagnostic(sampling::ImuSite::Top);
        assert(prepared.startup_status_observed && prepared.startup_status == 8);
        assert(prepared.attempts == 0 && prepared.raw == empty_raw);
        assert(stale.clock == before_clock); // no fake sample timestamp or arbitrary delay
        assert(device.read(sampling::ImuSite::Top, sample) == PortStatus::Unavailable);
        assert(!sample.acquired_uptime_us);
        stale.registers[{0x68, 0x2d}][0] = 8; // the next real update
        stale.clock += 10000;
        assert(device.read(sampling::ImuSite::Top, sample) == PortStatus::Ready);
        assert(sample.acquired_uptime_us == stale.clock);
        stale.fail_read_reg = 0x2d;
        assert(device.prepare_drdy(sampling::ImuSite::Top) == ESP_ERR_TIMEOUT);
        assert(!prepared.startup_status_observed && prepared.drdy_arm_error == ESP_ERR_TIMEOUT);
        assert(prepared.init_error == ESP_OK); // preserve distinct init and arm failure
        stale.fail_read_reg = 0x100;
        stale.registers[{0x68, 0x2d}][0] = 8;
        assert(device.read(sampling::ImuSite::Top, sample) == PortStatus::Ready); // explicit polling can recover
    }

    // TEST_ONLY phase model using the real register driver: a known 100Hz
    // producer plus a nominal 100Hz polling schedule can lose observations
    // when polling moves across a ready boundary. This illustrates a mechanism,
    // not measured clock/jitter values or a claimed hardware root cause.
    auto phase_run = [](bool service_each_update) {
        FakeBus timed;
        timed.registers[{0x68, 0x75}][0] = 0x47;
        drivers::DualIcm42688 device(timed);
        assert(device.initialize(sampling::ImuSite::Top, 100, true) == ESP_OK);
        timed.clear_drdy_on_status = true;
        const auto origin = timed.clock;
        std::uint64_t next_update = origin + 5000;
        unsigned generated = 0, accepted = 0, empty = 0;
        for (unsigned poll = 0; poll < 1000; ++poll) {
            // One bounded phase excursion each 20 cycles; the sensor period
            // remains exactly 10ms throughout both variants.
            timed.clock = service_each_update ? origin + 5000 + poll * 10000 + 500 :
                origin + poll * 10000 + (poll % 20 == 0 ? 6000 : 4000);
            while (next_update <= timed.clock) {
                ++generated;
                timed.registers[{0x68, 0x2d}][0] = 8;
                timed.registers[{0x68, 0x1f}][0] = static_cast<std::uint8_t>(generated >> 8);
                timed.registers[{0x68, 0x1f}][1] = static_cast<std::uint8_t>(generated);
                next_update += 10000;
            }
            sampling::ImuSample observation;
            const auto status = device.read(sampling::ImuSite::Top, observation);
            if (status == PortStatus::Ready) {
                ++accepted;
                assert(observation.acquired_uptime_us == timed.clock);
                assert(device.diagnostic(sampling::ImuSite::Top).raw[0] == static_cast<std::int16_t>(generated));
            } else {
                assert(status == PortStatus::Unavailable && !observation.acquired_uptime_us);
                ++empty;
            }
        }
        assert(accepted + empty == 1000);
        if (service_each_update) assert(generated == 1000 && accepted == 1000 && empty == 0);
        else assert(generated > accepted && empty > 0);
    };
    phase_run(false);
    phase_run(true);

    // TEST_ONLY: reproduce the observed seven requests exactly. Both bank
    // writes succeed, but each following REAL R/0x76 fails with SDK 259.
    // This identifies the operation; it does not prove a physical root cause.
    {
        FakeBus trace_bus;
        trace_bus.clock = 1000000;
        trace_bus.read_time_us = 17; trace_bus.write_time_us = 7;
        trace_bus.registers[{0x69, 0x75}][0] = trace_bus.registers[{0x68, 0x75}][0] = 0x47;
        trace_bus.injected_address = 0x69;
        trace_bus.injected_requests = {5, 7};
        drivers::DualIcm42688 device(trace_bus);
        assert(device.initialize(sampling::ImuSite::Toe, 100, true) == ESP_ERR_INVALID_STATE);
        const auto& init = device.initialization_diagnostic(sampling::ImuSite::Toe);
        assert(init.critical_size == 7 && init.transfers == 7);
        assert(init.bank_restore_attempted);
        assert(init.who_observed && init.actual_who == 0x47);
        const unsigned regs[]{0x76,0x11,0x75,0x76,0x76,0x76,0x76};
        const char operations[]{'W','W','R','W','R','W','R'};
        const drivers::ImuInitPhase phases[]{drivers::ImuInitPhase::InitialBank0,
            drivers::ImuInitPhase::Reset, drivers::ImuInitPhase::WhoAmI,
            drivers::ImuInitPhase::SelectBank1, drivers::ImuInitPhase::SelectBank1,
            drivers::ImuInitPhase::RestoreBank0, drivers::ImuInitPhase::RestoreBank0};
        for (unsigned k = 0; k < init.critical_size; ++k) {
            const auto& access = init.critical[k];
            assert(access.phase == phases[k] && access.operation == operations[k]);
            assert(access.reg == regs[k] && access.length == 1);
            assert(access.started_us >= 1000000 && access.finished_us > access.started_us);
            assert(!access.validation_error);
            if (k == 4 || k == 6) {
                assert(access.error == ESP_ERR_INVALID_STATE && !access.value_observed);
            } else assert(access.error == ESP_OK);
        }
        assert(init.critical[3].value == 1 && init.critical[5].value == 0); // write requests
        assert(init.critical[2].value_observed && init.critical[2].value == 0x47);
        assert(init.first_failure_present);
        assert(init.first_failure.phase == drivers::ImuInitPhase::SelectBank1);
        assert(init.first_failure.operation == 'R' && init.first_failure.reg == 0x76);
        assert(init.first_failure.error == ESP_ERR_INVALID_STATE && !init.first_failure.validation_error);
        assert(init.first_failure.started_us == init.critical[4].started_us);
        assert(device.diagnostic(sampling::ImuSite::Toe).init_error == ESP_ERR_INVALID_STATE);
        assert(device.diagnostic(sampling::ImuSite::Toe).bank_restore_error == ESP_ERR_INVALID_STATE);
        const auto first_failure_time = init.first_failure.finished_us;
        const auto bus_calls = trace_bus.transfers.size();
        assert(device.prepare_drdy(sampling::ImuSite::Toe) == ESP_ERR_INVALID_STATE);
        assert(device.read(sampling::ImuSite::Toe, sample) == PortStatus::Error);
        assert(!sample.acquired_uptime_us && sample.validity == sampling::Validity::Error);
        assert(device.diagnostic(sampling::ImuSite::Toe).raw == empty_raw);
        assert(trace_bus.transfers.size() == bus_calls); // no retry/IRQ-driven I2C work for unready TOE
        assert(init.first_failure.finished_us == first_failure_time && init.transfers == 7);
        assert(device.initialize(sampling::ImuSite::Top, 100, true) == ESP_OK);
        trace_bus.registers[{0x68, 0x2d}][0] = 8;
        trace_bus.registers[{0x68, 0x1f}][1] = 4;
        assert(device.read(sampling::ImuSite::Top, sample) == PortStatus::Ready);
        assert(sample.acquired_uptime_us == trace_bus.clock && sample.validity == sampling::Validity::Valid);
        assert(device.diagnostic(sampling::ImuSite::Top).raw[0] == 4);
        assert(init.first_failure.operation == 'R' && init.first_failure.finished_us == first_failure_time);
    }
    {
        FakeBus writes_fail;
        writes_fail.registers[{0x69, 0x75}][0] = 0x47;
        writes_fail.injected_address = 0x69; writes_fail.injected_requests = {4, 5};
        drivers::DualIcm42688 device(writes_fail);
        assert(device.initialize(sampling::ImuSite::Toe, 100, true) == ESP_ERR_INVALID_STATE);
        const auto& init = device.initialization_diagnostic(sampling::ImuSite::Toe);
        assert(init.transfers == 5 && init.critical_size == 5);
        assert(init.first_failure.operation == 'W' && init.first_failure.reg == 0x76);
        assert(init.first_failure.value == 1 && !init.first_failure.value_observed);
        assert(init.critical[4].phase == drivers::ImuInitPhase::RestoreBank0);
        assert(init.critical[4].operation == 'W' && init.critical[4].value == 0);
        assert(device.diagnostic(sampling::ImuSite::Toe).bank_restore_error == ESP_ERR_INVALID_STATE);
    }
    {
        FakeBus restore_read_fail;
        restore_read_fail.registers[{0x69, 0x75}][0] = 0x47;
        restore_read_fail.injected_address = 0x69; restore_read_fail.injected_requests = {13};
        drivers::DualIcm42688 device(restore_read_fail);
        assert(device.initialize(sampling::ImuSite::Toe, 100, true) == ESP_ERR_INVALID_STATE);
        const auto& init = device.initialization_diagnostic(sampling::ImuSite::Toe);
        assert(init.transfers == 13 && init.critical_size == 7);
        assert(init.first_failure.phase == drivers::ImuInitPhase::RestoreBank0);
        assert(init.first_failure.operation == 'R' && init.first_failure.reg == 0x76);
    }
    {
        FakeBus wrong_identity;
        wrong_identity.registers[{0x69, 0x75}][0] = 0x42;
        drivers::DualIcm42688 device(wrong_identity);
        assert(device.initialize(sampling::ImuSite::Toe, 100, true) == ESP_ERR_INVALID_RESPONSE);
        const auto& init = device.initialization_diagnostic(sampling::ImuSite::Toe);
        assert(init.who_observed && init.actual_who == 0x42); // never substitute expected 0x47
        assert(!init.bank_restore_attempted);
        assert(init.first_failure.validation_error && init.first_failure.value_observed);
        assert(init.first_failure.operation == 'R' && init.first_failure.reg == 0x75);
        assert(init.critical[2].error == ESP_OK); // SDK success vs value validation failure
    }
    {
        FakeBus initial_write_fail;
        initial_write_fail.injected_address = 0x69; initial_write_fail.injected_requests = {1};
        drivers::DualIcm42688 device(initial_write_fail);
        assert(device.initialize(sampling::ImuSite::Toe, 100, true) == ESP_ERR_INVALID_STATE);
        const auto& init = device.initialization_diagnostic(sampling::ImuSite::Toe);
        assert(init.transfers == 1 && init.critical_size == 1 && !init.bank_restore_attempted);
        assert(!init.who_observed && init.first_failure_present);
        assert(init.first_failure.phase == drivers::ImuInitPhase::InitialBank0);
        assert(init.first_failure.operation == 'W' && init.first_failure.reg == 0x76);
        assert(init.first_failure.value == 0 && !init.first_failure.value_observed);
    }
    {
        FakeBus reserved;
        reserved.registers[{0x69, 0x75}][0] = 0x47;
        reserved.bad_readback_reg = 0x76; reserved.bad_readback_mask = 0x80;
        drivers::DualIcm42688 device(reserved);
        assert(device.initialize(sampling::ImuSite::Toe, 100, true) == ESP_ERR_INVALID_RESPONSE);
        const auto& init = device.initialization_diagnostic(sampling::ImuSite::Toe);
        assert(init.first_failure.validation_error && init.first_failure.value == 0x81);
        assert(init.critical[4].error == ESP_OK && init.critical[4].value_observed);
        assert(device.diagnostic(sampling::ImuSite::Toe).bank_restore_error == ESP_ERR_INVALID_RESPONSE);
        // Preserve the old checked8 policy. This is not the observed SDK 259.
    }
    {
        FakeBus success;
        success.registers[{0x69, 0x75}][0] = 0x47;
        drivers::DualIcm42688 device(success);
        assert(device.initialize(sampling::ImuSite::Toe, 100, true) == ESP_OK);
        // Golden bus sequence from the pre-diagnostic driver. No bank read,
        // register readback, write value or explicit delay is removed/added.
        struct Expected { char operation; unsigned reg, write_value; };
        const Expected expected[]{
            {'W',0x76,0},{'W',0x11,1},{'R',0x75,0},
            {'W',0x76,1},{'R',0x76,0},
            {'R',0x7c,0},{'W',0x7c,0x10},{'R',0x7c,0},
            {'R',0x7a,0},{'W',0x7a,0},{'R',0x7a,0},
            {'W',0x76,0},{'R',0x76,0},
            {'R',0x13,0},{'W',0x13,9},{'R',0x13,0},
            {'W',0x4c,0x30},{'R',0x4c,0},{'W',0x4f,8},{'R',0x4f,0},
            {'W',0x50,8},{'R',0x50,0},{'W',0x51,0x16},{'R',0x51,0},
            {'W',0x52,0x11},{'R',0x52,0},{'W',0x53,0x0d},{'R',0x53,0},
            {'W',0x4e,0x0f},{'R',0x4e,0},
            {'R',0x14,0},{'W',0x14,7},{'R',0x14,0},
            {'R',0x63,0},{'W',0x63,0},{'R',0x63,0},
            {'R',0x64,0},{'W',0x64,0},{'R',0x64,0},
            {'R',0x65,0},{'W',0x65,8},{'R',0x65,0},
            {'R',0x4f,0},{'R',0x50,0},{'R',0x4e,0},{'R',0x4d,0},
            {'R',0x14,0},{'R',0x63,0},{'R',0x64,0},{'R',0x65,0}};
        assert(success.transfers.size() == sizeof(expected)/sizeof(expected[0]));
        for (unsigned k = 0; k < success.transfers.size(); ++k) {
            const auto& actual = success.transfers[k]; const auto& want = expected[k];
            assert(actual.address == 0x69 && actual.length == 1);
            assert(actual.operation == want.operation && actual.reg == want.reg);
            if (actual.operation == 'W') assert(actual.requested == want.write_value);
        }
        assert((success.delays == std::vector<unsigned>{2, 50}));
        const auto& init = device.initialization_diagnostic(sampling::ImuSite::Toe);
        assert(init.transfers == 50 && init.critical_size == 7 && !init.first_failure_present);
        assert(init.phase == drivers::ImuInitPhase::Complete && init.who_observed && init.actual_who == 0x47);
    }

    drivers::SoilAds1115 ads(b);
    assert(ads.initialize() == ESP_OK);
    assert(ads.start_conversion(3) == PortStatus::Error);
    assert(ads.start_conversion(1) == PortStatus::Ready);
    assert(b.adc_config == 0x5383);
    assert(ads.start_conversion(2) == PortStatus::Error); // cannot overwrite pending MUX
    sampling::SoilSample soil;
    assert(ads.try_read_conversion(soil) == PortStatus::Unavailable && !soil.raw);
    b.delay_ms(10);
    b.adc_value = 0;
    assert(ads.try_read_conversion(soil) == PortStatus::Ready);
    assert(soil.raw && *soil.raw == 0 && soil.validity == sampling::Validity::Valid);
    assert(ads.start_conversion(2) == PortStatus::Ready);
    b.delay_ms(10); b.adc_config ^= 0x1000;
    assert(ads.try_read_conversion(soil) == PortStatus::Error && !soil.raw);
    assert(ads.start_conversion(0) == PortStatus::Ready);
    b.adc_busy = true; b.delay_ms(10);
    assert(ads.try_read_conversion(soil) == PortStatus::Unavailable);
    b.delay_ms(40);
    assert(ads.try_read_conversion(soil) == PortStatus::Error && !soil.raw);
    assert(ads.last_error() == ESP_ERR_TIMEOUT);
    assert(ads.start_conversion(1) == PortStatus::Error); // old conversion still active
    b.adc_busy = false;
    assert(ads.start_conversion(1) == PortStatus::Ready);
    b.fail_address = 0x48; b.delay_ms(10);
    assert(ads.try_read_conversion(soil) == PortStatus::Error && !soil.raw);
    assert(soil.validity == sampling::Validity::Error);
    b.fail_address = 0;

    // Initialization readback failure leaves no usable/pending conversion;
    // a later, bounded runtime retry can initialize the device again.
    b.adc_bad_readback = true;
    assert(ads.initialize() == ESP_ERR_INVALID_RESPONSE);
    assert(ads.status() == PortStatus::Error && ads.start_conversion(0) == PortStatus::Error);
    assert(ads.last_init_error() == ESP_ERR_INVALID_RESPONSE && ads.last_error() == ESP_ERR_INVALID_RESPONSE);
    const auto failed_init_writes = b.writes.size();
    for (unsigned channel = 0; channel < 3; ++channel) {
        assert(ads.start_conversion(channel) == PortStatus::Error);
        assert(ads.last_error() == ESP_ERR_INVALID_RESPONSE);
    }
    assert(b.writes.size() == failed_init_writes); // no transport work before reinitialization
    b.adc_bad_readback = false;
    b.fail_address = 0x48;
    assert(ads.initialize() == ESP_ERR_TIMEOUT);
    assert(ads.last_init_error() == ESP_ERR_TIMEOUT);
    assert(ads.start_conversion(0) == PortStatus::Error && ads.last_error() == ESP_ERR_TIMEOUT);
    b.fail_address = 0;
    assert(ads.initialize() == ESP_OK);
    assert(ads.last_init_error() == ESP_OK);
    assert(ads.start_conversion(0) == PortStatus::Ready);
    b.delay_ms(drivers::ads_conversion_period_ms);
    b.adc_value = 0xff9c;
    assert(ads.try_read_conversion(soil) == PortStatus::Ready);
    assert(soil.raw && *soil.raw == -100 && soil.acquired_uptime_us == b.clock);

    // A peripheral which NEVER sets OS ready must terminate at the exact
    // engineering deadline. No conversion-register read, zero, or old sample.
    assert(ads.start_conversion(0) == PortStatus::Ready);
    b.adc_busy = true;
    unsigned polls = 0;
    PortStatus state = PortStatus::Unavailable;
    do {
        b.clock += 1000;
        state = ads.try_read_conversion(soil);
        ++polls;
        assert(polls <= drivers::ads_conversion_timeout_us / 1000);
    } while (state == PortStatus::Unavailable);
    assert(state == PortStatus::Error && ads.last_error() == ESP_ERR_TIMEOUT);
    assert(polls == drivers::ads_conversion_timeout_us / 1000);
    assert(!soil.raw && soil.validity == sampling::Validity::Error && !soil.acquired_uptime_us);
    const auto write_count = b.writes.size();
    assert(ads.start_conversion(1) == PortStatus::Error);
    assert(b.writes.size() == write_count); // busy conversion cannot change MUX
    b.adc_busy = false;

    // A ready indication or result arriving after a slow I2C read crosses the
    // deadline is not accepted as an on-time observation.
    assert(ads.start_conversion(2) == PortStatus::Ready);
    b.clock += drivers::ads_conversion_timeout_us - 1;
    b.read_time_us = 1;
    assert(ads.try_read_conversion(soil) == PortStatus::Error);
    assert(ads.last_error() == ESP_ERR_TIMEOUT && !soil.raw);
    b.read_time_us = 0;
    assert(ads.start_conversion(2) == PortStatus::Ready);
    b.clock += drivers::ads_conversion_timeout_us - 2;
    b.read_time_us = 1; // config completes before deadline; result reaches it
    assert(ads.try_read_conversion(soil) == PortStatus::Error);
    assert(ads.last_error() == ESP_ERR_TIMEOUT && !soil.raw);
    b.read_time_us = 0;

    // Runtime can also cancel when its independent poll budget expires (e.g.
    // a nonadvancing injected clock). Cancellation never resets the real ADC.
    assert(ads.start_conversion(1) == PortStatus::Ready);
    b.adc_busy = true;
    ads.cancel_conversion(ESP_ERR_TIMEOUT);
    assert(ads.last_error() == ESP_ERR_TIMEOUT);
    assert(ads.start_conversion(2) == PortStatus::Error);
    b.adc_busy = false;
    assert(ads.start_conversion(2) == PortStatus::Ready);
    b.delay_ms(drivers::ads_conversion_period_ms);
    b.adc_value = 0;
    assert(ads.try_read_conversion(soil) == PortStatus::Ready);
    assert(soil.raw && *soil.raw == 0 && ads.last_error() == ESP_OK);
}
