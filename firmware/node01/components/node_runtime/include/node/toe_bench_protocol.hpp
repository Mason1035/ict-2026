#pragma once
#include <array>
#include <cstddef>
#include <cstring>
#include <string_view>

namespace node::runtime::toe_bench {
#if defined(CONFIG_NODE01_TOE_BENCH_QUEUE_SD)
inline constexpr std::string_view command_prefix = "TOE QUEUE DIAG START ";
inline constexpr std::string_view start512_prefix = "TOE QUEUE DIAG START512 ";
inline constexpr std::string_view readab_prefix = "TOE QUEUE DIAG READAB ";
inline constexpr std::string_view wrstress_prefix = "TOE QUEUE DIAG WRSTRESS ";
inline constexpr std::size_t max_command_bytes = wrstress_prefix.size() + 16 + 2;
static_assert(start512_prefix.size() + 16 <= max_command_bytes);
static_assert(readab_prefix.size() + 16 + 2 <= max_command_bytes);
#elif defined(CONFIG_NODE01_TOE_BENCH_SD)
inline constexpr std::string_view command_prefix = "TOE SD DIAG START ";
inline constexpr std::size_t max_command_bytes = command_prefix.size() + 16;
#elif defined(CONFIG_NODE01_TOE_BENCH_ADS)
inline constexpr std::string_view command_prefix = "TOE ADS DIAG START ";
inline constexpr std::size_t max_command_bytes = command_prefix.size() + 16;
#else
inline constexpr std::string_view command_prefix = "TOE DIAG START ";
inline constexpr std::size_t max_command_bytes = command_prefix.size() + 16;
#endif
#ifdef CONFIG_NODE01_CAPTURE_SECONDS
inline constexpr unsigned window_seconds = CONFIG_NODE01_CAPTURE_SECONDS;
#else
inline constexpr unsigned window_seconds = 10;
#endif
inline constexpr unsigned prearm_ms = 250;
#ifdef CONFIG_NODE01_REAL_TEST_ONLY
inline constexpr std::string_view publish_prefix = "TOE QUEUE DIAG PUB ";
static_assert(publish_prefix.size() + 2 <= command_prefix.size());
#endif

class Command {
public:
    explicit Command(std::string_view nonce) : nonce_(nonce) {}
    bool feed(char c) {
        if (used_) return false;
        if (c == '\r' || c == '\n') {
            bool accept = matches(command_prefix, 0);
#ifdef CONFIG_NODE01_TOE_BENCH_QUEUE_SD
            const bool accept_512 = matches(start512_prefix, 0);
            if (accept_512) {
                accept = true;
                single_sector_ = true;
            }
            unsigned readab_hit = 0;
            if (!accept && matches(readab_prefix, 2) && buffer_[size_ - 2] == ' ') {
                const auto digit = buffer_[size_ - 1];
                if (digit == '1' || digit == '2') {
                    readab_hit = static_cast<unsigned>(digit - '0');
                    readab_order_ = readab_hit;
                }
            }
            unsigned wrstress_hit = 0;
            if (!accept && !readab_hit && matches(wrstress_prefix, 2) && buffer_[size_ - 2] == ' ') {
                const auto digit = buffer_[size_ - 1];
                if (digit >= '1' && digit <= '5') {
                    wrstress_hit = static_cast<unsigned>(digit - '0');
                    wrstress_cycles_ = wrstress_hit;
                }
            }
#endif
#ifdef CONFIG_NODE01_REAL_TEST_ONLY
            if (matches(publish_prefix, 2) && buffer_[size_ - 2] == ' ') {
                const auto digit = buffer_[size_ - 1];
                if (digit >= '1' && digit <= '3') publish_limit_ = static_cast<unsigned>(digit - '0');
            }
#endif
            size_ = 0;
            discard_ = false;
#ifdef CONFIG_NODE01_TOE_BENCH_QUEUE_SD
            used_ = accept || (readab_hit != 0) || (wrstress_hit != 0);
#else
            used_ = accept;
#endif
            return accept;
        }
        if (size_ == buffer_.size()) discard_ = true;
        if (!discard_) buffer_[size_++] = c;
        return false;
    }
#ifdef CONFIG_NODE01_TOE_BENCH_QUEUE_SD
    unsigned take_readab_order() {
        const auto order = readab_order_;
        readab_order_ = 0;
        return order;
    }
    unsigned take_wrstress_cycles() {
        const auto cycles = wrstress_cycles_;
        wrstress_cycles_ = 0;
        return cycles;
    }
    bool start_single_sector() const { return single_sector_; }
#endif
#ifdef CONFIG_NODE01_REAL_TEST_ONLY
    unsigned take_publish_limit() {
        const auto limit = publish_limit_;
        publish_limit_ = 0;
        return limit;
    }
#endif
private:
    bool matches(std::string_view prefix, std::size_t suffix) const {
        return !discard_ && nonce_.size() == 16 && size_ == prefix.size() + 16 + suffix &&
            std::memcmp(buffer_.data(), prefix.data(), prefix.size()) == 0 &&
            std::memcmp(buffer_.data() + prefix.size(), nonce_.data(), 16) == 0;
    }
#ifdef CONFIG_NODE01_TOE_BENCH_QUEUE_SD
    unsigned readab_order_ = 0;
    unsigned wrstress_cycles_ = 0;
    bool single_sector_ = false;
#endif
#ifdef CONFIG_NODE01_REAL_TEST_ONLY
    unsigned publish_limit_ = 0;
#endif
    std::string_view nonce_; // immutable boot-local buffer
    std::array<char, max_command_bytes> buffer_{};
    std::size_t size_ = 0;
    bool discard_ = false, used_ = false;
};
} // namespace node::runtime::toe_bench

