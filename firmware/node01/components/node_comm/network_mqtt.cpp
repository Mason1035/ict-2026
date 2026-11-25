#include "node/network.hpp"
#include "node/board.hpp"
#ifdef CONFIG_MBEDTLS_CERTIFICATE_BUNDLE
#include "esp_crt_bundle.h"
#endif
#include "esp_log.h"
#include "esp_timer.h"
#include "nvs.h"
#include <cstdio>
#include <cstring>

namespace node::comm {
namespace {
constexpr const char* tag = "node_comm";
constexpr std::uint64_t connect_budget_us = 15'000'000;
constexpr std::uint64_t enqueue_budget_us = 10'000'000;
constexpr std::uint64_t retire_budget_us = 10'000'000;

class NvsBootCounter final : public BootCounterStore {
public:
    explicit NvsBootCounter(nvs_handle_t handle) : handle_(handle) {}
    bool load(protocol::Integer& out) override { return nvs_get_u64(handle_, "last_boot", &out) == ESP_OK; }
    bool commit(protocol::Integer value) override {
        return nvs_set_u64(handle_, "last_boot", value) == ESP_OK && nvs_commit(handle_) == ESP_OK;
    }
private:
    nvs_handle_t handle_;
};
}

esp_err_t Network::provision_mqtt() {
    nvs_handle_t settings = 0;
    auto error = nvs_open("node01_net", NVS_READONLY, &settings);
    if (error != ESP_OK) return error;
    auto get = [&](const char* key, char* out, std::size_t capacity) {
        if (error == ESP_OK) error = nvs_get_str(settings, key, out, &capacity);
    };
    get("uri", uri_, sizeof(uri_));
    get("user", user_, sizeof(user_));
    get("pass", password_, sizeof(password_));
    get("site", site_, sizeof(site_));
    if (error == ESP_OK) {
        std::size_t dev_cap = sizeof(device_);
        const auto dev_err = nvs_get_str(settings, "device", device_, &dev_cap);
        if (dev_err == ESP_ERR_NVS_NOT_FOUND || (dev_err == ESP_OK && !device_[0])) {
            std::snprintf(device_, sizeof(device_), "%s", board::device_id);
        } else if (dev_err != ESP_OK) {
            error = dev_err;
        }
    }
    nvs_close(settings);
    if (error != ESP_OK) return error;
    if (!user_[0] || !password_[0] || !topic_segment(site_) || !topic_segment(device_)) return ESP_ERR_INVALID_ARG;
    tls_ = std::strncmp(uri_, "mqtts://", 8) == 0;
    if ((!tls_ && std::strncmp(uri_, "mqtt://", 7) != 0) || std::strchr(uri_, '@')) return ESP_ERR_INVALID_ARG;
#ifndef CONFIG_MBEDTLS_CERTIFICATE_BUNDLE
    if (tls_) return ESP_ERR_NOT_SUPPORTED;
#endif
    const auto bytes = std::snprintf(topic_, sizeof(topic_), "zhifang/v2/%s/%s/telemetry", site_, device_);
    if (bytes < 0 || static_cast<unsigned>(bytes) >= sizeof(topic_)) return ESP_ERR_INVALID_SIZE;
    nvs_handle_t id_handle = 0;
    error = nvs_open("node01_id", NVS_READWRITE, &id_handle);
    if (error != ESP_OK) return error;
    NvsBootCounter counter(id_handle);
    const bool allocated = identity_.start(counter, device_);
    nvs_close(id_handle);
    if (!allocated) {
        ESP_LOGE(tag, "IDENTITY_BLOCKED: existing provisioned counter and commit required");
        return ESP_ERR_INVALID_STATE;
    }
    ESP_LOGI(tag, "MQTT_PROVISIONED uri=%s topic=%s device=%s", uri_, topic_, device_);
    return ESP_OK;
}

bool Network::mqtt_up() const {
    const auto epoch = wifi_epoch_.load();
    return (epoch & ip_bit) && epoch == attempt_epoch_.load() && signal_.load() == Signal::Online;
}

void Network::begin_mqtt(std::uint64_t now, std::uint32_t epoch) {
    esp_mqtt_client_config_t config{};
    config.broker.address.uri = uri_;
    config.credentials.username = user_;
    config.credentials.authentication.password = password_;
    config.credentials.client_id = device_;
    config.session.protocol_ver = MQTT_PROTOCOL_V_3_1_1;
    config.network.disable_auto_reconnect = true;
    config.network.timeout_ms = 5000;
    config.buffer.size = 2048;
    config.buffer.out_size = 2048;
    config.outbox.limit = 8192;
    config.task.stack_size = 6144;
#ifdef CONFIG_MBEDTLS_CERTIFICATE_BUNDLE
    if (tls_) config.broker.verification.crt_bundle_attach = esp_crt_bundle_attach;
#endif
    mqtt_ = esp_mqtt_client_init(&config);
    if (!mqtt_) {
        ESP_LOGE(tag, "MQTT_INIT failed");
        mqtt_retry_.failed(now);
        return;
    }
    sdk_task_entered_ = false;
    attempt_epoch_ = epoch;
    connect_deadline_ = now + connect_budget_us;
    callback_client_ = mqtt_;
    signal_ = Signal::Connecting;
    auto error = esp_mqtt_client_register_event(mqtt_, MQTT_EVENT_ANY, mqtt_event, this);
    if (error == ESP_OK) error = esp_mqtt_client_start(mqtt_);
    if (error != ESP_OK) {
        // In the pinned SDK a failed start does not create a task.
        ESP_LOGW(tag, "MQTT_START %s", esp_err_to_name(error));
        retire_mqtt(now, "START_REJECTED");
        post_work(Work::Retire);
    }
}

void Network::mqtt_event(void* arg, esp_event_base_t, std::int32_t id, void* data) {
    auto& self = *static_cast<Network*>(arg);
    const auto* event = static_cast<esp_mqtt_event_t*>(data);
    if (!event || !event->client || event->client != self.callback_client_.load()) return;

    // On ESP-IDF 5.5.3 these events dispatch from the client task after run
    // is set. A returned start() alone does not prove the task has entered.
    if (id != MQTT_EVENT_BEFORE_CONNECT && id != MQTT_EVENT_CONNECTED &&
        id != MQTT_EVENT_DISCONNECTED && id != MQTT_EVENT_ERROR) return;
    self.sdk_task_entered_ = true;
    if (id == MQTT_EVENT_CONNECTED) {
        if (self.wifi_epoch_.load() != self.attempt_epoch_.load() ||
            static_cast<std::uint64_t>(esp_timer_get_time()) >= self.connect_deadline_) return;
        auto expected = Signal::Connecting;
        self.signal_.compare_exchange_strong(expected, Signal::Online);
    } else if (id == MQTT_EVENT_ERROR || id == MQTT_EVENT_DISCONNECTED) {
        auto previous = self.signal_.load();
        while ((previous == Signal::Connecting || previous == Signal::Online) &&
               !self.signal_.compare_exchange_weak(previous, Signal::Failed)) {}
    }
}

void Network::post_work(Work job) {
    work_ = job;
    xTaskNotifyGive(worker_);
}

void Network::mqtt_worker(void* arg) {
    auto& self = *static_cast<Network*>(arg);
    for (;;) {
        ulTaskNotifyTake(pdTRUE, portMAX_DELAY); // Idle worker, no owner waits for it.
        const auto job = self.work_.load();
        if (job == Work::Enqueue) {
            self.enqueue_result_ = self.mqtt_up()
                ? esp_mqtt_client_enqueue(self.mqtt_, self.topic_, self.payload_, self.payload_bytes_, 0, 0, true)
                : -1;
            self.work_ = Work::EnqueueDone;
        } else if (job == Work::Retire) {
            // For a successful start we only get here after observing task
            // entry. Stop must succeed before destroy or context reuse.
            auto result = self.sdk_task_entered_ ? esp_mqtt_client_stop(self.mqtt_) : ESP_OK;
            if (result == ESP_OK) result = esp_mqtt_client_destroy(self.mqtt_);
            self.work_ = result == ESP_OK ? Work::RetireDone : Work::RetireFailed;
        }
    }
}

void Network::retire_mqtt(std::uint64_t now, const char* reason) {
    signal_ = Signal::Inactive;
    retiring_ = true;
    retire_deadline_reported_ = false;
    retire_deadline_ = now + retire_budget_us;
    online_observed_ = false;
    mqtt_retry_.failed(now);
    ESP_LOGW(tag, "MQTT_RETIRE reason=%s", reason);
}

void Network::poll_retirement(std::uint64_t now) {
    const auto work = work_.load();
    if (work == Work::RetireDone) {
        callback_client_ = nullptr;
        mqtt_ = nullptr;
        work_ = Work::Idle;
        retiring_ = false;
        ESP_LOGI(tag, "MQTT_RETIRED");
        return;
    }
    if (!retire_deadline_reported_ && (work == Work::RetireFailed || now >= retire_deadline_)) {
        retire_deadline_reported_ = true;
        const char* reason = work == Work::RetireFailed ? "SDK_FAILED" :
                             work == Work::Enqueue ? "ENQUEUE_WAIT" :
                             work == Work::Retire ? "SDK_STOP_OR_DESTROY_WAIT" : "TASK_ENTRY_UNPROVEN";
        ESP_LOGE(tag, "MQTT_RETIRE_QUARANTINED reason=%s; client retained, no replacement", reason);
    }
    if (work == Work::Idle && sdk_task_entered_) post_work(Work::Retire);
}

void Network::poll_mqtt(const sampling::SensorSnapshot& sensors, bool sd_ok, std::uint64_t now) {
    if (work_ == Work::EnqueueDone) {
        if (enqueue_result_ < 0) {
            ++rejected_;
            ESP_LOGW(tag, "MQTT_ENQUEUE rejected=%d", enqueue_result_);
        } else {
            ++enqueued_; // Local enqueue only.
        }
        work_ = Work::Idle;
    }
    if (retiring_) {
        poll_retirement(now);
        return;
    }
    const auto epoch = wifi_epoch_.load();
    if (!mqtt_) {
        if ((epoch & ip_bit) && mqtt_retry_.due(now)) begin_mqtt(now, epoch);
        return;
    }
    const auto signal = signal_.load();
    const char* retire_reason = nullptr;
    if (!(epoch & ip_bit) || epoch != attempt_epoch_) retire_reason = "WIFI_EPOCH_CHANGED";
    else if (signal == Signal::Failed) retire_reason = "MQTT_TERMINAL_EVENT";
    else if (signal == Signal::Connecting && now >= connect_deadline_) retire_reason = "CONNECT_DEADLINE";
    else if (work_ == Work::Enqueue && now >= enqueue_deadline_) retire_reason = "ENQUEUE_DEADLINE";
    if (retire_reason) {
        retire_mqtt(now, retire_reason);
        poll_retirement(now);
        return;
    }
    if (signal != Signal::Online) return;
    if (!online_observed_) {
        online_observed_ = true;
        mqtt_retry_.connected();
        ESP_LOGI(tag, "MQTT_CONNECTED; Atlas receipt unverified");
    }
    if (work_ != Work::Idle || now < next_publish_ || !mqtt_up()) return;
    next_publish_ = now + 1'000'000;
    auto draft = make_draft(sensors, now);
    draft.site_id = site_;
    draft.identity = identity_.next_original();
    draft.system.wifi_up = wifi_up();
    draft.system.mqtt_up = mqtt_up();
    draft.system.sd_ok = sd_ok;
    const auto encoded = serializer_.encode(draft, payload_, sizeof(payload_));
    if (encoded.status != protocol::SerializeStatus::Encoded || !mqtt_up()) {
        ++rejected_;
        return;
    }
    payload_bytes_ = static_cast<int>(encoded.bytes_written);
    enqueue_deadline_ = now + enqueue_budget_us;
    post_work(Work::Enqueue);
}
}
