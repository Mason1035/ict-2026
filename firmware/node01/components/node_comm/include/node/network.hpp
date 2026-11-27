#pragma once
#include "sdkconfig.h"
#include "node/network_policy.hpp"
#include "node/telemetry.hpp"
#include "esp_err.h"
#include "esp_event.h"
#include "esp_netif.h"
#include <atomic>
#ifdef CONFIG_NODE01_MQTT_ONLY
#include "node/mqtt_only.hpp"
#endif

#ifdef CONFIG_NODE01_NETWORK_ENABLE
#include "node/identity.hpp"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "mqtt_client.h"
#endif

namespace node::comm {
// One owner (CommSupervisorTask). In the MQTT profile this object has boot
// lifetime, including when an SDK worker cannot return.
class Network {
public:
    esp_err_t start();
#ifdef CONFIG_NODE01_REAL_TEST_ONLY
    void poll(const sampling::SensorSnapshot&, bool sd_ok, MqttOnly::CaptureStatus = nullptr);
    esp_err_t authorize_publish(unsigned limit) {
        return ready_ ? mqtt_only_.authorize_publish(limit) : ESP_ERR_INVALID_STATE;
    }
#else
    void poll(const sampling::SensorSnapshot&, bool sd_ok);
#endif
    bool wifi_up() const { return (wifi_epoch_.load() & ip_bit) != 0; }
#ifdef CONFIG_NODE01_NETWORK_ENABLE
    bool mqtt_up() const;
    std::uint32_t enqueued() const { return enqueued_; }
    std::uint32_t rejected() const { return rejected_; }
#else
#ifdef CONFIG_NODE01_MQTT_ONLY
    bool mqtt_up() const { return mqtt_only_.up(); }
#else
    bool mqtt_up() const { return false; }
#endif
#ifdef CONFIG_NODE01_REAL_TEST_ONLY
    std::uint32_t enqueued() const { return mqtt_only_.submitted(); }
    std::uint32_t rejected() const { return mqtt_only_.rejected(); }
#else
    std::uint32_t enqueued() const { return 0; }
    std::uint32_t rejected() const { return 0; }
#endif
#endif

private:
    static void wifi_event(void*, esp_event_base_t, std::int32_t, void*);
    void cleanup_wifi();
    static constexpr std::uint32_t ip_bit = 1;
    // The low bit is IP readiness. A loss invalidates every older MQTT
    // attempt even when loss and recovery both occur between owner polls.
    std::atomic<std::uint32_t> wifi_epoch_{0};
#ifdef CONFIG_NODE01_MQTT_ONLY
    MqttOnly mqtt_only_{wifi_epoch_};
#endif
    std::atomic<bool> wifi_started_{false}, wifi_connected_since_poll_{false};
    esp_netif_t* netif_ = nullptr;
    esp_event_handler_instance_t wifi_handler_ = nullptr, ip_handler_ = nullptr;
    bool wifi_initialized_ = false, event_loop_owned_ = false, ready_ = false;
    bool start_called_ = false;
    policy::RetrySchedule wifi_retry_;
    char ssid_[33]{}, psk_[65]{};

#ifdef CONFIG_NODE01_NETWORK_ENABLE
    enum class Signal { Inactive, Connecting, Online, Failed };
    enum class Work { Idle, Enqueue, EnqueueDone, Retire, RetireDone, RetireFailed };
    static void mqtt_event(void*, esp_event_base_t, std::int32_t, void*);
    static void mqtt_worker(void*);
    esp_err_t provision_mqtt();
    void begin_mqtt(std::uint64_t now, std::uint32_t wifi_epoch);
    void poll_mqtt(const sampling::SensorSnapshot&, bool sd_ok, std::uint64_t now);
    void retire_mqtt(std::uint64_t now, const char* reason);
    void poll_retirement(std::uint64_t now);
    void post_work(Work job);

    TaskHandle_t worker_ = nullptr;
    // The handle and job data transfer through work_ publication/completion.
    // A still-running worker and its client are retained after a deadline.
    std::atomic<Work> work_{Work::Idle};
    esp_mqtt_client_handle_t mqtt_ = nullptr;
    std::atomic<esp_mqtt_client_handle_t> callback_client_{nullptr};
    std::atomic<Signal> signal_{Signal::Inactive};
    std::atomic<bool> sdk_task_entered_{false};
    std::atomic<std::uint32_t> attempt_epoch_{0};
    std::uint64_t connect_deadline_ = 0;
    bool retiring_ = false, retire_deadline_reported_ = false, online_observed_ = false;
    std::uint64_t retire_deadline_ = 0, enqueue_deadline_ = 0, next_publish_ = 0;
    std::uint32_t enqueued_ = 0, rejected_ = 0;
    int payload_bytes_ = 0, enqueue_result_ = 0;
    bool tls_ = false;
    char uri_[192]{}, user_[65]{}, password_[129]{}, site_[65]{}, device_[65]{}, topic_[128]{};
    char payload_[2048]{};
    DurableIdentity identity_;
    V2Serializer serializer_;
    policy::RetrySchedule mqtt_retry_;
#endif
};
}
