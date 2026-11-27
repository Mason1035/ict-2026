#include "node/risk_framework.hpp"
#include <algorithm>
#include <array>
#include <cctype>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iostream>
#include <map>
#include <memory>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

struct JsonValue {
    enum class Type { Null, Bool, Number, String, Array, Object };
    Type type = Type::Null;
    bool boolean = false;
    double number = 0.0;
    std::int64_t integer = 0;
    bool is_integer = false;
    std::string str;
    std::vector<JsonValue> arr;
    std::map<std::string, JsonValue> obj;

    const JsonValue& at(const std::string& key) const {
        if (type != Type::Object) throw std::runtime_error("Expected JSON object accessing " + key);
        auto it = obj.find(key);
        if (it == obj.end()) throw std::runtime_error("Missing JSON key: " + key);
        return it->second;
    }
    bool contains(const std::string& key) const {
        return type == Type::Object && obj.find(key) != obj.end();
    }
};

class JsonParser {
public:
    explicit JsonParser(const std::string& input) : s_(input) {}

    JsonValue parse() {
        skip_ws();
        JsonValue v = parse_value();
        skip_ws();
        if (pos_ != s_.size()) throw std::runtime_error("Trailing characters in JSON");
        return v;
    }

private:
    const std::string& s_;
    std::size_t pos_ = 0;

    void skip_ws() {
        while (pos_ < s_.size() &&
               (s_[pos_] == ' ' || s_[pos_] == '\t' || s_[pos_] == '\r' || s_[pos_] == '\n')) {
            ++pos_;
        }
    }

    char peek() const {
        if (pos_ >= s_.size()) throw std::runtime_error("Unexpected EOF in JSON");
        return s_[pos_];
    }

    char get() {
        char c = peek();
        ++pos_;
        return c;
    }

    void expect(const char* lit) {
        while (*lit) {
            if (get() != *lit++) throw std::runtime_error("Unexpected literal in JSON");
        }
    }

    std::string parse_string() {
        if (get() != '"') throw std::runtime_error("Expected string");
        std::string out;
        while (pos_ < s_.size()) {
            char c = get();
            if (c == '"') return out;
            if (c == '\\') {
                char esc = get();
                switch (esc) {
                case '"': out.push_back('"'); break;
                case '\\': out.push_back('\\'); break;
                case '/': out.push_back('/'); break;
                case 'b': out.push_back('\b'); break;
                case 'f': out.push_back('\f'); break;
                case 'n': out.push_back('\n'); break;
                case 'r': out.push_back('\r'); break;
                case 't': out.push_back('\t'); break;
                case 'u': {
                    if (pos_ + 4 > s_.size()) throw std::runtime_error("Bad \\u escape");
                    unsigned code = 0;
                    for (int i = 0; i < 4; ++i) {
                        char h = get();
                        code <<= 4;
                        if (h >= '0' && h <= '9') code |= static_cast<unsigned>(h - '0');
                        else if (h >= 'a' && h <= 'f') code |= static_cast<unsigned>(h - 'a' + 10);
                        else if (h >= 'A' && h <= 'F') code |= static_cast<unsigned>(h - 'A' + 10);
                        else throw std::runtime_error("Invalid hex in \\u escape");
                    }
                    if (code <= 0x7F) {
                        out.push_back(static_cast<char>(code));
                    } else if (code <= 0x7FF) {
                        out.push_back(static_cast<char>(0xC0 | ((code >> 6) & 0x1F)));
                        out.push_back(static_cast<char>(0x80 | (code & 0x3F)));
                    } else {
                        out.push_back(static_cast<char>(0xE0 | ((code >> 12) & 0x0F)));
                        out.push_back(static_cast<char>(0x80 | ((code >> 6) & 0x3F)));
                        out.push_back(static_cast<char>(0x80 | (code & 0x3F)));
                    }
                    break;
                }
                default: throw std::runtime_error("Unknown escape sequence");
                }
            } else {
                out.push_back(c);
            }
        }
        throw std::runtime_error("Unterminated string");
    }

