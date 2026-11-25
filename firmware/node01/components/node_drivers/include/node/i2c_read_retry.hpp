#pragma once
#include "esp_err.h"
#include <cstddef>
#include <cstdint>

namespace node::drivers::retry {
// Only registers whose re-read does not trigger/consume a new acquisition.
// In particular, do NOT replay IMU INT_STATUS (read-to-clear), IMU sample
// bursts (freshness/side effects are not proven), or ANY write/reset/start.
constexpr bool reread_safe(std::uint8_t address, std::uint8_t reg, std::size_t size) {
    if (address == 0x48) return size == 2 && (reg == 0x00 || reg == 0x01);
    return (address == 0x68 || address == 0x69) && size == 1 && (reg == 0x75 || reg == 0x76);
}
struct Attempt {
    esp_err_t error;
    bool sdk_entered;
};
struct Result {
    Attempt first, final;
    bool attempted = false;
};
// Run owns the existing application mutex ONLY for its synchronous SDK call.
// Once Run returns, it has released that mutex. Wait must block/yield outside
// it. Re-entry uses the same live device handle and explicit register pointer.
// There is no nested retry, handle replacement or explicit bus reset here.
template<class Run, class Wait, class Clear>
Result read_once_then_maybe_retry(std::uint8_t address, std::uint8_t reg,
        std::size_t size, Run run, Wait wait, Clear clear) {
    const auto first = run();
    Result result{first, first, false};
    if (!first.sdk_entered || !reread_safe(address, reg, size) ||
        (first.error != ESP_ERR_INVALID_STATE && first.error != ESP_ERR_TIMEOUT)) return result;
    // Failed/partial SDK bytes never survive into the second observation.
    clear();
    wait();
    result.attempted = true;
    result.final = run();
    if (result.final.error != ESP_OK) clear();
    return result;
}
} // namespace node::drivers::retry
