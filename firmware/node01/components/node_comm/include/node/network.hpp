#pragma once
#include "node/identity.hpp"
#include "node/telemetry.hpp"
#include "node/network_policy.hpp"
#include "esp_err.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "mqtt_client.h"
#include <atomic>

namespace node::comm {
class Network {
public:
    esp_err_t start();
    void poll(const sampling::SensorSnapshot&, bool sd_ok);
    bool wifi_up() const { return links_.wifi_up(); }
    bool mqtt_up() const { return links_.mqtt_up(); }
    std::uint32_t enqueued() const { return enqueued_; }
    std::uint32_t rejected() const { return rejected_; }
private:
    static void wifi_event(void*, esp_event_base_t, std::int32_t, void*);
    static void mqtt_event(void*, esp_event_base_t, std::int32_t, void*);
    void cleanup();
    esp_mqtt_client_handle_t mqtt_ = nullptr;
    esp_netif_t* netif_ = nullptr;
    esp_event_handler_instance_t wifi_handler_ = nullptr, ip_handler_ = nullptr;
    bool wifi_initialized_ = false, event_loop_owned_ = false, ready_ = false, mqtt_started_ = false;
    policy::ObservedLinks links_;
    std::atomic<bool> wifi_started_{false}, wifi_connected_since_poll_{false};
    std::atomic<bool> mqtt_disconnected_{false}, mqtt_connected_since_poll_{false};
    policy::RetrySchedule wifi_retry_, mqtt_retry_;
    std::uint64_t next_publish_ = 0;
    std::uint32_t enqueued_ = 0, rejected_ = 0;
    char ssid_[33]{}, psk_[65]{}, uri_[192]{}, user_[65]{}, password_[129]{}, site_[65]{}, topic_[128]{};
    char payload_[2048]{};
    DurableIdentity identity_;
    V2Serializer serializer_;
};
}
