#pragma once
#include "node/ports.hpp"
#include "esp_err.h"
#include <atomic>

namespace node::drivers {
// Testable register boundary; production implementation serializes each short
// transfer through the EXISTING runtime mutex. Delays never hold that mutex.
class RegisterBus {
public:
    virtual ~RegisterBus() = default;
    virtual esp_err_t read(std::uint8_t address, std::uint8_t reg, std::uint8_t*, std::size_t) = 0;
    virtual esp_err_t write(std::uint8_t address, std::uint8_t reg, const std::uint8_t*, std::size_t) = 0;
    virtual void delay_ms(unsigned) = 0;
    virtual std::uint64_t now_us() const = 0;
};
// Diagnostic acquisition settings, NOT B's calibrated feature/filter parameters.
inline constexpr unsigned imu_odr_hz = 100;
inline constexpr float accel_lsb_per_g = 2048.0f; // FS_SEL=0: +/-16 g
inline constexpr float gyro_lsb_per_dps = 16.4f; // FS_SEL=0: +/-2000 dps (DS-000347)
inline constexpr float standard_gravity = 9.80665f;
inline constexpr unsigned ads_pga_mv = 4096, ads_sps = 128;
// Round the configured single-shot conversion period up to whole milliseconds.
// Five periods is an engineering liveness deadline, NOT a calibration parameter.
inline constexpr unsigned ads_conversion_period_ms = (1000U + ads_sps - 1U) / ads_sps;
inline constexpr std::uint64_t ads_conversion_timeout_us =
    static_cast<std::uint64_t>(ads_conversion_period_ms) * 5U * 1000U;
std::int16_t signed_be(const std::uint8_t*);
enum class ImuReadStage : std::uint8_t { NotReady, Status, NoData, Raw, Decode, Complete };
inline constexpr const char* imu_stage_name(ImuReadStage stage) {
    switch (stage) {
    case ImuReadStage::NotReady: return "not_ready";
    case ImuReadStage::Status: return "status_0x2d";
    case ImuReadStage::NoData: return "no_new_data";
    case ImuReadStage::Raw: return "raw_0x1f";
    case ImuReadStage::Decode: return "invalid_raw_code";
    case ImuReadStage::Complete: return "complete";
    }
    return "unknown";
}
struct ImuInitReadback {
    // Actual final bank-0 register observations, never expected-value aliases.
    // complete=false preserves the fact that a later register read failed.
    std::uint8_t gyro_config0 = 0, accel_config0 = 0, pwr_mgmt0 = 0, intf_config1 = 0;
    std::uint8_t int_config = 0, int_config0 = 0, int_config1 = 0, int_source0 = 0;
    bool complete = false, drdy_requested = false;
};
struct ImuDiagnostic {
    std::array<std::int16_t, 6> raw{}; // only usable when returned sample is Valid
    esp_err_t error = ESP_OK;
    esp_err_t init_error = ESP_ERR_INVALID_STATE, bank_restore_error = ESP_OK;
    // Pre-capture interrupt preparation is not an acquisition attempt/sample.
    esp_err_t drdy_arm_error = ESP_ERR_INVALID_STATE;
    bool startup_status_observed = false;
    std::uint8_t startup_status = 0;
    ImuInitReadback init_readback{};
    ImuReadStage stage = ImuReadStage::NotReady;
    bool status_observed = false;
    std::uint8_t status = 0;
    // A ready-status read followed by a failed data read is a lost
    // acquisition attempt, not a reusable sample or an ordinary empty poll.
    std::uint64_t attempts = 0, status_failures = 0, ready_data_read_failures = 0;
    std::uint64_t invalid_raw_codes = 0, empty_polls = 0;
};
enum class ImuInitPhase : std::uint8_t {
    NotStarted, InitialBank0, Reset, WhoAmI, SelectBank1, InterfaceSettings,
    RestoreBank0, Drive, AcquisitionConfig, Power, Drdy, FinalReadback, Complete
};
inline constexpr const char* imu_init_phase_name(ImuInitPhase phase) {
    switch (phase) {
    case ImuInitPhase::NotStarted: return "not_started";
    case ImuInitPhase::InitialBank0: return "initial_bank0";
    case ImuInitPhase::Reset: return "reset";
    case ImuInitPhase::WhoAmI: return "who_am_i";
    case ImuInitPhase::SelectBank1: return "select_bank1";
    case ImuInitPhase::InterfaceSettings: return "interface_settings";
    case ImuInitPhase::RestoreBank0: return "restore_bank0";
    case ImuInitPhase::Drive: return "drive";
    case ImuInitPhase::AcquisitionConfig: return "acquisition_config";
    case ImuInitPhase::Power: return "power";
    case ImuInitPhase::Drdy: return "drdy";
    case ImuInitPhase::FinalReadback: return "final_readback";
    case ImuInitPhase::Complete: return "complete";
    }
    return "unknown";
}
struct ImuInitAccess {
    ImuInitPhase phase = ImuInitPhase::NotStarted;
    char operation = '?'; // W=requested value; R=value only if value_observed
    std::uint8_t reg = 0, length = 0, value = 0;
    bool value_observed = false, validation_error = false;
    esp_err_t error = ESP_OK;
    std::uint64_t started_us = 0, finished_us = 0; // actual host operation boundaries
};
struct ImuInitTrace {
    // Fixed startup-only evidence, independent of the 100Hz sample diagnostic.
    // Initial W76, W11, R75, bank1 W/R76 and restore W/R76 need at most 7 slots.
    std::array<ImuInitAccess, 8> critical{};
    unsigned critical_size = 0, transfers = 0;
    ImuInitPhase phase = ImuInitPhase::NotStarted;
    bool first_failure_present = false, who_observed = false;
    bool bank_restore_attempted = false;
    std::uint8_t actual_who = 0;
    ImuInitAccess first_failure{};
};
class DualIcm42688 final : public Icm42688p {
public:
    explicit DualIcm42688(RegisterBus& bus) : bus_(bus) {}
    esp_err_t initialize(sampling::ImuSite, unsigned odr_hz = imu_odr_hz, bool drdy = false);
    esp_err_t prepare_drdy(sampling::ImuSite); // real INT_STATUS read; no invented observation
    PortStatus status() const override;
    PortStatus read(sampling::ImuSite, sampling::ImuSample&) override;
    const ImuDiagnostic& diagnostic(sampling::ImuSite s) const { return diag_[static_cast<unsigned>(s)]; }
    const ImuInitTrace& initialization_diagnostic(sampling::ImuSite s) const {
        return init_trace_[static_cast<unsigned>(s)];
    }
private:
    RegisterBus& bus_;
    // Reject recursive/overlapping initialization of the same site before it
    // can reset the active attempt's Ready/diagnostic/trace. Other APIs still
    // require the existing single-owner discipline; this is not a general
    // concurrent read/diagnostic API or a hardware recovery/retry mechanism.
    std::array<std::atomic<bool>, 2> initializing_{{false, false}};
    std::array<bool, 2> ready_{};
    std::array<ImuDiagnostic, 2> diag_{};
    std::array<ImuInitTrace, 2> init_trace_{}; // not copied into runtime sample/Health snapshots
};
class SoilAds1115 final : public Ads1115 {
public:
    explicit SoilAds1115(RegisterBus& bus) : bus_(bus) {}
    esp_err_t initialize();
    PortStatus status() const override { return ready_ ? PortStatus::Ready : PortStatus::Error; }
    PortStatus start_conversion(unsigned channel) override;
    PortStatus try_read_conversion(sampling::SoilSample&) override;
    // Cancels the software request only. The next start still checks the
    // hardware OS bit before changing MUX; no reset or fabricated observation.
    void cancel_conversion(esp_err_t reason);
    esp_err_t last_error() const { return error_; }
    esp_err_t last_init_error() const { return init_error_; }
private:
    RegisterBus& bus_;
    bool ready_ = false, pending_ = false;
    std::uint16_t config_ = 0;
    std::uint64_t started_us_ = 0;
    esp_err_t error_ = ESP_OK;
    esp_err_t init_error_ = ESP_ERR_INVALID_STATE;
};
} // namespace node::drivers
