#pragma once
#include <array>
#include <cstddef>
#include <cstdint>

namespace node::runtime::sd_bench {
constexpr std::size_t block_size=4096;
constexpr unsigned total_blocks=10;
using Block=std::array<std::uint8_t,block_size>;
constexpr std::uint8_t expected(std::uint32_t seed, unsigned block, std::size_t index) {
    std::uint32_t value=seed ^ (0x9e3779b9U*(block+1)) ^ static_cast<std::uint32_t>(index);
    value=(value ^ (value >> 16))*0x7feb352dU;
    value=(value ^ (value >> 15))*0x846ca68bU;
    return static_cast<std::uint8_t>(value ^ (value >> 16));
}
inline std::uint32_t add_crc(std::uint32_t state, const Block& block) {
    for (const auto byte : block) {
        state ^= byte;
        for (unsigned bit=0;bit<8;++bit) state=(state>>1)^(0xedb88320U & (0U-(state & 1U)));
    }
    return state;
}
}
