#pragma once
#include <cstddef>
#include <cstdint>
#include <cstring>

namespace node::runtime::experiment {
inline constexpr unsigned minimum_seconds = 30, maximum_seconds = 300, default_seconds = 120;
enum class Command { None, Status, Help, Start, Stop, Invalid, TooLong, Incomplete };
struct Request { Command command = Command::None; unsigned seconds = 0; };
// ASCII only. No partial/overflow command can turn into a different command.
class Parser {
public:
    Request feed(unsigned char ch, std::uint64_t now) {
        if (ch == '\r' || ch == '\n') {
            Request result = timed_out_ ? Request{} : bad_ ? Request{overflow_ ? Command::TooLong : Command::Invalid, 0} : parse();
            clear(); return result;
        }
        if (timed_out_) return {};
        last_us_ = now;
        if (ch < 32 || ch > 126) { if (ch != '\t') bad_ = true; }
        if (size_ + 1 >= sizeof(line_)) { bad_ = overflow_ = true; return {}; }
        line_[size_++] = static_cast<char>(ch); line_[size_] = 0; return {};
    }
    Request expire(std::uint64_t now) {
        if (!timed_out_ && (size_ || bad_) && now >= last_us_ && now - last_us_ >= 5000000ULL) {
            timed_out_ = true; return {Command::Incomplete, 0}; // discard tail through newline
        }
        return {};
    }
private:
    void clear() { size_ = 0; line_[0] = 0; bad_ = overflow_ = timed_out_ = false; }
    Request parse() {
        const char* p = line_; auto space = [](char c) { return c == ' ' || c == '\t'; };
        while (space(*p)) ++p;
        if (!*p) return {};
        const auto token = [&](const char* word) {
            const auto n = std::strlen(word);
            if (std::strncmp(p, word, n) || (p[n] && !space(p[n]))) return false;
            p += n; while (space(*p)) ++p; return true;
        };
        if (!token("EXP")) return {Command::Invalid, 0};
        if (token("STATUS")) return {!*p ? Command::Status : Command::Invalid, 0};
        if (token("HELP")) return {!*p ? Command::Help : Command::Invalid, 0};
        if (token("STOP")) return {!*p ? Command::Stop : Command::Invalid, 0};
        if (!token("START")) return {Command::Invalid, 0};
        if (!*p) return {Command::Start, default_seconds}; // explicit START, never auto-start
        unsigned n = 0, digits = 0;
        while (*p >= '0' && *p <= '9') {
            if (++digits > 3) return {Command::Invalid, 0};
            n = n * 10 + static_cast<unsigned>(*p++ - '0');
        }
        while (space(*p)) ++p;
        return digits && !*p && n >= minimum_seconds && n <= maximum_seconds
            ? Request{Command::Start, n} : Request{Command::Invalid, 0};
    }
    char line_[48]{};
    unsigned size_ = 0;
    std::uint64_t last_us_ = 0;
    bool bad_ = false, overflow_ = false, timed_out_ = false;
};
enum class State { Initializing, Ready, StartPending, Capturing, Stopping, Finalizing, Finalized, Failed };
enum class Reason { None, TimeLimit, UserStop, MetadataFailure, InitFailure, FinalizeFailure };
inline const char* name(State s) {
    constexpr const char* names[]{"INITIALIZING","READY","START_PENDING","CAPTURING","STOPPING_PRODUCERS","DRAINING_CLOSING_VERIFYING","FINALIZED","FINALIZE_FAILED"};
    return names[static_cast<unsigned>(s)];
}
inline const char* reason(Reason r) {
    constexpr const char* names[]{"NONE","TIME_LIMIT","USER_STOP","METADATA_FAILURE","INIT_FAILURE","FINALIZE_FAILURE"};
    return names[static_cast<unsigned>(r)];
}
struct Observation {
    State state = State::Initializing;
    Reason stopped_by = Reason::None;
    unsigned seconds = 0;
    std::uint64_t start_us = 0, stop_us = 0;
};
// Runtime holds snapshot_lock; no I/O, task, reset, index allocation or heap here.
class Session {
public:
    bool ready(bool sensors_ready, bool storage_ready, bool console_ready) {
        if (value_.state != State::Initializing || !sensors_ready || !storage_ready || !console_ready) return false;
        value_.state = State::Ready; return true;
    }
    bool request_start(unsigned seconds) {
        if (value_.state != State::Ready || seconds < minimum_seconds || seconds > maximum_seconds) return false;
        value_.seconds = seconds; value_.state = State::StartPending; return true;
    }
    bool begin(std::uint64_t now) {
        if (value_.state != State::StartPending) return false;
        value_.start_us = now; value_.state = State::Capturing; return true;
    }
    bool stop(std::uint64_t now, Reason why) {
        if (value_.state != State::Capturing || why == Reason::None || now < value_.start_us) return false;
        value_.stop_us = now; value_.stopped_by = why; value_.state = State::Stopping; return true;
    }
    bool finalizing(bool producers_done, bool queue_empty, bool pending) {
        if (value_.state != State::Stopping || !producers_done || !queue_empty || pending) return false;
        value_.state = State::Finalizing; return true;
    }
    bool complete(bool csv_clean, bool metadata_verified) {
        if (value_.state != State::Finalizing) return false;
        value_.state = csv_clean && metadata_verified ? State::Finalized : State::Failed; return true;
    }
    void fail() { if (value_.state != State::Finalized) value_.state = State::Failed; }
    Observation observation() const { return value_; }
private: Observation value_{};
};
}
