#pragma once
#include <atomic>
#include <cstdint>

namespace node::comm::policy {
// CommSupervisorTask owns scheduling. Callbacks only report observed link events.
class RetrySchedule {
public:
    bool due(std::uint64_t now) const { return !in_flight_ && now >= deadline_; }
    void failed(std::uint64_t now) {
        constexpr unsigned seconds[]{5, 10, 20, 40, 60};
        deadline_ = now + seconds[stage_] * 1000000ULL;
        if (stage_ < 4) ++stage_;
        in_flight_ = false;
    }
    void requested() { in_flight_ = true; }
    void connected() { stage_ = 0; deadline_ = 0; in_flight_ = false; }
    // Remember a success between polls: a subsequent loss starts again at 5s.
    void observe_wifi(bool online, bool connected_since_poll, std::uint64_t now) {
        if (online || connected_since_poll) connected();
        if (!online && connected_since_poll) failed(now);
    }
private:
    unsigned stage_ = 0;
    std::uint64_t deadline_ = 0;
    bool in_flight_ = false;
};

// One atomic observation prevents a delayed MQTT_CONNECTED from restoring MQTT
// readiness after Wi-Fi loss. This is observed connectivity, never durable receipt.
class ObservedLinks {
public:
    void wifi_connected() { bits_.fetch_or(wifi_bit); }
    void wifi_disconnected() { bits_.fetch_and(~(wifi_bit | mqtt_bit)); }
    bool mqtt_connected() {
        auto previous = bits_.load();
        while (previous & wifi_bit) {
            if (bits_.compare_exchange_weak(previous, previous | mqtt_bit)) return true;
        }
        return false;
    }
    void mqtt_disconnected() { bits_.fetch_and(~mqtt_bit); }
    bool wifi_up() const { return (bits_.load() & wifi_bit) != 0; }
    bool mqtt_up() const { return (bits_.load() & (wifi_bit | mqtt_bit)) == (wifi_bit | mqtt_bit); }
private:
    static constexpr std::uint32_t wifi_bit = 1, mqtt_bit = 2;
    std::atomic<std::uint32_t> bits_{0};
};
}
