#include "node/telemetry.hpp"
#include <cmath>
#include <cinttypes>
#include <cstdio>
#include <cstring>

namespace node::comm {
namespace {
bool finite(std::optional<float> x) { return !x || std::isfinite(*x); }
bool pct(std::optional<float> x) { return finite(x) && (!x || (*x >= 0 && *x <= 100)); }
const char* level(protocol::RiskLevel v) {
    switch (v) {
    case protocol::RiskLevel::Normal: return "NORMAL";
    case protocol::RiskLevel::Watch: return "WATCH";
    case protocol::RiskLevel::Warning: return "WARNING";
    case protocol::RiskLevel::Emergency: return "EMERGENCY";
    }
    return "";
}
class Writer {
public:
    Writer(char* out, std::size_t size) : out_(out), capacity_(size) { if (size) out[0] = 0; }
    void text(std::string_view s) {
        if (!ok_ || s.size() >= capacity_ - used_) { ok_ = false; return; }
        std::memcpy(out_ + used_, s.data(), s.size()); used_ += s.size(); out_[used_] = 0;
    }
    void string(std::string_view s) {
        text("\"");
        for (const unsigned char c : s) {
            if (c == '"' || c == '\\') { text("\\"); const char x = c; text({&x, 1}); }
            else if (c < 0x20) { char hex[7]; std::snprintf(hex, sizeof(hex), "\\u%04x", c); text(hex); }
            else { const char x = c; text({&x, 1}); }
        }
        text("\"");
    }
    void number(std::uint64_t n) { char s[24]; std::snprintf(s, sizeof(s), "%" PRIu64, n); text(s); }
    void value(std::optional<float> n) {
        if (!n) { text("null"); return; }
        char s[32]; std::snprintf(s, sizeof(s), "%.9g", static_cast<double>(*n)); text(s);
    }
    void raw(std::optional<std::int16_t> n) {
        if (!n) { text("null"); return; }
        char s[16]; std::snprintf(s, sizeof(s), "%d", static_cast<int>(*n)); text(s);
    }
    void boolean(bool b) { text(b ? "true" : "false"); }
    bool ok() const { return ok_; }
    std::size_t size() const { return used_; }
private:
    char* out_; std::size_t capacity_, used_ = 0; bool ok_ = true;
};
bool valid(const protocol::TelemetryDraft& d) {
    using namespace protocol;
    if (d.schema_name != schema || d.site_id.empty() || !d.identity || d.identity->device_id.empty()) return false;
    if (d.identity->boot_id > json_safe_integer_max || d.identity->seq > json_safe_integer_max ||
        d.uptime_ms > json_safe_integer_max || (d.timestamp_ms && *d.timestamp_ms > json_safe_integer_max) ||
        d.time_synced != d.timestamp_ms.has_value()) return false;
    if (d.imu[0].id != "top" || d.imu[1].id != "toe") return false;
    for (const auto& i : d.imu) {
        for (auto v : {i.ax, i.ay, i.az, i.gx, i.gy, i.gz, i.tilt_deg, i.tilt_rate_dps, i.vibration_rms})
            if (!finite(v) || (!i.valid && v)) return false;
        if (i.valid && (!i.ax || !i.ay || !i.az || !i.gx || !i.gy || !i.gz)) return false;
    }
    for (auto p : {d.soil.top_pct, d.soil.middle_pct, d.soil.toe_pct, d.soil.avg_pct}) if (!pct(p)) return false;
    if (!finite(d.soil.growth_pct_min) || (d.experiment.rain_level && *d.experiment.rain_level > 3)) return false;
    if (d.risk.sensor_score) {
        if (!d.risk.level || classify(d.risk.sensor_score) != d.risk.level) return false;
    } else if (d.risk.level || d.risk.reason_mask) return false;
    if (d.risk.reason_mask && *d.risk.reason_mask > json_safe_integer_max) return false;
    return true;
}
}
bool topic_segment(std::string_view s) {
    if (s.empty()) return false;
    for (const unsigned char c : s) if (c < 0x20 || c == '/' || c == '+' || c == '#') return false;
    return true;
}
protocol::TelemetryDraft make_draft(const sampling::SensorSnapshot& s, std::uint64_t now) {
    protocol::TelemetryDraft d;
    d.uptime_ms = now / 1000;
    bool complete = true;
    for (unsigned k = 0; k < 2; ++k) {
        const auto& v = s.imu[k]; auto& i = d.imu[k];
        // Driver liveness bounds only; not a calibrated feature-window Missing Policy.
        i.valid = v.validity == sampling::Validity::Valid && v.acquired_uptime_us &&
            now >= *v.acquired_uptime_us && now - *v.acquired_uptime_us <= 30000;
        if (i.valid) {
            i.ax = v.acceleration_mps2[0]; i.ay = v.acceleration_mps2[1]; i.az = v.acceleration_mps2[2];
            i.gx = v.angular_rate_dps[0]; i.gy = v.angular_rate_dps[1]; i.gz = v.angular_rate_dps[2];
        }
        complete = complete && i.valid;
    }
    std::optional<std::int16_t>* soil[]{&d.soil.top_raw, &d.soil.middle_raw, &d.soil.toe_raw};
    for (unsigned k = 0; k < 3; ++k) {
        const auto& v = s.soil[k];
        const bool ok = v.validity == sampling::Validity::Valid && v.raw && v.acquired_uptime_us &&
            now >= *v.acquired_uptime_us && now - *v.acquired_uptime_us <= 1500000;
        if (ok) *soil[k] = v.raw;
        complete = complete && ok;
    }
    d.system.sensor_degraded = !complete;
    return d; // all calibration-dependent fields and UTC remain null
}
protocol::SerializeResult V2Serializer::encode(const protocol::TelemetryDraft& d, char* out, std::size_t size) {
    using protocol::SerializeStatus;
    if (out && size) out[0] = 0;
    if (!valid(d)) return {SerializeStatus::InvalidDraft, 0};
    if (!out || !size) return {SerializeStatus::BufferTooSmall, 0};
    Writer w(out, size);
    w.text("{\"schema\":"); w.string(d.schema_name);
    w.text(",\"site_id\":"); w.string(d.site_id);
    w.text(",\"device_id\":"); w.string(d.identity->device_id);
    w.text(",\"boot_id\":"); w.number(d.identity->boot_id);
    w.text(",\"seq\":"); w.number(d.identity->seq);
    w.text(",\"timestamp_ms\":"); if (d.timestamp_ms) w.number(*d.timestamp_ms); else w.text("null");
    w.text(",\"uptime_ms\":"); w.number(d.uptime_ms);
    w.text(",\"time_synced\":"); w.boolean(d.time_synced);
    w.text(",\"imu\":[");
    for (unsigned k = 0; k < 2; ++k) {
        if (k) w.text(",");
        const auto& i = d.imu[k];
        w.text("{\"id\":"); w.string(i.id);
        w.text(",\"ax\":"); w.value(i.ax); w.text(",\"ay\":"); w.value(i.ay); w.text(",\"az\":"); w.value(i.az);
        w.text(",\"gx\":"); w.value(i.gx); w.text(",\"gy\":"); w.value(i.gy); w.text(",\"gz\":"); w.value(i.gz);
        w.text(",\"tilt_deg\":"); w.value(i.tilt_deg); w.text(",\"tilt_rate_dps\":"); w.value(i.tilt_rate_dps);
        w.text(",\"vibration_rms\":"); w.value(i.vibration_rms); w.text(",\"valid\":"); w.boolean(i.valid); w.text("}");
    }
    w.text("],\"soil\":{\"top_raw\":"); w.raw(d.soil.top_raw);
    w.text(",\"middle_raw\":"); w.raw(d.soil.middle_raw); w.text(",\"toe_raw\":"); w.raw(d.soil.toe_raw);
    w.text(",\"top_pct\":"); w.value(d.soil.top_pct); w.text(",\"middle_pct\":"); w.value(d.soil.middle_pct);
    w.text(",\"toe_pct\":"); w.value(d.soil.toe_pct); w.text(",\"avg_pct\":"); w.value(d.soil.avg_pct);
    w.text(",\"growth_pct_min\":"); w.value(d.soil.growth_pct_min);
    w.text("},\"experiment\":{\"run_id\":"); if (d.experiment.run_id) w.string(*d.experiment.run_id); else w.text("null");
    w.text(",\"rain_level\":"); if (d.experiment.rain_level) w.number(*d.experiment.rain_level); else w.text("null");
    w.text("},\"risk\":{\"sensor_score\":"); w.value(d.risk.sensor_score);
    w.text(",\"level\":"); if (d.risk.level) w.string(level(*d.risk.level)); else w.text("null");
    w.text(",\"reason_mask\":"); if (d.risk.reason_mask) w.number(*d.risk.reason_mask); else w.text("null");
    w.text("},\"system\":{\"wifi_up\":"); w.boolean(d.system.wifi_up);
    w.text(",\"mqtt_up\":"); w.boolean(d.system.mqtt_up); w.text(",\"lora_ready\":"); w.boolean(d.system.lora_ready);
    w.text(",\"sd_ok\":"); w.boolean(d.system.sd_ok); w.text(",\"edge_online\":"); w.boolean(d.system.edge_online);
    w.text(",\"sensor_degraded\":"); w.boolean(d.system.sensor_degraded); w.text("}}");
    if (!w.ok()) { out[0] = 0; return {SerializeStatus::BufferTooSmall, 0}; }
    return {SerializeStatus::Encoded, w.size()};
}
}
