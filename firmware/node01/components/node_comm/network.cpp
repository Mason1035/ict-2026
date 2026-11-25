#include "node/network.hpp"
#include "esp_wifi.h"
#include "esp_wifi_default.h"
#include "esp_timer.h"
#include "esp_log.h"
#include "nvs.h"
#include "nvs_flash.h"
#include <cstring>

namespace node::comm {
namespace { constexpr const char* tag = "node_comm"; }

void Network::cleanup_wifi() {
    ready_ = false;
    wifi_epoch_.fetch_and(~ip_bit);
    if (wifi_handler_) { esp_event_handler_instance_unregister(WIFI_EVENT, ESP_EVENT_ANY_ID, wifi_handler_); wifi_handler_ = nullptr; }
    if (ip_handler_) {
        esp_event_handler_instance_unregister(IP_EVENT, ESP_EVENT_ANY_ID, ip_handler_);
        ip_handler_ = nullptr;
    }
    if (wifi_initialized_) { esp_wifi_stop(); esp_wifi_deinit(); wifi_initialized_ = false; }
    if (netif_) { esp_netif_destroy_default_wifi(netif_); netif_ = nullptr; }
    if (event_loop_owned_) { esp_event_loop_delete_default(); event_loop_owned_ = false; }
}

esp_err_t Network::start() {
#if !defined(CONFIG_NODE01_WIFI_ONLY) && !defined(CONFIG_NODE01_NETWORK_ENABLE) && !defined(CONFIG_NODE01_MQTT_ONLY)
    return ESP_ERR_NOT_SUPPORTED;
#else
    if (start_called_) return ESP_ERR_INVALID_STATE;
    start_called_ = true;
    auto e = nvs_flash_init(); // Never erase NVS on initialization errors.
    if (e != ESP_OK) return e;
    nvs_handle_t settings = 0;
#ifdef CONFIG_NODE01_REAL_TEST_ONLY
    e = nvs_open("node01_realtest", NVS_READONLY, &settings);
#elif defined(CONFIG_NODE01_MQTT_ONLY)
    e = nvs_open("node01_mqdiag", NVS_READONLY, &settings);
#else
    e = nvs_open("node01_net", NVS_READONLY, &settings);
#endif
    if (e != ESP_OK) return e;
#ifdef CONFIG_NODE01_MQTT_ONLY
    std::uint8_t enabled = 0;
    if (nvs_get_u8(settings, "enable", &enabled) != ESP_OK || enabled != 1) {
        nvs_close(settings);
#ifdef CONFIG_NODE01_REAL_TEST_ONLY
        ESP_LOGW(tag, "REAL_TEST_ONLY_DISARMED");
#else
        ESP_LOGW(tag, "MQTT_ONLY_DISARMED");
#endif
        return ESP_ERR_INVALID_STATE;
    }
#endif
#ifdef CONFIG_NODE01_WIFI_ONLY
    std::uint8_t armed = 0;
    if (nvs_get_u8(settings, "wifi_only", &armed) != ESP_OK || armed != 1) {
        nvs_close(settings);
        ESP_LOGW(tag, "WIFI_ONLY_DISARMED; explicit diagnostic opt-in required");
        return ESP_ERR_INVALID_STATE;
    }
#endif
    std::size_t ssid_capacity = sizeof(ssid_), psk_capacity = sizeof(psk_);
    e = nvs_get_str(settings, "ssid", ssid_, &ssid_capacity);
    if (e == ESP_OK) e = nvs_get_str(settings, "psk", psk_, &psk_capacity);
    if (e == ESP_ERR_NVS_NOT_FOUND) {
        psk_[0] = '\0';
        e = ESP_OK;
    }
#ifdef CONFIG_NODE01_MQTT_ONLY
    if (e == ESP_OK) e = mqtt_only_.configure(settings);
#endif
    nvs_close(settings);
    if (e != ESP_OK) return e;
    const auto ssid_length = std::strlen(ssid_), psk_length = std::strlen(psk_);
#ifdef CONFIG_NODE01_MQTT_ONLY
    if (psk_length < 8) return ESP_ERR_INVALID_ARG;
#endif
    if (!ssid_length || ssid_length > 32 || (psk_length && (psk_length < 8 || psk_length > 63)))
        return ESP_ERR_INVALID_ARG;
#ifdef CONFIG_NODE01_NETWORK_ENABLE
    e = provision_mqtt();
    if (e != ESP_OK) return e;
#endif
    auto fail = [&](esp_err_t error) { cleanup_wifi(); return error; };
    e = esp_netif_init(); if (e != ESP_OK) return e;
    e = esp_event_loop_create_default();
    event_loop_owned_ = e == ESP_OK;
    if (e != ESP_OK && e != ESP_ERR_INVALID_STATE) return e;
    netif_ = esp_netif_create_default_wifi_sta();
    if (!netif_) return fail(ESP_ERR_NO_MEM);
    wifi_init_config_t init = WIFI_INIT_CONFIG_DEFAULT();
#if defined(CONFIG_NODE01_WIFI_ONLY) || defined(CONFIG_NODE01_MQTT_ONLY)
    init.nvs_enable = 0;
#endif
    e = esp_wifi_init(&init); if (e != ESP_OK) return fail(e);
    wifi_initialized_ = true;
    e = esp_event_handler_instance_register(WIFI_EVENT, ESP_EVENT_ANY_ID, wifi_event, this, &wifi_handler_);
    if (e == ESP_OK) e = esp_event_handler_instance_register(IP_EVENT, ESP_EVENT_ANY_ID, wifi_event, this, &ip_handler_);
    if (e != ESP_OK) return fail(e);
    wifi_config_t wifi{};
    wifi.sta.threshold.authmode = psk_length == 0 ? WIFI_AUTH_OPEN : WIFI_AUTH_WPA2_PSK;
    std::memcpy(wifi.sta.ssid, ssid_, ssid_length);
    std::memcpy(wifi.sta.password, psk_, psk_length);
    e = esp_wifi_set_storage(WIFI_STORAGE_RAM);
    if (e == ESP_OK) e = esp_wifi_set_mode(WIFI_MODE_STA);
    if (e == ESP_OK) e = esp_wifi_set_config(WIFI_IF_STA, &wifi);
    if (e == ESP_OK) e = esp_wifi_start();
    if (e != ESP_OK) return fail(e);
#ifdef CONFIG_NODE01_NETWORK_ENABLE
    if (xTaskCreate(mqtt_worker, "MqttSdkWork", 4096, this, 3, &worker_) != pdPASS)
        return fail(ESP_ERR_NO_MEM);
    ESP_LOGI(tag, "STA/MQTT configured; telemetry QoS=0 retained=false");
#elif defined(CONFIG_NODE01_MQTT_ONLY)
    e = mqtt_only_.start_window(static_cast<std::uint64_t>(esp_timer_get_time()));
    if (e != ESP_OK) return fail(e);
#else
    ESP_LOGI(tag, "WIFI_ONLY_ARMED; no MQTT, identity allocation or publication");
#endif
    ready_ = true;
    return ESP_OK;
#endif
}

void Network::wifi_event(void* arg, esp_event_base_t base, std::int32_t id, void* data) {
    auto& self = *static_cast<Network*>(arg);
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) self.wifi_started_ = true;
    if ((base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) ||
        (base == IP_EVENT && id == IP_EVENT_STA_LOST_IP)) {
        auto previous = self.wifi_epoch_.load();
        while (!self.wifi_epoch_.compare_exchange_weak(previous, (previous + 2) & ~ip_bit)) {}
        if (base == WIFI_EVENT) {
            const auto* event = static_cast<wifi_event_sta_disconnected_t*>(data);
            ESP_LOGW(tag, "WIFI_DISCONNECTED reason=%u", event ? event->reason : 0);
        }
    }
    if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        const auto* event = static_cast<ip_event_got_ip_t*>(data);
        if (event && event->esp_netif == self.netif_ && self.wifi_started_) {
            self.wifi_epoch_.fetch_or(ip_bit);
            self.wifi_connected_since_poll_ = true;
            ESP_LOGI(tag, "WIFI_GOT_IP " IPSTR, IP2STR(&event->ip_info.ip));
        }
    }
}