    JsonValue parse_number() {
        const std::size_t start = pos_;
        if (s_[pos_] == '-') ++pos_;
        bool is_float = false;
        while (pos_ < s_.size() && std::isdigit(static_cast<unsigned char>(s_[pos_]))) ++pos_;
        if (pos_ < s_.size() && s_[pos_] == '.') {
            is_float = true;
            ++pos_;
            while (pos_ < s_.size() && std::isdigit(static_cast<unsigned char>(s_[pos_]))) ++pos_;
        }
        if (pos_ < s_.size() && (s_[pos_] == 'e' || s_[pos_] == 'E')) {
            is_float = true;
            ++pos_;
            if (pos_ < s_.size() && (s_[pos_] == '+' || s_[pos_] == '-')) ++pos_;
            while (pos_ < s_.size() && std::isdigit(static_cast<unsigned char>(s_[pos_]))) ++pos_;
        }
        const std::string token = s_.substr(start, pos_ - start);
        if (token.empty() || token == "-") throw std::runtime_error("Invalid number");

        char* endptr = nullptr;
        const double d = std::strtod(token.c_str(), &endptr);
        if (endptr != token.c_str() + token.size() || !std::isfinite(d)) {
            throw std::runtime_error("Non-finite number in JSON: " + token);
        }
        JsonValue v;
        v.type = JsonValue::Type::Number;
        v.number = d;
        if (!is_float) {
            char* iend = nullptr;
            const long long iv = std::strtoll(token.c_str(), &iend, 10);
            if (iend == token.c_str() + token.size()) {
                v.is_integer = true;
                v.integer = static_cast<std::int64_t>(iv);
            }
        }
        return v;
    }

    JsonValue parse_value() {
        skip_ws();
        char c = peek();
        if (c == 'n') {
            expect("null");
            return JsonValue{};
        }
        if (c == 't') {
            expect("true");
            JsonValue v;
            v.type = JsonValue::Type::Bool;
            v.boolean = true;
            return v;
        }
        if (c == 'f') {
            expect("false");
            JsonValue v;
            v.type = JsonValue::Type::Bool;
            v.boolean = false;
            return v;
        }
        if (c == '"') {
            JsonValue v;
            v.type = JsonValue::Type::String;
            v.str = parse_string();
            return v;
        }
        if (c == '[') {
            get();
            JsonValue v;
            v.type = JsonValue::Type::Array;
            skip_ws();
            if (peek() == ']') {
                get();
                return v;
            }
            for (;;) {
                v.arr.push_back(parse_value());
                skip_ws();
                char next = get();
                if (next == ']') break;
                if (next != ',') throw std::runtime_error("Expected ',' or ']'");
            }
            return v;
        }
        if (c == '{') {
            get();
            JsonValue v;
            v.type = JsonValue::Type::Object;
            skip_ws();
            if (peek() == '}') {
                get();
                return v;
            }
            for (;;) {
                skip_ws();
                std::string key = parse_string();
                if (v.obj.find(key) != v.obj.end()) {
                    throw std::runtime_error("Duplicate JSON key: " + key);
                }
                skip_ws();
                if (get() != ':') throw std::runtime_error("Expected ':'");
                v.obj.emplace(std::move(key), parse_value());
                skip_ws();
                char next = get();
                if (next == '}') break;
                if (next != ',') throw std::runtime_error("Expected ',' or '}'");
            }
            return v;
        }
        if (c == '-' || std::isdigit(static_cast<unsigned char>(c))) {
            return parse_number();
        }
        throw std::runtime_error(std::string("Unexpected JSON token starting with '") + c + "'");
    }
};

std::string read_text(const std::string& path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) throw std::runtime_error("Failed to open input file: " + path);
    std::ostringstream ss;
    ss << in.rdbuf();
    return ss.str();
}

