#include "node/network.hpp"
#include "node/board.hpp"
#include "esp_wifi.h"
#include "esp_timer.h"
#include "esp_log.h"
#include "nvs.h"
#include "nvs_flash.h"
#include "esp_crt_bundle.h"
#include <cstdio>
#include <cstring>

namespace node::comm {
namespace {
constexpr const char* tag = "node_comm";
class NvsBootCounter final : public BootCounterStore {
public:
    explicit NvsBootCounter(nvs_handle_t h) : handle_(h) {}
    bool load(protocol::Integer& out) override { return nvs_get_u64(handle_, "last_boot", &out) == ESP_OK; }
    bool commit(protocol::Integer value) override {
        return nvs_set_u64(handle_, "last_boot", value) == ESP_OK && nvs_commit(handle_) == ESP_OK;
    }
private: nvs_handle_t handle_;
};
}
void Network::cleanup() {
    ready_ = false;
    links_.wifi_disconnected();
    if (mqtt_) { if (mqtt_started_) esp_mqtt_client_stop(mqtt_); esp_mqtt_client_destroy(mqtt_); mqtt_ = nullptr; }
    if (wifi_handler_) { esp_event_handler_instance_unregister(WIFI_EVENT, ESP_EVENT_ANY_ID, wifi_handler_); wifi_handler_ = nullptr; }
    if (ip_handler_) { esp_event_handler_instance_unregister(IP_EVENT, IP_EVENT_STA_GOT_IP, ip_handler_); ip_handler_ = nullptr; }
    if (wifi_initialized_) { esp_wifi_stop(); esp_wifi_deinit(); wifi_initialized_ = false; }
    if (netif_) { esp_netif_destroy_default_wifi(netif_); netif_ = nullptr; }
    if (event_loop_owned_) { esp_event_loop_delete_default(); event_loop_owned_ = false; }
}
esp_err_t Network::start() {
    auto fail = [&](esp_err_t e) { cleanup(); return e; };
    auto e = nvs_flash_init(); // Do NOT erase NVS on version/no-free-pages errors.
    if (e != ESP_OK) return e;
    nvs_handle_t config = 0;
    e = nvs_open("node01_net", NVS_READONLY, &config);
    if (e != ESP_OK) return e;
    auto get = [&](const char* name, char* out, std::size_t capacity) {
        if (e == ESP_OK) e = nvs_get_str(config, name, out, &capacity);
    };
    get("ssid", ssid_, sizeof(ssid_)); get("psk", psk_, sizeof(psk_));
    get("uri", uri_, sizeof(uri_)); get("user", user_, sizeof(user_));
    get("pass", password_, sizeof(password_)); get("site", site_, sizeof(site_));
    nvs_close(config);
    if (e != ESP_OK) return e;
    if (!ssid_[0] || !user_[0] || !password_[0] || !topic_segment(site_)) return ESP_ERR_INVALID_ARG;
    // Only explicit MQTT transport, no HTTP substitution and no password logging.
    const bool tls = std::strncmp(uri_, "mqtts://", 8) == 0;
    if (!tls && std::strncmp(uri_, "mqtt://", 7) != 0) return ESP_ERR_INVALID_ARG;
    if (std::strchr(uri_, '@')) return ESP_ERR_INVALID_ARG; // credentials belong in NVS fields
    const auto psk_length = std::strlen(psk_);
    if (psk_length && (psk_length < 8 || psk_length > 63)) return ESP_ERR_INVALID_ARG;
    nvs_handle_t id_handle = 0;
    e = nvs_open("node01_id", NVS_READWRITE, &id_handle);
    if (e != ESP_OK) return e;
    NvsBootCounter counter(id_handle);
    const bool allocated = identity_.start(counter, board::device_id);
    nvs_close(id_handle);
    if (!allocated) {
        ESP_LOGE(tag, "IDENTITY_BLOCKED: existing provisioned counter + committed reservation required; no automatic seeding");
        return ESP_ERR_INVALID_STATE;
    }
    const auto n = std::snprintf(topic_, sizeof(topic_), "zhifang/v2/%s/%s/telemetry", site_, board::device_id);
    if (n < 0 || static_cast<unsigned>(n) >= sizeof(topic_)) return ESP_ERR_INVALID_SIZE;
    e = esp_netif_init(); if (e != ESP_OK) return e;
    e = esp_event_loop_create_default();
    event_loop_owned_ = e == ESP_OK;
    if (e != ESP_OK && e != ESP_ERR_INVALID_STATE) return e;
    netif_ = esp_netif_create_default_wifi_sta();
    if (!netif_) return fail(ESP_ERR_NO_MEM);
    wifi_init_config_t init = WIFI_INIT_CONFIG_DEFAULT();
    e = esp_wifi_init(&init); if (e != ESP_OK) return fail(e);
    wifi_initialized_ = true;
    e = esp_event_handler_instance_register(WIFI_EVENT, ESP_EVENT_ANY_ID, wifi_event, this, &wifi_handler_);
    if (e == ESP_OK) e = esp_event_handler_instance_register(IP_EVENT, IP_EVENT_STA_GOT_IP, wifi_event, this, &ip_handler_);
    if (e != ESP_OK) return fail(e);
    wifi_config_t wifi{};
    std::memcpy(wifi.sta.ssid, ssid_, std::strlen(ssid_));
    std::memcpy(wifi.sta.password, psk_, psk_length);
    e = esp_wifi_set_storage(WIFI_STORAGE_RAM);
    if (e == ESP_OK) e = esp_wifi_set_mode(WIFI_MODE_STA);
    if (e == ESP_OK) e = esp_wifi_set_config(WIFI_IF_STA, &wifi);
    if (e != ESP_OK) return fail(e);
    esp_mqtt_client_config_t mqtt{};
    mqtt.broker.address.uri = uri_;
    mqtt.credentials.username = user_;
    mqtt.credentials.authentication.password = password_;
    mqtt.credentials.client_id = board::device_id;
    mqtt.network.disable_auto_reconnect = true;
    mqtt.network.timeout_ms = 5000;
    mqtt.buffer.size = 2048; mqtt.buffer.out_size = 2048;
    mqtt.outbox.limit = 8192;
    mqtt.task.stack_size = 6144;
    if (tls) {
#ifdef CONFIG_MBEDTLS_CERTIFICATE_BUNDLE
        mqtt.broker.verification.crt_bundle_attach = esp_crt_bundle_attach;
#else
        return fail(ESP_ERR_NOT_SUPPORTED); // never silently disable certificate verification
#endif
    }
    mqtt_ = esp_mqtt_client_init(&mqtt);
    if (!mqtt_) return fail(ESP_ERR_NO_MEM);
    e = esp_mqtt_client_register_event(mqtt_, MQTT_EVENT_ANY, mqtt_event, this);
    if (e == ESP_OK) e = esp_wifi_start();
    if (e != ESP_OK) return fail(e);
    ready_ = true;
    ESP_LOGI(tag, "STA/MQTT configured; telemetry QoS=0 retained=false; edge_online remains false");
    return ESP_OK;
}
void Network::wifi_event(void* arg, esp_event_base_t base, std::int32_t id, void* data) {
    auto& self = *static_cast<Network*>(arg);
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) self.wifi_started_ = true;
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        self.links_.wifi_disconnected();
        const auto* event = static_cast<wifi_event_sta_disconnected_t*>(data);
        ESP_LOGW(tag, "WIFI_DISCONNECTED reason=%u", event ? event->reason : 0);
    }
    if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        self.links_.wifi_connected();
        self.wifi_connected_since_poll_ = true;
    }
}
void Network::mqtt_event(void* arg, esp_event_base_t, std::int32_t id, void*) {
    auto& self = *static_cast<Network*>(arg);
    if (id == MQTT_EVENT_CONNECTED) {
        if (self.links_.mqtt_connected()) self.mqtt_connected_since_poll_ = true;
        ESP_LOGI(tag, "MQTT_CONNECTED callback (requires observed Wi-Fi; not Atlas durable receipt)");
    }
    if (id == MQTT_EVENT_DISCONNECTED) { self.links_.mqtt_disconnected(); self.mqtt_disconnected_ = true; ESP_LOGW(tag, "MQTT_DISCONNECTED"); }
    if (id == MQTT_EVENT_ERROR) ESP_LOGE(tag, "MQTT_ERROR; no credential/payload logging");
}
void Network::poll(const sampling::SensorSnapshot& sensors, bool sd_ok) {
    if (!ready_) return;
    const auto now = static_cast<std::uint64_t>(esp_timer_get_time());
    wifi_retry_.observe_wifi(wifi_up(), wifi_connected_since_poll_.exchange(false), now);
    if (!wifi_up()) {
        if (wifi_started_ && wifi_retry_.due(now)) {
            const auto e = esp_wifi_connect();
            if (e != ESP_OK) ESP_LOGW(tag, "WIFI_CONNECT %s", esp_err_to_name(e));
            wifi_retry_.failed(now);
        }
        return;
    }
    if (mqtt_connected_since_poll_.exchange(false)) mqtt_retry_.connected();
    if (mqtt_disconnected_.exchange(false)) mqtt_retry_.failed(now);
    if (!mqtt_started_) {
        if (!mqtt_retry_.due(now)) return;
        const auto e = esp_mqtt_client_start(mqtt_);
        mqtt_started_ = e == ESP_OK;
        if (e != ESP_OK) { ESP_LOGE(tag, "MQTT_START %s", esp_err_to_name(e)); mqtt_retry_.failed(now); }
        else mqtt_retry_.requested();
        return;
    }
    if (!mqtt_up()) {
        if (mqtt_retry_.due(now)) {
            const auto e = esp_mqtt_client_reconnect(mqtt_);
            if (e != ESP_OK) ESP_LOGW(tag, "MQTT_RECONNECT %s", esp_err_to_name(e));
            // A successful asynchronous request is followed by CONNECTED or
            // DISCONNECTED. Only a failed attempt advances the backoff once.
            if (e == ESP_OK) mqtt_retry_.requested();
            else mqtt_retry_.failed(now);
        }
        return;
    }
    mqtt_retry_.connected();
    if (now < next_publish_) return;
    next_publish_ = now + 1000000; // diagnostic 1Hz; no calibrated risk-dependent rate selection yet
    auto draft = make_draft(sensors, now);
    draft.site_id = site_; draft.identity = identity_.next_original();
    draft.system.wifi_up = wifi_up(); draft.system.mqtt_up = mqtt_up(); draft.system.sd_ok = sd_ok;
    const auto encoded = serializer_.encode(draft, payload_, sizeof(payload_));
    if (encoded.status != protocol::SerializeStatus::Encoded) {
        ++rejected_; ESP_LOGE(tag, "TELEMETRY_BLOCKED invalid identity/draft/buffer"); return;
    }
    // Events may change while encoding. Re-check the joint observed link state;
    // enqueue itself still does not imply delivery or durable receipt.
    if (!mqtt_up()) { ++rejected_; return; }
    const int result = esp_mqtt_client_enqueue(mqtt_, topic_, payload_, encoded.bytes_written, 0, 0, true);
    if (result < 0) { ++rejected_; ESP_LOGW(tag, "MQTT_ENQUEUE rejected=%d (no durable queue implemented)", result); }
    else ++enqueued_; // only local enqueue, NOT delivered/durable/Atlas PASS
}
}
