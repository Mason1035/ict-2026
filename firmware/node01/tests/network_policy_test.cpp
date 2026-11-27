#include "node/network_policy.hpp"
#include <cassert>
#include <cstdio>

int main() {
    using namespace node::comm::policy;
    RetrySchedule wifi;
    std::uint64_t now = 0;
    constexpr unsigned delays[]{5, 10, 20, 40, 60, 60};
    for (const auto seconds : delays) {
        assert(wifi.due(now));
        wifi.failed(now);
        const auto next = now + seconds * 1000000ULL;
        assert(!wifi.due(next - 1));
        assert(wifi.due(next));
        now = next;
    }
    // Long failure -> briefly connected -> disconnected entirely between polls.
    wifi.failed(now); // old 60s deadline must not survive the observed success
    wifi.observe_wifi(false, true, now + 100);
    assert(!wifi.due(now + 5000099));
    assert(wifi.due(now + 5000100));
    wifi.observe_wifi(true, false, now + 200);
    assert(wifi.due(now + 200)); // success cleared the old deadline
    wifi.failed(now + 300);
    assert(wifi.due(now + 5000300)); // stage restarted at 5s

    RetrySchedule mqtt;
    assert(mqtt.due(0));
    mqtt.requested();
    assert(!mqtt.due(1000000000)); // asynchronous request is not repeated in flight
    mqtt.failed(100); // eventual DISCONNECTED: advance once, not on request
    assert(!mqtt.due(5000099) && mqtt.due(5000100));
    mqtt.requested();
    mqtt.failed(5000200);
    assert(!mqtt.due(15000199) && mqtt.due(15000200)); // next failure is 10s
    mqtt.connected();
    mqtt.failed(20000000);
    assert(mqtt.due(25000000));

    ObservedLinks links;
    assert(!links.wifi_up() && !links.mqtt_up());
    assert(!links.mqtt_connected()); // stale callback while Wi-Fi is absent
    links.wifi_connected();
    assert(links.wifi_up() && !links.mqtt_up());
    assert(links.mqtt_connected() && links.mqtt_up());
    links.wifi_disconnected();
    assert(!links.wifi_up() && !links.mqtt_up());
    assert(!links.mqtt_connected() && !links.mqtt_up());
    links.wifi_connected();
    assert(!links.mqtt_up()); // ignored old callback cannot revive next Wi-Fi epoch
    assert(links.mqtt_connected());
    links.mqtt_disconnected();
    assert(links.wifi_up() && !links.mqtt_up());
    std::puts("HOST_NETWORK_POLICY_TEST_PASS (TEST_ONLY retry clocks/link event order; Wi-Fi/MQTT hardware NOT_RUN)");
}