void write_text(const std::string& path, const std::string& content) {
    std::ofstream out(path, std::ios::binary | std::ios::trunc);
    if (!out) throw std::runtime_error("Failed to open output file: " + path);
    out << content;
    if (!out) throw std::runtime_error("Failed to write output file: " + path);
}

bool non_empty_str(const JsonValue& v) {
    return v.type == JsonValue::Type::String && !v.str.empty();
}

node::logic::math::Curve parse_curve(const JsonValue& arr) {
    if (arr.type != JsonValue::Type::Array ||
        arr.arr.size() > node::logic::math::Curve::max_points) {
        throw std::runtime_error("Invalid curve size");
    }
    node::logic::math::Curve c{};
    c.count = arr.arr.size();
    for (std::size_t i = 0; i < c.count; ++i) {
        const auto& pair = arr.arr[i];
        if (pair.type != JsonValue::Type::Array || pair.arr.size() != 2 ||
            pair.arr[0].type != JsonValue::Type::Number ||
            pair.arr[1].type != JsonValue::Type::Number) {
            throw std::runtime_error("Invalid curve point");
        }
        c.points[i] = {pair.arr[0].number, pair.arr[1].number};
    }
    return c;
}

node::logic::RiskConfig::WindowSpec parse_window(const JsonValue& obj) {
    node::logic::RiskConfig::WindowSpec w{};
    w.lookback_ms = static_cast<std::uint32_t>(obj.at("lookback_ms").integer);
    w.max_gap_ms = static_cast<std::uint32_t>(obj.at("max_gap_ms").integer);
    w.max_age_ms = static_cast<std::uint32_t>(obj.at("max_age_ms").integer);
    w.min_samples = static_cast<std::uint32_t>(obj.at("min_samples").integer);
    w.min_span_ms = static_cast<std::uint32_t>(obj.at("min_span_ms").integer);
    return w;
}

