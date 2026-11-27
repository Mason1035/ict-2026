#include "node/sensors.hpp"
#include "node/board.hpp"
#include <limits>

namespace node::drivers {
namespace {
constexpr std::array<std::uint8_t, 2> imu_address{board::bus::imu_top_address, board::bus::imu_toe_address};
esp_err_t write8(RegisterBus& b, std::uint8_t a, std::uint8_t r, std::uint8_t v) {
    return b.write(a, r, &v, 1);
}
esp_err_t checked8(RegisterBus& b, std::uint8_t a, std::uint8_t r, std::uint8_t v) {
    auto e = write8(b, a, r, v);
    std::uint8_t got = 0;
    if (e == ESP_OK) e = b.read(a, r, &got, 1);
    return e != ESP_OK ? e : (got == v ? ESP_OK : ESP_ERR_INVALID_RESPONSE);
}
// Interface selection only; reserved and unrelated bits survive. DS-000347
// v1.6 section 12.3, not a sensor calibration or signal-path parameter.
esp_err_t masked8(RegisterBus& b, std::uint8_t a, std::uint8_t reg,
                  std::uint8_t mask, std::uint8_t value) {
    std::uint8_t before = 0, after = 0;
    auto error = b.read(a, reg, &before, 1);
    if (error != ESP_OK) return error;
    const auto desired = static_cast<std::uint8_t>((before & ~mask) | (value & mask));
    error = write8(b, a, reg, desired);
    if (error == ESP_OK) error = b.read(a, reg, &after, 1);
    return error != ESP_OK ? error :
        ((after & mask) == (desired & mask) ? ESP_OK : ESP_ERR_INVALID_RESPONSE);
}
// Observe existing init operations without adding a register access, retry or
// delay. The selected bank remains the device's real state, never a cache.
class InitializationBus final : public RegisterBus {
public:
    InitializationBus(RegisterBus& bus, ImuInitTrace& trace) : bus_(bus), trace_(trace) {}
    void phase(ImuInitPhase phase) {
        trace_.phase = phase;
        if (phase == ImuInitPhase::RestoreBank0) trace_.bank_restore_attempted = true;
    }
    esp_err_t read(std::uint8_t address, std::uint8_t reg, std::uint8_t* out, std::size_t n) override {
        ImuInitAccess access{};
        access.phase = trace_.phase; access.operation = 'R'; access.reg = reg;
        access.length = static_cast<std::uint8_t>(n); access.started_us = bus_.now_us();
        access.error = bus_.read(address, reg, out, n);
        access.finished_us = bus_.now_us();
        access.value_observed = access.error == ESP_OK && out && n == 1;
        if (access.value_observed) access.value = out[0];
        if (trace_.phase == ImuInitPhase::WhoAmI) {
            trace_.who_observed = access.value_observed;
            trace_.actual_who = access.value;
        }
        observe(access); return access.error;
    }
    esp_err_t write(std::uint8_t address, std::uint8_t reg, const std::uint8_t* data, std::size_t n) override {
        ImuInitAccess access{};
        access.phase = trace_.phase; access.operation = 'W'; access.reg = reg;
        access.length = static_cast<std::uint8_t>(n);
        if (data && n == 1) access.value = data[0]; // request, never claimed readback
        access.started_us = bus_.now_us();
        access.error = bus_.write(address, reg, data, n);
        access.finished_us = bus_.now_us();
        observe(access); return access.error;
    }
    void delay_ms(unsigned ms) override { bus_.delay_ms(ms); }
    std::uint64_t now_us() const override { return bus_.now_us(); }
    void result(esp_err_t error, bool compound_validation = false) {
        if (error == ESP_OK || trace_.first_failure_present) return;
        auto failure = last_;
        failure.error = error; failure.validation_error = true;
        if (compound_validation) {
            // The final check compares several prior real readbacks. Do not
            // falsely identify its last read as the particular bad register.
            failure.operation = 'V'; failure.reg = 0xff; failure.length = 0;
            failure.value = 0; failure.value_observed = false;
            failure.started_us = failure.finished_us = bus_.now_us();
        }
        trace_.first_failure = failure; trace_.first_failure_present = true;
    }
private:
    void observe(const ImuInitAccess& access) {
        last_ = access;
        ++trace_.transfers;
        if (access.phase == ImuInitPhase::InitialBank0 || access.phase == ImuInitPhase::Reset ||
                access.phase == ImuInitPhase::WhoAmI || access.phase == ImuInitPhase::SelectBank1 ||
                access.phase == ImuInitPhase::RestoreBank0) {
            if (trace_.critical_size < trace_.critical.size()) trace_.critical[trace_.critical_size++] = access;
        }
        if (access.error != ESP_OK && !trace_.first_failure_present) {
            trace_.first_failure = access; trace_.first_failure_present = true;
        }
    }
    RegisterBus& bus_;
    ImuInitTrace& trace_;
    ImuInitAccess last_{};
};
struct InitializationResult {
    ImuDiagnostic& diagnostic;
    InitializationBus& bus;
    ~InitializationResult() {
        diagnostic.init_error = diagnostic.error;
        bus.result(diagnostic.error);
        if (diagnostic.error == ESP_OK) bus.phase(ImuInitPhase::Complete);
    }
};
esp_err_t read16(RegisterBus& b, std::uint8_t reg, std::uint16_t& value) {
    std::uint8_t bytes[2]{};
    const auto e = b.read(board::bus::ads1115_address, reg, bytes, 2);
    value = (static_cast<unsigned>(bytes[0]) << 8) | bytes[1];
    return e;
}
esp_err_t write16(RegisterBus& b, std::uint8_t reg, std::uint16_t value) {
    const std::uint8_t bytes[]{static_cast<std::uint8_t>(value >> 8), static_cast<std::uint8_t>(value)};
    return b.write(board::bus::ads1115_address, reg, bytes, 2);
}
}
std::int16_t signed_be(const std::uint8_t* p) {
    const auto u = static_cast<std::uint16_t>((static_cast<unsigned>(p[0]) << 8) | p[1]);
    return static_cast<std::int16_t>(u < 0x8000 ? static_cast<int>(u) : static_cast<int>(u) - 65536);
}
esp_err_t DualIcm42688::initialize(sampling::ImuSite site, unsigned odr, bool drdy) {
    const auto i = static_cast<unsigned>(site);
    if (i >= ready_.size() || (odr != 100 && odr != 200)) return ESP_ERR_INVALID_ARG;
    if (initializing_[i].exchange(true, std::memory_order_acq_rel)) return ESP_ERR_INVALID_STATE;
    struct ReleaseInitialization {
        std::atomic<bool>& active;
        ~ReleaseInitialization() { active.store(false, std::memory_order_release); }
    } release{initializing_[i]};
    ready_[i] = false;
    diag_[i] = {};
    diag_[i].init_readback.drdy_requested = drdy;
    init_trace_[i] = {};
    InitializationBus init(bus_, init_trace_[i]);
    const auto a = imu_address[i];
    auto& error = diag_[i].error;
    InitializationResult remember{diag_[i], init};
    // DS-000347: bank 0, reset, >=1 ms, WHO_AM_I; no inherited Arduino state.
    init.phase(ImuInitPhase::InitialBank0);
    error = write8(init, a, 0x76, 0);
    if (error == ESP_OK) {
        init.phase(ImuInitPhase::Reset);
        error = write8(init, a, 0x11, 1);
    }
    if (error != ESP_OK) return error;
    init.delay_ms(2);
    init.phase(ImuInitPhase::WhoAmI);
    std::uint8_t who = 0;
    error = init.read(a, 0x75, &who, 1);
    if (error == ESP_OK && who != 0x47) error = ESP_ERR_INVALID_RESPONSE;
    if (error != ESP_OK) return error;
    // Apply the manufacturer's I2C interface settings explicitly. Prior
    // firmware retained reset-default I3C SDR/DDR enables and slew settings.
    // This corrects a documented configuration gap; hardware retest must still
    // establish whether it changes the observed NACK/timeout failure rate.
    init.phase(ImuInitPhase::SelectBank1);
    error = checked8(init, a, 0x76, 1); // bank 1
    init.result(error);
    if (error == ESP_OK) init.phase(ImuInitPhase::InterfaceSettings);
    if (error == ESP_OK) error = masked8(init, a, 0x7c, 0x13, 0x10); // I3C_EN=1, SDR/DDR=0
    if (error == ESP_OK) error = masked8(init, a, 0x7a, 0x40, 0x00); // I3C_BUS_MODE=0
    const auto interface_error = error;
    init.result(interface_error);
    // Always attempt one bank-0 restoration, including a failed bank-1 access.
    // Preserve both causes; do not sample if either initialization path failed.
    init.phase(ImuInitPhase::RestoreBank0);
    diag_[i].bank_restore_error = checked8(init, a, 0x76, 0);
    init.result(diag_[i].bank_restore_error);
    error = interface_error != ESP_OK ? interface_error : diag_[i].bank_restore_error;
    if (error != ESP_OK) return error;
    init.phase(ImuInitPhase::Drive);
    error = masked8(init, a, 0x13, 0x3f, 0x09); // I2C/SPI slew rate fields both 1
    if (error != ESP_OK) return error;
    const std::uint8_t rate = odr == 100 ? 0x08 : 0x07;
    // +/-16g, +/-2000dps, LN; factory UI filter registers explicitly checked.
    // These are acquisition settings awaiting B review, not calibrated DSP.
    init.phase(ImuInitPhase::AcquisitionConfig);
    for (const auto rv : {std::array<std::uint8_t, 2>{0x4c, 0x30},
             {0x4f, rate}, {0x50, rate}, {0x51, 0x16}, {0x52, 0x11}, {0x53, 0x0d}}) {
        error = checked8(init, a, rv[0], rv[1]);
        if (error != ESP_OK) return error;
    }
    init.phase(ImuInitPhase::Power);
    error = write8(init, a, 0x4e, 0x0f);
    if (error != ESP_OK) return error;
    // No register writes for >=200us after OFF->LN; gyro warmup >=45ms.
    init.delay_ms(50);
    std::uint8_t power = 0;
    error = init.read(a, 0x4e, &power, 1);
    if (error == ESP_OK && power != 0x0f) error = ESP_ERR_INVALID_RESPONSE;
    if (error != ESP_OK) return error;
    if (drdy) {
        init.phase(ImuInitPhase::Drdy);
        // DS-000347 v1.6 sections 12.6 / 14.3 / 14.49-51. Only the sensor
        // interrupt route is configured here; the runtime owns frozen GPIO4/5.
        // Latched active-high push-pull avoids pulse-width dependence. Status
        // reading clears ready as before; ISR notifications are not samples.
        error = masked8(init, a, 0x14, 0x07, 0x07);
        if (error == ESP_OK) error = masked8(init, a, 0x63, 0x30, 0x00);
        if (error == ESP_OK) error = masked8(init, a, 0x64, 0x10, 0x00);
        // UI_DRDY is the only INT1 source. These are device register bits,
        // unrelated to the frozen Telemetry reason_mask / Risk bit table.
        if (error == ESP_OK) error = masked8(init, a, 0x65, 0x7f, 0x08);
        if (error != ESP_OK) return error;
    }
    init.phase(ImuInitPhase::FinalReadback);
    auto& readback = diag_[i].init_readback;
    struct RegisterReadback { std::uint8_t reg; std::uint8_t* destination; };
    const RegisterReadback registers[]{{0x4f, &readback.gyro_config0},
        {0x50, &readback.accel_config0}, {0x4e, &readback.pwr_mgmt0},
        {0x4d, &readback.intf_config1}, {0x14, &readback.int_config},
        {0x63, &readback.int_config0}, {0x64, &readback.int_config1},
        {0x65, &readback.int_source0}};
    for (const auto& reg : registers) {
        error = init.read(a, reg.reg, reg.destination, 1);
        if (error != ESP_OK) return error;
    }
    if (readback.gyro_config0 != rate || readback.accel_config0 != rate ||
        readback.pwr_mgmt0 != 0x0f || (drdy && ((readback.int_config & 0x07) != 0x07 ||
        (readback.int_config0 & 0x30) != 0 || (readback.int_config1 & 0x10) != 0 ||
        (readback.int_source0 & 0x7f) != 0x08))) error = ESP_ERR_INVALID_RESPONSE;
    init.result(error, true);
    readback.complete = error == ESP_OK;
    ready_[i] = error == ESP_OK;
    return error;
}
esp_err_t DualIcm42688::prepare_drdy(sampling::ImuSite site) {
    const auto i = static_cast<unsigned>(site);
    if (i >= ready_.size()) return ESP_ERR_INVALID_ARG;
    auto& d = diag_[i];
    d.startup_status_observed = false;
    d.startup_status = 0;
    if (!ready_[i] || !d.init_readback.drdy_requested) {
        d.drdy_arm_error = ESP_ERR_INVALID_STATE;
        return d.drdy_arm_error;
    }
    // DS-000347 INT_CONFIG0.UI_DRDY_INT_CLEAR=00: reading INT_STATUS
    // clears a previously latched DRDY. Do this BEFORE the capture epoch and
    // GPIO enable. A failure leaves the pin disabled; polling can still report
    // actual reads/errors. No data, timestamp, or Valid counter is fabricated.
    d.drdy_arm_error = bus_.read(imu_address[i], 0x2d, &d.startup_status, 1);
    d.startup_status_observed = d.drdy_arm_error == ESP_OK;
    return d.drdy_arm_error;
}
PortStatus DualIcm42688::status() const {
    return ready_[0] && ready_[1] ? PortStatus::Ready : PortStatus::Error;
}
PortStatus DualIcm42688::read(sampling::ImuSite site, sampling::ImuSample& out) {
    out = {};
    const auto i = static_cast<unsigned>(site);
    if (i >= ready_.size()) { out.validity = sampling::Validity::Error; return PortStatus::Error; }
    auto& d = diag_[i];
    d.raw = {};
    d.stage = ImuReadStage::NotReady;
    d.status_observed = false; d.status = 0;
    ++d.attempts;
    auto fail = [&]() { out = {}; out.validity = sampling::Validity::Error; return PortStatus::Error; };
    if (!ready_[i]) { d.error = ESP_ERR_INVALID_STATE; return fail(); }
    std::uint8_t status = 0;
    d.stage = ImuReadStage::Status;
    d.error = bus_.read(imu_address[i], 0x2d, &status, 1);
    if (d.error != ESP_OK) { ++d.status_failures; return fail(); }
    d.status_observed = true; d.status = status;
    if (!(status & 0x08)) {
        d.stage = ImuReadStage::NoData; ++d.empty_polls;
        return PortStatus::Unavailable; // no NEW observation
    }
    std::uint8_t raw[12]{};
    d.stage = ImuReadStage::Raw;
    d.error = bus_.read(imu_address[i], 0x1f, raw, sizeof(raw));
    if (d.error != ESP_OK) { ++d.ready_data_read_failures; return fail(); }
    d.stage = ImuReadStage::Decode;
    std::array<std::int16_t, 6> decoded{};
    for (unsigned k = 0; k < 6; ++k) {
        decoded[k] = signed_be(raw + 2 * k);
        // FIFO_HOLD_LAST_DATA_EN=0: -32768 is the sensor's invalid code.
        if (decoded[k] == std::numeric_limits<std::int16_t>::min()) {
            ++d.invalid_raw_codes; d.error = ESP_ERR_INVALID_RESPONSE; return fail();
        }
    }
    d.raw = decoded;
    for (unsigned k = 0; k < 3; ++k) {
        out.acceleration_mps2[k] = d.raw[k] * (standard_gravity / accel_lsb_per_g);
        out.angular_rate_dps[k] = d.raw[k + 3] / gyro_lsb_per_dps;
    }
    out.acquired_uptime_us = bus_.now_us(); // host read completion, NOT synchronized sensor clock
    out.validity = sampling::Validity::Valid;
    d.stage = ImuReadStage::Complete;
    return PortStatus::Ready;
}
esp_err_t SoilAds1115::initialize() {
    pending_ = ready_ = false;
    config_ = 0;
    started_us_ = 0;
    // Single-shot, AIN0-GND, +/-4.096V, 128SPS, comparator disabled.
    // ADS1115 has no WHO_AM_I; readback is configuration validation, not unique ID.
    error_ = write16(bus_, 1, 0x4383);
    std::uint16_t got = 0;
    if (error_ == ESP_OK) error_ = read16(bus_, 1, got);
    if (error_ == ESP_OK && (got & 0x7fff) != 0x4383) error_ = ESP_ERR_INVALID_RESPONSE;
    ready_ = error_ == ESP_OK;
    init_error_ = error_;
    return error_;
}
PortStatus SoilAds1115::start_conversion(unsigned channel) {
    if (!ready_) {
        // Preserve the initialization transport/readback failure. Repeated
        // calls before the bounded runtime reinit must not replace its cause.
        error_ = init_error_;
        return PortStatus::Error;
    }
    if (pending_ || channel > board::bus::soil_toe_channel) {
        error_ = ESP_ERR_INVALID_STATE; return PortStatus::Error;
    }
    std::uint16_t state = 0;
    error_ = read16(bus_, 1, state);
    // After timeout never change MUX while a previous conversion is still active.
    if (error_ == ESP_OK && !(state & 0x8000)) error_ = ESP_ERR_INVALID_STATE;
    if (error_ != ESP_OK) return PortStatus::Error;
    config_ = static_cast<std::uint16_t>(0xc383 | (channel << 12));
    error_ = write16(bus_, 1, config_);
    if (error_ != ESP_OK) return PortStatus::Error;
    started_us_ = bus_.now_us(); pending_ = true;
    return PortStatus::Ready;
}
PortStatus SoilAds1115::try_read_conversion(sampling::SoilSample& out) {
    out = {};
    auto fail = [&]() { cancel_conversion(error_); out.validity = sampling::Validity::Error; return PortStatus::Error; };
    if (!pending_) { error_ = ESP_ERR_INVALID_STATE; return fail(); }
    const auto elapsed = bus_.now_us() - started_us_;
    if (elapsed >= ads_conversion_timeout_us) { error_ = ESP_ERR_TIMEOUT; return fail(); }
    error_ = ESP_OK;
    if (elapsed < static_cast<std::uint64_t>(ads_conversion_period_ms) * 1000U)
        return PortStatus::Unavailable;
    std::uint16_t state = 0;
    error_ = read16(bus_, 1, state);
    if (error_ != ESP_OK) return fail();
    if (bus_.now_us() - started_us_ >= ads_conversion_timeout_us) {
        error_ = ESP_ERR_TIMEOUT; return fail();
    }
    if ((state & 0x7fff) != (config_ & 0x7fff)) { error_ = ESP_ERR_INVALID_RESPONSE; return fail(); }
    if (!(state & 0x8000)) return PortStatus::Unavailable;
    std::uint16_t value = 0;
    error_ = read16(bus_, 0, value);
    if (error_ != ESP_OK) return fail();
    if (bus_.now_us() - started_us_ >= ads_conversion_timeout_us) {
        error_ = ESP_ERR_TIMEOUT; return fail();
    }
    const std::uint8_t bytes[]{static_cast<std::uint8_t>(value >> 8), static_cast<std::uint8_t>(value)};
    out.raw = signed_be(bytes); // zero is a valid measured code, never a missing sentinel
    out.acquired_uptime_us = bus_.now_us();
    out.validity = sampling::Validity::Valid;
    pending_ = false;
    return PortStatus::Ready;
}
void SoilAds1115::cancel_conversion(esp_err_t reason) {
    pending_ = false;
    config_ = 0;
    started_us_ = 0;
    error_ = reason;
}
}