#ifdef CONFIG_NODE01_REAL_TEST_ONLY
void Network::poll(const sampling::SensorSnapshot& sensors, bool sd_ok, MqttOnly::CaptureStatus capture) {
#else
void Network::poll(const sampling::SensorSnapshot& sensors, bool sd_ok) {
#endif
    if (!ready_) return;
    const auto now = static_cast<std::uint64_t>(esp_timer_get_time());
    wifi_retry_.observe_wifi(wifi_up(), wifi_connected_since_poll_.exchange(false), now);
    if (!wifi_up() && wifi_started_ && wifi_retry_.due(now)) {
        const auto e = esp_wifi_connect();
        if (e != ESP_OK) ESP_LOGW(tag, "WIFI_CONNECT %s", esp_err_to_name(e));
        wifi_retry_.failed(now);
    }
#ifdef CONFIG_NODE01_NETWORK_ENABLE
    poll_mqtt(sensors, sd_ok, now);
#else
    (void)sensors;
    (void)sd_ok;
#ifdef CONFIG_NODE01_MQTT_ONLY
    mqtt_only_.poll(now);
#ifdef CONFIG_NODE01_REAL_TEST_ONLY
    if (sd_ok) mqtt_only_.poll_telemetry(sensors, capture, now);
#endif
#endif
#endif
}
}