node::logic::RiskConfig parse_risk_config(const JsonValue& cfg) {
    using namespace node::logic;
    if (cfg.at("schema").str != "B.feature_risk.config.v1") {
        throw std::runtime_error("Unexpected config schema");
    }
    RiskConfig rc{};
    const auto& mode_s = cfg.at("mode").str;
    if (mode_s == "TEST_ONLY") rc.mode = ConfigMode::TestOnly;
    else if (mode_s == "CALIBRATED") rc.mode = ConfigMode::Calibrated;
    else rc.mode = ConfigMode::Draft;

    rc.validated_for_runtime = cfg.at("validated_for_runtime").boolean;
    rc.has_config_version = non_empty_str(cfg.at("config_version"));
    rc.has_feature_version = non_empty_str(cfg.at("feature_version"));
    rc.has_calibration_version = non_empty_str(cfg.at("calibration_version"));
    rc.has_frame_id = non_empty_str(cfg.at("frame_id"));
    rc.has_config_hash = non_empty_str(cfg.at("config_hash"));
    rc.has_device_identity = non_empty_str(cfg.at("device_identity").at("site_id")) &&
                             non_empty_str(cfg.at("device_identity").at("device_id"));

    const auto& sids = cfg.at("sensor_ids");
    rc.has_sensor_ids = non_empty_str(sids.at("imu").at("top")) &&
                        non_empty_str(sids.at("imu").at("toe")) &&
                        non_empty_str(sids.at("soil").at("top")) &&
                        non_empty_str(sids.at("soil").at("middle")) &&
                        non_empty_str(sids.at("soil").at("toe"));

    if (cfg.contains("review_refs") && cfg.at("review_refs").type == JsonValue::Type::Object) {
        const auto& rr = cfg.at("review_refs");
        rc.review_a = rr.contains("A") && non_empty_str(rr.at("A"));
        rc.review_b = rr.contains("B") && non_empty_str(rr.at("B"));
        rc.review_c = rr.contains("C") && non_empty_str(rr.at("C"));
    }
    rc.has_reason_mask_version = cfg.contains("reason_mask_version") &&
                                 cfg.at("reason_mask_version").type == JsonValue::Type::String;
    rc.has_reason_bits = cfg.contains("reason_bits") &&
                         cfg.at("reason_bits").type == JsonValue::Type::Object;
    if (rc.has_reason_bits) {
        const auto& rb = cfg.at("reason_bits");
        rc.reason_bits[0] = static_cast<std::uint8_t>(rb.at("TILT_CONTRIBUTION").integer);
        rc.reason_bits[1] = static_cast<std::uint8_t>(rb.at("VIBRATION_CONTRIBUTION").integer);
        rc.reason_bits[2] = static_cast<std::uint8_t>(rb.at("MOISTURE_CONTRIBUTION").integer);
        rc.reason_bits[3] = static_cast<std::uint8_t>(rb.at("GROWTH_CONTRIBUTION").integer);
        rc.reason_bits[4] = static_cast<std::uint8_t>(rb.at("DUAL_IMU_CONSENSUS").integer);
    }

    const auto& w = cfg.at("weights");
    rc.weights = {
        w.at("tilt").number,
        w.at("vibration").number,
        w.at("moisture").number,
        w.at("growth").number
    };
    rc.imu_odr_hz = cfg.at("odr_hz").at("imu").number;
    rc.soil_odr_hz = cfg.at("odr_hz").at("soil").number;
    if (cfg.at("missing_policy").str == "REQUIRE_BOTH_IMU_AND_ALL_THREE_SOIL_V1") {
        rc.missing_policy = MissingPolicy::RequireBothImuAndAllThreeSoilV1;
    }

    const auto& imu = cfg.at("imu");
    if (imu.at("filter").str != "CAUSAL_GRAVITY_LOWPASS_V1") {
        throw std::runtime_error("Unsupported IMU filter");
    }
    rc.imu.gravity_tau_ms = imu.at("gravity_tau_ms").number;
    rc.imu.warmup_ms = static_cast<std::uint32_t>(imu.at("warmup_ms").integer);
    rc.imu.alignment_ms = static_cast<std::uint32_t>(imu.at("alignment_ms").integer);
    const char* imu_names[2] = {"top", "toe"};
    for (unsigned s = 0; s < 2; ++s) {
        const auto& vec = imu.at("baseline_gravity_mps2").at(imu_names[s]).arr;
        if (vec.size() != 3) throw std::runtime_error("Bad baseline vector");
        rc.imu.baseline_gravity_mps2[s] = {vec[0].number, vec[1].number, vec[2].number};
    }

    const auto& soil = cfg.at("soil");
    rc.soil.alignment_ms = static_cast<std::uint32_t>(soil.at("alignment_ms").integer);
    const char* soil_names[3] = {"top", "middle", "toe"};
    for (unsigned p = 0; p < 3; ++p) {
        const auto& cal = soil.at("calibration").at(soil_names[p]);
        rc.soil.calibration[p] = {
            cal.at("dry_raw").number,
            cal.at("wet_raw").number,
            cal.at("min_span_raw").number
        };
    }

    const auto& win = cfg.at("windows");
    rc.windows.tilt = parse_window(win.at("tilt"));
    rc.windows.vibration = parse_window(win.at("vibration"));
    rc.windows.soil_growth = parse_window(win.at("soil_growth"));

    const auto& crv = cfg.at("curves");
    rc.curves.tilt = parse_curve(crv.at("tilt"));
    rc.curves.vibration = parse_curve(crv.at("vibration"));
    rc.curves.moisture = parse_curve(crv.at("moisture"));
    rc.curves.growth = parse_curve(crv.at("growth"));

    const auto& con = cfg.at("consensus");
    rc.consensus.tilt_threshold_deg = con.at("tilt_threshold_deg").number;
    rc.consensus.max_tilt_difference_deg = con.at("max_tilt_difference_deg").number;
    rc.consensus.bonus = con.at("bonus").number;
    return rc;
}

