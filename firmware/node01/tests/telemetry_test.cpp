#include "node/telemetry.hpp"
#include "node/identity.hpp"
#include <cassert>
#include <cstdio>
#include <cstring>
#include <limits>

class Counter final : public node::comm::BootCounterStore {
public:
    node::protocol::Integer value = 0;
    bool exists = true, fail_commit = false, corrupt_readback = false;
    bool load(node::protocol::Integer& v) override { v = value; return exists; }
    bool commit(node::protocol::Integer v) override {
        if (fail_commit) return false;
        value = v + (corrupt_readback ? 1 : 0); return true;
    }
};
int main(int argc, char**) {
    using namespace node;
    Counter store;
    comm::DurableIdentity first;
    assert(!first.next_original());
    assert(first.start(store, "NODE-01"));
    const auto a = first.next_original(), b = first.next_original();
    assert(a && b && a->boot_id == 1 && a->seq == 1 && b->seq == 2);
    assert(!first.start(store, "NODE-01"));
    comm::DurableIdentity reboot;
    assert(reboot.start(store, "NODE-01"));
    const auto c = reboot.next_original();
    assert(c && c->boot_id == 2 && c->seq == 1);
    for (unsigned mode = 0; mode < 4; ++mode) {
        Counter bad;
        if (mode == 0) bad.exists = false;
        if (mode == 1) bad.fail_commit = true;
        if (mode == 2) bad.corrupt_readback = true;
        if (mode == 3) bad.value = protocol::json_safe_integer_max;
        comm::DurableIdentity blocked;
        assert(!blocked.start(bad, "NODE-01"));
        assert(!blocked.next_original());
    }
    sampling::SensorSnapshot input;
    for (auto& imu : input.imu) {
        imu.validity = sampling::Validity::Valid;
        imu.acquired_uptime_us = 100000;
        imu.acceleration_mps2 = {0, 0, 9.80665f};
    }
    for (auto& soil : input.soil) {
        soil.validity = sampling::Validity::Valid;
        soil.acquired_uptime_us = 100000; soil.raw = 1000;
    }
    auto d = comm::make_draft(input, 110000);
    d.site_id = "TEST_ONLY"; d.identity = a;
    assert(!d.system.sensor_degraded && !d.risk.sensor_score && !d.risk.level && !d.risk.reason_mask);
    assert(!d.timestamp_ms && !d.time_synced && !d.soil.top_pct);
    comm::V2Serializer serializer;
    char json[2048];
    auto encode = [&]() { return serializer.encode(d, json, sizeof(json)).status; };
    using protocol::SerializeStatus;
    assert(encode() == SerializeStatus::Encoded);
    if (argc > 1) std::puts(json); // TEST_ONLY host vector, never sent to a Broker
    input.soil[1] = {}; // M02 semantics: missing middle must remain null
    d = comm::make_draft(input, 110000); d.site_id = "TEST_ONLY"; d.identity = a;
    assert(!d.soil.middle_raw && d.system.sensor_degraded);
    assert(encode() == SerializeStatus::Encoded);
    assert(std::strstr(json, "\"middle_raw\":null"));
    assert(std::strstr(json, "\"risk\":{\"sensor_score\":null,\"level\":null,\"reason_mask\":null}"));
    if (argc > 1) std::puts(json);
    const auto expired = comm::make_draft(input, 2000000);
    assert(!expired.imu[0].valid && !expired.imu[0].ax && !expired.soil.top_raw);
    char tiny[2]{'x','x'};
    assert(serializer.encode(d, tiny, sizeof(tiny)).status == SerializeStatus::BufferTooSmall && tiny[0] == 0);
    d.identity.reset(); assert(encode() == SerializeStatus::InvalidDraft);
    d.identity = a; d.identity->seq = protocol::json_safe_integer_max + 1;
    assert(encode() == SerializeStatus::InvalidDraft);
    d.identity = a; d.imu[0].ax = std::numeric_limits<float>::quiet_NaN();
    assert(encode() == SerializeStatus::InvalidDraft);
    d.imu[0].ax = 0; d.imu[0].valid = false;
    assert(encode() == SerializeStatus::InvalidDraft);
    d.imu[0].valid = true; d.time_synced = true;
    assert(encode() == SerializeStatus::InvalidDraft);
    d.time_synced = false; d.schema_name = "wrong";
    assert(encode() == SerializeStatus::InvalidDraft);
    d.schema_name = protocol::schema; d.risk.level = protocol::RiskLevel::Normal;
    assert(encode() == SerializeStatus::InvalidDraft);
    d.risk.level.reset(); d.site_id = "test\"\\\n";
    assert(encode() == SerializeStatus::Encoded);
    assert(std::strstr(json, "test\\\"\\\\\\u000a"));
    assert(comm::topic_segment("SITE-LAB") && !comm::topic_segment("a/#") && !comm::topic_segment(""));
}
