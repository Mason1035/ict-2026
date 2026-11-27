#include "node/mqtt_only.hpp"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_timer.h"
#include <cinttypes>
#include <cmath>
#include <cstdio>
#include <cstring>

namespace node::comm {
namespace {
constexpr const char* tag = "node_comm";
constexpr std::uint64_t connect_budget = 15'000'000;
constexpr std::uint64_t stop_budget = 10'000'000;
constexpr std::uint64_t window_budget = 180'000'000;
#ifdef CONFIG_NODE01_REAL_TEST_ONLY
constexpr char profile_namespace[] = "node01_realtest";
constexpr char site[] = "NODE01-STAGE23-TEST";
constexpr char device[] = "NODE-01-REAL-TEST";
constexpr char topic[] = "zhifang/v2/NODE01-STAGE23-TEST/NODE-01-REAL-TEST/telemetry";
constexpr std::uint64_t publish_interval = 1'000'000;
constexpr std::uint64_t publish_budget = 7'000'000;

bool fresh(const std::optional<std::uint64_t>& time, std::uint64_t beginning,
           std::uint64_t now, std::uint64_t max_age) {
    return time && *time >= beginning && *time <= now && now - *time <= max_age;
}

bool fresh(const sampling::SensorSnapshot& sample, std::uint64_t beginning, std::uint64_t now) {
    for (const auto& imu : sample.imu)
        if (imu.validity != sampling::Validity::Valid ||
            !fresh(imu.acquired_uptime_us, beginning, now, 30'000)) return false;
    for (const auto& soil : sample.soil)
        if (soil.validity != sampling::Validity::Valid || !soil.raw ||
            !fresh(soil.acquired_uptime_us, beginning, now, 1'500'000)) return false;
    return true;
}

// The TEST_ONLY profile emits the full v2 envelope and only admits fresh raw
// observations. Fixed fields avoid linking the general-purpose JSON writer.
int encode_real_test(const sampling::SensorSnapshot& sample, std::uint64_t boot,
                     std::uint64_t seq, std::uint64_t uptime_ms, char* out, std::size_t capacity) {
    if (!boot || !seq || boot > protocol::json_safe_integer_max ||
        seq > protocol::json_safe_integer_max || uptime_ms > protocol::json_safe_integer_max) return 0;
    for (const auto& imu : sample.imu) {
        for (float value : imu.acceleration_mps2) if (!std::isfinite(value)) return 0;
        for (float value : imu.angular_rate_dps) if (!std::isfinite(value)) return 0;
    }
    const auto& top = sample.imu[0];
    const auto& toe = sample.imu[1];
    const int length = std::snprintf(out, capacity,
        R"({"schema":"%s","site_id":"%s","device_id":"%s","boot_id":%)" PRIu64
        R"(,"seq":%)" PRIu64 R"(,"timestamp_ms":null,"uptime_ms":%)" PRIu64
        R"(,"time_synced":false,"imu":[)"
        R"({"id":"top","ax":%.9g,"ay":%.9g,"az":%.9g,"gx":%.9g,"gy":%.9g,"gz":%.9g,)"
        R"("tilt_deg":null,"tilt_rate_dps":null,"vibration_rms":null,"valid":true},)"
        R"({"id":"toe","ax":%.9g,"ay":%.9g,"az":%.9g,"gx":%.9g,"gy":%.9g,"gz":%.9g,)"
        R"("tilt_deg":null,"tilt_rate_dps":null,"vibration_rms":null,"valid":true}],)"
        R"("soil":{"top_raw":%d,"middle_raw":%d,"toe_raw":%d,"top_pct":null,"middle_pct":null,)"
        R"("toe_pct":null,"avg_pct":null,"growth_pct_min":null},)"
        R"("experiment":{"run_id":null,"rain_level":null},)"
        R"("risk":{"sensor_score":null,"level":null,"reason_mask":null},)"
        R"("system":{"wifi_up":true,"mqtt_up":true,"lora_ready":false,"sd_ok":true,)"
        R"("edge_online":false,"sensor_degraded":false}})",
        protocol::schema, site, device, boot, seq, uptime_ms,
        top.acceleration_mps2[0], top.acceleration_mps2[1], top.acceleration_mps2[2],
        top.angular_rate_dps[0], top.angular_rate_dps[1], top.angular_rate_dps[2],
        toe.acceleration_mps2[0], toe.acceleration_mps2[1], toe.acceleration_mps2[2],
        toe.angular_rate_dps[0], toe.angular_rate_dps[1], toe.angular_rate_dps[2],
        static_cast<int>(*sample.soil[0].raw), static_cast<int>(*sample.soil[1].raw),
        static_cast<int>(*sample.soil[2].raw));
    return length > 0 && static_cast<std::size_t>(length) < capacity ? length : 0;
}
#endif

#ifndef CONFIG_MQTT_TRANSPORT_SSL
bool private_ipv4(const char* host) {
    unsigned octets[4]{};
    const char* cursor = host;
    for (unsigned index = 0; index < 4; ++index) {
        const char* first = cursor;
        unsigned value = 0;
        while (*cursor >= '0' && *cursor <= '9') {
            if (cursor - first >= 3) return false;
            value = value * 10 + unsigned(*cursor++ - '0');
        }
        if (cursor == first || value > 255 || (cursor - first > 1 && *first == '0')) return false;
        octets[index] = value;
        if (index < 3 && *cursor++ != '.') return false;
    }
    return *cursor == '\0' && (octets[0] == 10 ||
        (octets[0] == 172 && octets[1] >= 16 && octets[1] <= 31) ||
        (octets[0] == 192 && octets[1] == 168));
}
#else
bool valid_hostname(const char* host) {
    for (const char* character = host; *character; ++character) {
        const char c = *character;
        if (!(('a' <= c && c <= 'z') || ('A' <= c && c <= 'Z') ||
              ('0' <= c && c <= '9') || c == '.' || c == '-')) return false;
    }
    return host[0] && host[0] != '.' && host[0] != '-';
}
#endif
}

esp_err_t MqttOnly::configure(nvs_handle_t settings) {
    esp_err_t result = ESP_OK;
    auto get = [&](const char* key, char* value, std::size_t capacity) {
        if (result == ESP_OK) result = nvs_get_str(settings, key, value, &capacity);
    };
    get("host", host_, sizeof(host_));
    get("user", user_, sizeof(user_));
    get("pass", password_, sizeof(password_));
    if (result == ESP_OK) result = nvs_get_u16(settings, "port", &port_);
    std::uint8_t transport = 0;
    if (result == ESP_OK) result = nvs_get_u8(settings, "transport", &transport);
#ifdef CONFIG_MQTT_TRANSPORT_SSL
    get("ca_pem", ca_pem_, sizeof(ca_pem_));
#endif
    if (result != ESP_OK) return result;
    if (!port_ || !user_[0] || !password_[0]) return ESP_ERR_INVALID_ARG;
#ifdef CONFIG_MQTT_TRANSPORT_SSL
    if (transport != 1 || !valid_hostname(host_) ||
        std::strncmp(ca_pem_, "-----BEGIN CERTIFICATE-----", 27) != 0 ||
        !std::strstr(ca_pem_, "-----END CERTIFICATE-----")) return ESP_ERR_INVALID_ARG;
#else
    if (transport != 0 || !private_ipv4(host_)) return ESP_ERR_INVALID_ARG;
#endif
    std::uint8_t mac[6]{};
    result = esp_read_mac(mac, ESP_MAC_WIFI_STA);
    if (result != ESP_OK) return result;
#ifdef CONFIG_NODE01_REAL_TEST_ONLY
    std::uint64_t approved_mac = 0, actual_mac = 0;
    for (const auto octet : mac) actual_mac = (actual_mac << 8) | octet;
    if (std::strcmp(host_, "192.168.31.225") == 0 ||
        nvs_get_u64(settings, "board_mac", &approved_mac) != ESP_OK || approved_mac != actual_mac)
        return ESP_ERR_INVALID_STATE;
    constexpr char client_format[] = "n01-rt-%02x%02x%02x%02x%02x%02x";
#else
    constexpr char client_format[] = "n01-md-%02x%02x%02x%02x%02x%02x";
#endif
    std::snprintf(client_id_, sizeof(client_id_), client_format,
                  unsigned(mac[0]), unsigned(mac[1]), unsigned(mac[2]), unsigned(mac[3]),
                  unsigned(mac[4]), unsigned(mac[5]));
    configured_ = true;
    return ESP_OK;
}

esp_err_t MqttOnly::start_window(std::uint64_t now) {
    if (!configured_ || worker_) return ESP_ERR_INVALID_STATE;
    window_end_ = now + window_budget;
    if (xTaskCreate(run, "MqttDiagSdk", 4096, this, 3, &worker_) != pdPASS) return ESP_ERR_NO_MEM;
#ifdef CONFIG_NODE01_REAL_TEST_ONLY
    ESP_LOGI(tag, "REAL_TEST_ONLY_CONNECT_ONLY window_s=180");
#else
    ESP_LOGI(tag, "MQTT_ONLY_ARMED window_s=180; CONNECT only");
#endif
    return ESP_OK;
}

bool MqttOnly::up() const {
    const auto wifi = wifi_epoch_.load();
    return (wifi & 1U) && wifi == attempt_epoch_.load() && signal_.load() == Signal::Online &&
           static_cast<std::uint64_t>(esp_timer_get_time()) < window_end_;
}

void MqttOnly::event(void* arg, esp_event_base_t, std::int32_t id, void* data) {
    auto& self = *static_cast<MqttOnly*>(arg);
    const auto* event = static_cast<esp_mqtt_event_t*>(data);
    if (!event || !event->client || event->client != self.callback_client_.load()) return;
    if (id != MQTT_EVENT_BEFORE_CONNECT && id != MQTT_EVENT_CONNECTED &&
        id != MQTT_EVENT_ERROR && id != MQTT_EVENT_DISCONNECTED) return;
    self.sdk_entered_ = true;
    if (id == MQTT_EVENT_CONNECTED) {
        const auto now = static_cast<std::uint64_t>(esp_timer_get_time());
        if (self.wifi_epoch_.load() != self.attempt_epoch_.load() ||
            now >= self.connect_end_ || now >= self.window_end_) return;
        auto expected = Signal::Connecting;
        self.signal_.compare_exchange_strong(expected, Signal::Online);
    } else if (id == MQTT_EVENT_ERROR || id == MQTT_EVENT_DISCONNECTED) {
        auto old = self.signal_.load();
        while ((old == Signal::Connecting || old == Signal::Online) &&
               !self.signal_.compare_exchange_weak(old, Signal::Failed)) {}
    }
}

void MqttOnly::post(Work job) {
    work_ = job;
    xTaskNotifyGive(worker_);
}

void MqttOnly::run(void* arg) {
    auto& self = *static_cast<MqttOnly*>(arg);
    for (;;) {
        ulTaskNotifyTake(pdTRUE, portMAX_DELAY); // Idle worker. Supervisor never joins it.
        const auto job = self.work_.load();
        if (job == Work::Start) self.start_client();
        if (job == Work::Stop) self.stop_client();
#ifdef CONFIG_NODE01_REAL_TEST_ONLY
        if (job == Work::Publish) self.publish_sample();
#endif
    }
}

void MqttOnly::start_client() {
    const auto admitted = [&] {
        const auto now = static_cast<std::uint64_t>(esp_timer_get_time());
        return signal_ == Signal::Connecting && wifi_epoch_.load() == attempt_epoch_ &&
               now < connect_end_ && now < window_end_;
    };
    if (!admitted()) {
        work_ = Work::StartDeclined;
        return;
    }
    esp_mqtt_client_config_t cfg{};
    cfg.broker.address.hostname = host_;
    cfg.broker.address.port = port_;
#ifdef CONFIG_MQTT_TRANSPORT_SSL
    cfg.broker.address.transport = MQTT_TRANSPORT_OVER_SSL;
    cfg.broker.verification.certificate = ca_pem_;
#else
    cfg.broker.address.transport = MQTT_TRANSPORT_OVER_TCP;
#endif
    cfg.credentials.client_id = client_id_;
    cfg.credentials.username = user_;
    cfg.credentials.authentication.password = password_;
    cfg.session.protocol_ver = MQTT_PROTOCOL_V_3_1_1;
    cfg.session.disable_clean_session = false;
    cfg.session.keepalive = 15;
    cfg.network.disable_auto_reconnect = true;
    cfg.network.timeout_ms = 5000;
    cfg.buffer.size = 512;
#ifdef CONFIG_NODE01_REAL_TEST_ONLY
    cfg.buffer.out_size = sizeof(payload_) + sizeof(topic) + 8;
#else
    cfg.buffer.out_size = 512;
#endif
    cfg.outbox.limit = 512;
    cfg.task.stack_size = 6144;
    client_ = esp_mqtt_client_init(&cfg);
    if (!client_) {
        work_ = Work::StartDeclined;
        return;
    }
    callback_client_ = client_;
    auto error = esp_mqtt_client_register_event(client_, MQTT_EVENT_ANY, event, this);
    if (error == ESP_OK && admitted()) error = esp_mqtt_client_start(client_);
    else if (error == ESP_OK) error = ESP_ERR_INVALID_STATE;
    if (error == ESP_OK) {
        work_ = Work::Started;
        return;
    }
    // No task was created if start was not called or returned an error.
    callback_client_ = nullptr;
    if (esp_mqtt_client_destroy(client_) == ESP_OK) {
        client_ = nullptr;
        work_ = Work::StartDeclined;
    } else {
        work_ = Work::Blocked;
    }
}

#ifdef CONFIG_NODE01_REAL_TEST_ONLY
esp_err_t MqttOnly::authorize_publish(unsigned limit) {
    if (!limit || limit > 3) return ESP_ERR_INVALID_ARG;
    if (authorization_used_ || !up() || work_ != Work::Started) return ESP_ERR_INVALID_STATE;
    authorization_used_ = true; // No retry on a possibly committed reservation.
    nvs_handle_t settings = 0;
    auto result = nvs_open(profile_namespace, NVS_READWRITE, &settings);
    if (result != ESP_OK) return result;
    std::uint8_t isolated = 0;
    std::uint64_t reserved = 0, last_used = 0;
    result = nvs_get_u8(settings, "isolated_rx", &isolated);
    if (result == ESP_OK && isolated != 1) result = ESP_ERR_INVALID_STATE;
    if (result == ESP_OK) result = nvs_get_u64(settings, "reserved", &reserved);
    if (result == ESP_OK) result = nvs_get_u64(settings, "last_used", &last_used);
    if (result == ESP_OK && (reserved <= last_used || reserved > protocol::json_safe_integer_max))
        result = ESP_ERR_INVALID_STATE;
    if (result == ESP_OK) result = nvs_set_u64(settings, "last_used", reserved);
    if (result == ESP_OK) result = nvs_commit(settings);
    nvs_close(settings);
    if (result != ESP_OK) return result;

    result = nvs_open(profile_namespace, NVS_READONLY, &settings);
    if (result != ESP_OK) return result;
    std::uint64_t committed = 0;
    result = nvs_get_u64(settings, "last_used", &committed);
    nvs_close(settings);
    if (result != ESP_OK) return result;
    if (committed != reserved || !up()) return ESP_ERR_INVALID_STATE;
    boot_id_ = reserved;
    publish_limit_ = limit;
    return ESP_OK;
}

void MqttOnly::poll_telemetry(const sampling::SensorSnapshot& sample, CaptureStatus capture,
                             std::uint64_t now) {
    // Only read the worker's sequence after acquiring its completion state.
    if (!publish_limit_ || !capture || now >= capture().end_us || now < next_attempt_ ||
        !up() || work_ != Work::Started || seq_ >= publish_limit_) return;
    capture_status_ = capture;
    pending_sample_ = sample;
    job_end_ = now + publish_budget;
    next_attempt_ = now + publish_interval;
    post(Work::Publish);
}

void MqttOnly::publish_sample() {
    const auto now = static_cast<std::uint64_t>(esp_timer_get_time());
    const auto capture = capture_status_();
    if (up() && now < capture.end_us && now < job_end_ && now >= next_send_ &&
        fresh(pending_sample_, capture.started_us, now)) {
        const auto bytes = encode_real_test(pending_sample_, boot_id_, seq_ + 1,
                                            now / 1000, payload_, sizeof(payload_));
        const auto send_at = static_cast<std::uint64_t>(esp_timer_get_time());
        const auto current = capture_status_();
        if (bytes && up() && current.started_us == capture.started_us && send_at < current.end_us &&
            send_at < job_end_ && fresh(pending_sample_, current.started_us, send_at)) {
            next_send_ = send_at + publish_interval;
            ++seq_; // A call with an uncertain outcome is never replayed.
            if (esp_mqtt_client_publish(client_, topic, payload_, bytes, 0, 0) == 0) ++submitted_;
            else ++rejected_;
            work_ = Work::Started;
            return;
        }
    }
    ++rejected_;
    work_ = Work::Started;
}
#endif

void MqttOnly::stop_client() {
    auto error = esp_mqtt_client_stop(client_);
    if (error == ESP_OK) {
        callback_client_ = nullptr;
        error = esp_mqtt_client_destroy(client_);
    }
    if (error == ESP_OK) {
        client_ = nullptr;
        work_ = Work::Released;
    } else {
        work_ = Work::Blocked;
    }
}

void MqttOnly::retire(std::uint64_t now, const char* reason) {
    signal_ = Signal::Inactive;
#ifdef CONFIG_NODE01_REAL_TEST_ONLY
    publish_limit_ = 0;
#endif
    retiring_ = true;
    retire_end_ = now + stop_budget;
    retry_.failed(now);
    observed_online_ = false;
    ESP_LOGW(tag, "MQTT_ONLY_RETIRE reason=%s", reason);
}

void MqttOnly::poll_retirement(std::uint64_t now, Work stage) {
    if (stage == Work::Started && sdk_entered_) post(Work::Stop);
    if (!quarantine_reported_ && (stage == Work::Blocked || now >= retire_end_)) {
        quarantine_reported_ = true;
        ESP_LOGE(tag, "MQTT_ONLY_QUARANTINED; SDK cleanup unconfirmed, no replacement");
    }
}

void MqttOnly::poll(std::uint64_t now) {
    if (!worker_) return;
    if (!closed_ && now >= window_end_) {
        closed_ = true;
        ESP_LOGI(tag, "MQTT_ONLY_WINDOW_CLOSED");
    }
    const auto wifi = wifi_epoch_.load();
    if (!active_) {
        if (closed_ || !(wifi & 1U) || !retry_.due(now)) return;
        active_ = true;
        sdk_entered_ = false;
        attempt_epoch_ = wifi;
        connect_end_ = now + connect_budget;
        quarantine_reported_ = false;
        signal_ = Signal::Connecting;
        post(Work::Start);
        return;
    }

    const auto stage = work_.load();
    if (stage == Work::Released || stage == Work::StartDeclined) {
        if (!retiring_) retry_.failed(now);
        signal_ = Signal::Inactive;
        work_ = Work::Idle;
        active_ = retiring_ = false;
        ESP_LOGI(tag, "MQTT_ONLY_CLIENT_RELEASED");
        return;
    }
    const auto signal = signal_.load();
    if (!retiring_) {
        if (closed_) retire(now, "WINDOW_END");
        else if (wifi != attempt_epoch_) retire(now, "WIFI_EPOCH_CHANGED");
        else if (signal == Signal::Failed || stage == Work::Blocked) retire(now, "SDK_ERROR");
        else if (signal == Signal::Connecting && now >= connect_end_) retire(now, "CONNECT_DEADLINE");
#ifdef CONFIG_NODE01_REAL_TEST_ONLY
        else if (stage == Work::Publish && now >= job_end_) retire(now, "PUBLISH_DEADLINE");
#endif
        else if (signal == Signal::Online && !observed_online_) {
            observed_online_ = true;
            retry_.connected();
            ESP_LOGI(tag, "MQTT_ONLY_CONNACK_ACCEPTED");
        }
    }
    if (retiring_) poll_retirement(now, stage);
}
}