const char* level_str(node::protocol::RiskLevel lv) {
    switch (lv) {
    case node::protocol::RiskLevel::Normal: return "NORMAL";
    case node::protocol::RiskLevel::Watch: return "WATCH";
    case node::protocol::RiskLevel::Warning: return "WARNING";
    case node::protocol::RiskLevel::Emergency: return "EMERGENCY";
    }
    return "";
}

std::string fmt_opt_double(std::optional<double> v) {
    if (!v || !std::isfinite(*v)) return "null";
    double val = *v;
    if (val == 0.0) val = 0.0; // avoid -0.0
    char buf[64];
    std::snprintf(buf, sizeof(buf), "%.17g", val);
    std::string out(buf);
    if (out.find('.') == std::string::npos &&
        out.find('e') == std::string::npos &&
        out.find('E') == std::string::npos) {
        out += ".0";
    }
    return out;
}

std::string fmt_opt_level(std::optional<node::protocol::RiskLevel> lv) {
    if (!lv) return "null";
    return std::string("\"") + level_str(*lv) + "\"";
}

std::string fmt_opt_u32(std::optional<std::uint32_t> v) {
    if (!v) return "null";
    return std::to_string(*v);
}

std::string json_escape(const std::string& s) {
    std::string out = "\"";
    for (char c : s) {
        if (c == '"' || c == '\\') { out.push_back('\\'); out.push_back(c); }
        else out.push_back(c);
    }
    out.push_back('"');
    return out;
}

struct SoilEvent {
    std::int64_t uptime_ms = 0;
    unsigned probe = 0;
    bool valid = false;
    std::int16_t raw = 0;
};

} // namespace

