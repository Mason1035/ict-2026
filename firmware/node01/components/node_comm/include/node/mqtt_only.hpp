#pragma once
#include "sdkconfig.h"
#include "node/network_policy.hpp"
#include "esp_err.h"
#include "mqtt_client.h"
#include "nvs.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include <atomic>
#ifdef CONFIG_NODE01_REAL_TEST_ONLY
#include "node/telemetry.hpp"
#endif

namespace node::comm {
// CommSupervisor owns poll(). The worker owns all MQTT SDK calls and the
// handle. This object must remain alive if the SDK worker cannot return.
class MqttOnly {
public:
    explicit MqttOnly(const std::atomic<std::uint32_t>& wifi_epoch) : wifi_epoch_(wifi_epoch) {}
    esp_err_t configure(nvs_handle_t settings);
    esp_err_t start_window(std::uint64_t now);
    void poll(std::uint64_t now);
    bool up() const;
#ifdef CONFIG_NODE01_REAL_TEST_ONLY
    struct CapturePermit { std::uint64_t started_us = 0, end_us = 0; };
    using CaptureStatus = CapturePermit (*)();
    esp_err_t authorize_publish(unsigned limit);
    void poll_telemetry(const sampling::SensorSnapshot&, CaptureStatus, std::uint64_t now);
    std::uint32_t submitted() const { return submitted_; }
    std::uint32_t rejected() const { return rejected_; }
#endif

private:
    enum class Signal { Inactive, Connecting, Online, Failed };
    enum class Work { Idle, Start, Started, StartDeclined, Publish, Stop, Released, Blocked };
    static void event(void*, esp_event_base_t, std::int32_t, void*);
    static void run(void*);
    void post(Work);
    void start_client();
    void stop_client();
    void retire(std::uint64_t now, const char* reason);
    void poll_retirement(std::uint64_t now, Work stage);

#ifdef CONFIG_NODE01_REAL_TEST_ONLY
    void publish_sample();
    unsigned publish_limit_ = 0; // owner only, revoked on session retirement
    bool authorization_used_ = false;
    std::uint64_t boot_id_ = 0, seq_ = 0, next_attempt_ = 0, next_send_ = 0;
    std::uint64_t job_end_ = 0;
    std::atomic<std::uint32_t> submitted_{0}, rejected_{0};
    CaptureStatus capture_status_ = nullptr;
    sampling::SensorSnapshot pending_sample_{};
    char payload_[1536]{};
#endif
    const std::atomic<std::uint32_t>& wifi_epoch_; // bit 0 means IPv4 ready
    std::atomic<std::uint32_t> attempt_epoch_{0};
    std::atomic<esp_mqtt_client_handle_t> callback_client_{nullptr};
    std::atomic<Signal> signal_{Signal::Inactive};
    std::atomic<Work> work_{Work::Idle};
    // An SDK callback proves the MQTT task entered. start() returning OK alone does not.
    std::atomic<bool> sdk_entered_{false};
    TaskHandle_t worker_ = nullptr;
    esp_mqtt_client_handle_t client_ = nullptr; // worker only
    bool configured_ = false, closed_ = false, active_ = false, retiring_ = false;
    bool observed_online_ = false, quarantine_reported_ = false;
    std::uint64_t window_end_ = 0, connect_end_ = 0, retire_end_ = 0;
    policy::RetrySchedule retry_;
    std::uint16_t port_ = 0;
    char host_[128]{}, user_[65]{}, password_[129]{}, client_id_[32]{};
#ifdef CONFIG_MQTT_TRANSPORT_SSL
    char ca_pem_[3072]{};
#endif
};
}
