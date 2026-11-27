#pragma once
#include <cstdint>
#include "esp_err.h"

namespace node::drivers::bench_bus {
struct Transaction {
    std::uint64_t request_us, sdk_begin_us, sdk_end_us, end_us;
    std::uint32_t lock_us;
    esp_err_t rc;
    std::uint8_t addr, reg;
    char op;
    bool sdk, retry;
    int config_word;
};
std::uint32_t lock_wait_us();
void observe(const Transaction&);
}