int main(int argc, char** argv) {
    try {
        std::string inputs_path, boundaries_path, out_actual_path, out_boundaries_path;
        for (int i = 1; i + 1 < argc; i += 2) {
            const std::string flag = argv[i];
            const std::string val = argv[i + 1];
            if (flag == "--inputs") inputs_path = val;
            else if (flag == "--boundaries") boundaries_path = val;
            else if (flag == "--out-actual") out_actual_path = val;
            else if (flag == "--out-boundaries") out_boundaries_path = val;
            else throw std::runtime_error("Unknown argument: " + flag);
        }
        if (inputs_path.empty() || boundaries_path.empty() ||
            out_actual_path.empty() || out_boundaries_path.empty()) {
            throw std::runtime_error(
                "Usage: bench_compare_runner --inputs <in> --boundaries <bnd> --out-actual <act> --out-boundaries <outbnd>");
        }

        const JsonValue inputs = JsonParser(read_text(inputs_path)).parse();
        const std::string expected_status = "TEST_ONLY_NOT_CALIBRATION_OR_BOARD_ACCEPTANCE";
        if (inputs.at("status").str != expected_status) {
            throw std::runtime_error("inputs.json status mismatch");
        }
        const auto risk_cfg = parse_risk_config(inputs.at("config"));
        if (node::logic::validate_risk_config(risk_cfg) != node::logic::ValidationError::Ok) {
            throw std::runtime_error("RiskConfig validation failed in C++ engine");
        }

        const auto& cases = inputs.at("cases").arr;
        auto pipeline = std::make_unique<node::logic::FeaturePipeline>();

        std::ostringstream out;
        out << "{\n  \"status\": \"" << expected_status << "\",\n  \"cases\": [\n";
        for (std::size_t ci = 0; ci < cases.size(); ++ci) {
            const auto& c = cases[ci];
            const std::string case_id = c.at("case_id").str;
            const auto& payload = c.at("payload");
            const auto& batch = c.at("context").at("runtime_input");
            if (payload.at("schema").str != "zhifang.telemetry.v2" ||
                batch.at("schema").str != "B.observation_batch.v1") {
                throw std::runtime_error("Unexpected payload or batch schema");
            }
            if (pipeline->reset(risk_cfg) != node::logic::ValidationError::Ok) {
                throw std::runtime_error("Failed to reset FeaturePipeline");
            }

            const char* imu_names[2] = {"top", "toe"};
            for (unsigned site = 0; site < 2; ++site) {
                const auto& rows = batch.at("imu").at(imu_names[site]).arr;
                for (const auto& row : rows) {
                    const std::int64_t t = row.at("uptime_ms").integer;
                    const bool valid = row.at("valid").boolean;
                    std::array<double, 3> accel{};
                    if (valid) {
                        const auto& a = row.at("acceleration_mps2").arr;
                        if (a.size() != 3) throw std::runtime_error("Invalid accel size");
                        accel = {a[0].number, a[1].number, a[2].number};
                    }
                    if (!pipeline->ingest_imu(site, t, valid, accel)) {
                        throw std::runtime_error("ingest_imu failed for case " + case_id);
                    }
                }
            }

            std::vector<SoilEvent> soil_events;
            const char* soil_names[3] = {"top", "middle", "toe"};
            for (unsigned p = 0; p < 3; ++p) {
                const auto& rows = batch.at("soil").at(soil_names[p]).arr;
                for (const auto& row : rows) {
                    SoilEvent ev;
                    ev.uptime_ms = row.at("uptime_ms").integer;
                    ev.probe = p;
                    ev.valid = row.at("valid").boolean;
                    if (ev.valid) {
                        const auto raw_i = row.at("raw").integer;
                        if (raw_i < -32768 || raw_i > 32767) {
                            throw std::runtime_error("Soil raw out of int16 range");
                        }
                        ev.raw = static_cast<std::int16_t>(raw_i);
                    }
                    soil_events.push_back(ev);
                }
            }
            std::sort(soil_events.begin(), soil_events.end(),
                      [](const SoilEvent& a, const SoilEvent& b) {
                          return a.uptime_ms != b.uptime_ms ? a.uptime_ms < b.uptime_ms
                                                            : a.probe < b.probe;
                      });

            for (std::size_t idx = 0; idx < soil_events.size();) {
                const std::int64_t group_t = soil_events[idx].uptime_ms;
                std::array<std::optional<node::logic::SoilRawObs>, 3> updates{};
                while (idx < soil_events.size() && soil_events[idx].uptime_ms == group_t) {
                    const auto& ev = soil_events[idx];
                    updates[ev.probe] = node::logic::SoilRawObs{ev.uptime_ms, ev.valid, ev.raw};
                    ++idx;
                }
                if (!pipeline->ingest_soil_group(group_t, updates)) {
                    throw std::runtime_error("ingest_soil_group failed for case " + case_id);
                }
            }

            const std::int64_t end_uptime_ms = payload.at("uptime_ms").integer;
            const auto proj = pipeline->evaluate_at(end_uptime_ms);

            out << "    {\n"
                << "      \"case_id\": " << json_escape(case_id) << ",\n"
                << "      \"risk\": {\n"
                << "        \"sensor_score\": " << fmt_opt_double(proj.risk.score) << ",\n"
                << "        \"level\": " << fmt_opt_level(proj.risk.level) << ",\n"
                << "        \"reason_mask\": " << fmt_opt_u32(proj.risk.reason_mask) << "\n"
                << "      },\n"
                << "      \"features\": {\n"
                << "        \"imu\": {\n"
                << "          \"top\": {\n"
                << "            \"tilt_deg\": " << fmt_opt_double(proj.imu[0].tilt_deg) << ",\n"
                << "            \"tilt_rate_dps\": " << fmt_opt_double(proj.imu[0].tilt_rate_dps) << ",\n"
                << "            \"vibration_rms\": " << fmt_opt_double(proj.imu[0].vibration_rms) << "\n"
                << "          },\n"
                << "          \"toe\": {\n"
                << "            \"tilt_deg\": " << fmt_opt_double(proj.imu[1].tilt_deg) << ",\n"
                << "            \"tilt_rate_dps\": " << fmt_opt_double(proj.imu[1].tilt_rate_dps) << ",\n"
                << "            \"vibration_rms\": " << fmt_opt_double(proj.imu[1].vibration_rms) << "\n"
                << "          }\n"
                << "        },\n"
                << "        \"soil\": {\n"
                << "          \"top_pct\": " << fmt_opt_double(proj.soil.top_pct) << ",\n"
                << "          \"middle_pct\": " << fmt_opt_double(proj.soil.middle_pct) << ",\n"
                << "          \"toe_pct\": " << fmt_opt_double(proj.soil.toe_pct) << ",\n"
                << "          \"avg_pct\": " << fmt_opt_double(proj.soil.avg_pct) << ",\n"
                << "          \"growth_pct_min\": " << fmt_opt_double(proj.soil.growth_pct_min) << "\n"
                << "        },\n"
                << "        \"dual_imu_tilt_difference_deg\": " << fmt_opt_double(proj.dual_imu_tilt_difference_deg) << "\n"
                << "      }\n"
                << "    }" << (ci + 1 < cases.size() ? "," : "") << "\n";
        }
        out << "  ]\n}\n";
        write_text(out_actual_path, out.str());

        const JsonValue boundaries = JsonParser(read_text(boundaries_path)).parse();
        if (boundaries.at("status").str != expected_status) {
            throw std::runtime_error("binary64_boundaries.json status mismatch");
        }
        const auto& bvecs = boundaries.at("vectors").arr;
        std::ostringstream bout;
        bout << "{\n  \"status\": \"" << expected_status << "\",\n  \"vectors\": [\n";
        unsigned passed_boundaries = 0;
        for (std::size_t bi = 0; bi < bvecs.size(); ++bi) {
            const auto& v = bvecs[bi];
            const std::string hex_s = v.at("score_hex").str;
            char* hex_end = nullptr;
            const double exact_score = std::strtod(hex_s.c_str(), &hex_end);
            if (hex_end != hex_s.c_str() + hex_s.size()) {
                throw std::runtime_error("Invalid score_hex: " + hex_s);
            }
            const auto actual_level = node::logic::math::classify_double(exact_score);
            const auto& exp_v = v.at("expected_level");
            std::optional<node::protocol::RiskLevel> expected_lv{};
            if (exp_v.type == JsonValue::Type::String) {
                if (exp_v.str == "NORMAL") expected_lv = node::protocol::RiskLevel::Normal;
                else if (exp_v.str == "WATCH") expected_lv = node::protocol::RiskLevel::Watch;
                else if (exp_v.str == "WARNING") expected_lv = node::protocol::RiskLevel::Warning;
                else if (exp_v.str == "EMERGENCY") expected_lv = node::protocol::RiskLevel::Emergency;
                else throw std::runtime_error("Unknown expected_level: " + exp_v.str);
            }
            if (actual_level != expected_lv) {
                throw std::runtime_error("Boundary classification mismatch at index " + std::to_string(bi));
            }
            ++passed_boundaries;
            bout << "    {\n"
                 << "      \"score_hex\": " << json_escape(hex_s) << ",\n"
                 << "      \"actual_level\": " << fmt_opt_level(actual_level) << "\n"
                 << "    }" << (bi + 1 < bvecs.size() ? "," : "") << "\n";
        }
        bout << "  ]\n}\n";
        write_text(out_boundaries_path, bout.str());

        std::cout << "BENCH_COMPARE_RUNNER_OK cases=" << cases.size()
                  << " boundaries_matched=" << passed_boundaries << "/" << bvecs.size() << "\n";
        return 0;
    } catch (const std::exception& ex) {
        std::cerr << "BENCH_COMPARE_RUNNER_ERROR: " << ex.what() << "\n";
        return 1;
    }
}
