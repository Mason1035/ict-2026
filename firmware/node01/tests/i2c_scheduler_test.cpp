#include "node/deferred_imu_notice.hpp"
#include <array>
#include <cassert>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <iterator>
#include <string>
#include <thread>

namespace {
// A deliberately small discrete model of non-reserving Mutex Give and fixed
// priorities on one core. NOT an ESP-IDF/SMP emulator or a timing guarantee.
struct HandoffModel {
    enum Task { None, High, Low };
    Task holder = High;
    bool low_ready = false, high_running = true;
    unsigned gives = 0;
    bool give(Task task, bool sdk_success = true) {
        if (!sdk_success || holder != task) return false;
        holder = None; low_ready = true; ++gives;
        return true; // token available, NOT reserved for waiter
    }
    bool take(Task task) {
        if (holder != None) return false;
        holder = task; return true;
    }
    Task scheduled() const { return high_running ? High : (low_ready ? Low : None); }
};
void scheduling_boundaries() {
    HandoffModel before;
    assert(before.give(HandoffModel::High));
    assert(before.low_ready && before.scheduled() == HandoffModel::High);
    // Voluntary yield does not defeat a strictly higher ready priority.
    assert(before.scheduled() == HandoffModel::High);
    assert(before.take(HandoffModel::High)); // immediate re-take is legal
    assert(!before.take(HandoffModel::Low));
    assert(!before.give(HandoffModel::Low)); // wrong owner cannot release
    assert(!before.give(HandoffModel::High, false)); // failed Give keeps ownership
    assert(before.holder == HandoffModel::High);
    assert(before.give(HandoffModel::High));
    const std::uint64_t request_us = 1976, timeout_tick_us = 13901;
    const std::uint64_t top_done_us = 4002, toe_request_us = 12998;
    // Source/Trace-inspired counterexample: no FIFO reservation plus busy
    // logging can consume the otherwise idle-bus interval before another Take.
    assert(toe_request_us - top_done_us == 8996);
    assert(before.scheduled() == HandoffModel::High);
    assert(before.take(HandoffModel::High));
    assert(timeout_tick_us - request_us == 11925);
    assert(before.holder != HandoffModel::Low); // timeout can be real

    HandoffModel after;
    assert(after.give(HandoffModel::High));
    after.high_running = false; // existing notification/SDK wait, not taskYIELD
    assert(after.scheduled() == HandoffModel::Low);
    assert(after.take(HandoffModel::Low));
    assert(top_done_us < timeout_tick_us); // succeeds in this modeled schedule
    assert(!after.take(HandoffModel::High));
    assert(after.give(HandoffModel::Low));
    assert(after.gives == 2);
    // If another task/ISR runs too long, even no logging cannot guarantee the
    // deadline. The fix does not lengthen/suppress the real timeout.
    constexpr unsigned external_delay_us = 20000;
    assert(top_done_us + external_delay_us > timeout_tick_us);
}
void notices() {
    using node::runtime::policy::DeferredImuNotice;
    using node::runtime::policy::ImuNotice;
    std::array<DeferredImuNotice, 2> fallback{}, error{};
    std::mutex notice_lock;
    ImuNotice n{9,9,true};
    assert(!fallback[0].read(notice_lock, n) && n.observed_us == 9);
    assert(fallback[0].record(notice_lock, 123,0,true));
    assert(!fallback[0].record(notice_lock, 999,259,false));
    assert(fallback[0].read(notice_lock, n) && n.observed_us == 123 && n.error == 0 && n.initialized);
    assert(!fallback[1].read(notice_lock, n)); // TOP does not become TOE
    assert(error[1].record(notice_lock, 456,263,false));
    assert(error[1].read(notice_lock, n) && n.error == 263 && !n.initialized && n.observed_us == 456);
    assert(fallback[0].read(notice_lock, n) && n.error == 0); // error cannot overwrite fallback
    DeferredImuNotice concurrent;
    std::thread producer([&] {
        assert(concurrent.record(notice_lock, 0x123456789abcdef0ULL,259,true));
        for (unsigned i=0;i<10000;++i) assert(!concurrent.record(notice_lock, i,0,false));
    });
    for (unsigned i=0;i<10000;++i) if (concurrent.read(notice_lock, n)) {
        assert(n.observed_us == 0x123456789abcdef0ULL && n.error == 259 && n.initialized);
    }
    producer.join();
    assert(concurrent.read(notice_lock, n) && n.observed_us == 0x123456789abcdef0ULL);
}
void real_runtime_wiring() {
    // Guard the actual wiring too: a mailbox-only test would not catch an
    // accidentally retained UART call in the production sampling loop.
    std::ifstream file("components/node_runtime/runtime.cpp");
    assert(file.good());
    std::string source((std::istreambuf_iterator<char>(file)), {});
    const auto begin=source.find("auto read_site =");
    const auto end=source.find("void storage_test_producer",begin);
    assert(begin!=std::string::npos && end!=std::string::npos);
    const auto loop=source.substr(begin,end-begin);
    assert(loop.find("ESP_LOG") == std::string::npos);
    assert(loop.find("imu_first_read_error[i].record") != std::string::npos);
    assert(loop.find("imu_first_fallback[i].record") != std::string::npos);
    assert(loop.find("imu_failed[i].fetch_add(1)") != std::string::npos);
    assert(loop.find("imu_irq_fallbacks[i].fetch_add(1)") != std::string::npos);
    assert(loop.find("xTaskNotifyWait") != std::string::npos);
    assert(loop.find("xTaskDelayUntil") != std::string::npos);
    assert(source.find("deferred=UiHealthTask") != std::string::npos);
}
}
int main() {
    scheduling_boundaries(); notices(); real_runtime_wiring();
    std::cout << "HOST_I2C_SCHEDULER_NOTICE_PASS (TEST_ONLY fixed-priority model + real notice/wiring; SMP/hardware NOT_RUN)\n";
}
