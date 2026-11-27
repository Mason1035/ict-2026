#pragma once
#include <cstdint>

namespace node::drivers {
// Runtime holds its IRQ spinlock around every access, including in the ISR.
// Pin installation is not evidence that this particular sensor is ready.
class ImuIrqGate {
public:
    void initialized(bool ready) { initialized_ = ready; armed_ = false; notified_ = false; }
    bool may_arm() const { return initialized_; }
    void arm_result(bool success) { armed_ = initialized_ && success; notified_ = false; }
    void stop() { armed_ = false; notified_ = false; }
    bool may_notify() const { return armed_; }
    // Raw GPIO callbacks are counted by Runtime before this decision. Coalesce
    // only Task Notifications: a noisy pin must not cause unbounded RTOS wakes.
    // The task resets this latch once per existing 10ms supervisory frame.
    void begin_service_frame() { notified_ = false; }
    bool claim_notification() {
        if (!armed_ || notified_) return false;
        notified_ = true; return true;
    }
    void begin_capture(std::uint32_t lifetime_edges) { baseline_ = lifetime_edges; capture_started_ = true; }
    std::uint32_t startup_edges() const { return baseline_; }
    std::uint32_t capture_edges(std::uint32_t lifetime_edges) const {
        return capture_started_ ? lifetime_edges - baseline_ : 0; // bounded uint32 counter wrap
    }
private:
    bool initialized_ = false, armed_ = false, notified_ = false;
    bool capture_started_ = false;
    std::uint32_t baseline_ = 0;
};
}
