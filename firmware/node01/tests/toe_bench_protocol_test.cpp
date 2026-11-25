#include "node/toe_bench_protocol.hpp"
#include <cassert>
#include <cstdio>
#include <string>
#include <string_view>

namespace {
using node::runtime::toe_bench::Command;

bool feed_line(Command& parser, std::string_view line, char eol = '\n') {
    for (char ch : line) assert(!parser.feed(ch));
    return parser.feed(eol);
}
} // namespace

int main() {
    constexpr std::string_view nonce = "0123456789abcdef";
    constexpr std::string_view wrong_nonce = "0123456789abcdee";

    // 1) PUB commands can run before capture starts without locking used_.
    {
        Command cmd(nonce);
        assert(!feed_line(cmd, "TOE QUEUE DIAG PUB 0123456789abcdef 2"));
        assert(cmd.take_publish_limit() == 2);
        assert(cmd.take_publish_limit() == 0);
        assert(cmd.take_readab_order() == 0);

        // Wrong nonce and invalid PUB digit are ignored cleanly.
        assert(!feed_line(cmd, std::string("TOE QUEUE DIAG PUB ") + std::string(wrong_nonce) + " 1"));
        assert(cmd.take_publish_limit() == 0);
        assert(!feed_line(cmd, "TOE QUEUE DIAG PUB 0123456789abcdef 4"));
        assert(cmd.take_publish_limit() == 0);

        // Oversized line discards safely and allows subsequent valid START.
        assert(!feed_line(cmd, std::string(200, 'X')));
        assert(!feed_line(cmd, std::string("TOE QUEUE DIAG START ") + std::string(wrong_nonce)));
        assert(feed_line(cmd, "TOE QUEUE DIAG START 0123456789abcdef", '\r'));
        assert(!cmd.start_single_sector());
        assert(cmd.take_readab_order() == 0);

        // Single-use latch ignores subsequent START / START512 / READAB / PUB commands.
        assert(!feed_line(cmd, "TOE QUEUE DIAG START512 0123456789abcdef"));
        assert(!feed_line(cmd, "TOE QUEUE DIAG READAB 0123456789abcdef 1"));
        assert(!feed_line(cmd, "TOE QUEUE DIAG PUB 0123456789abcdef 3"));
        assert(cmd.take_readab_order() == 0);
        assert(cmd.take_publish_limit() == 0);
    }

    // 2) START512 sets single-sector verification mode and locks used_.
    {
        Command cmd(nonce);
        assert(feed_line(cmd, "TOE QUEUE DIAG START512 0123456789abcdef"));
        assert(cmd.start_single_sector());
        assert(cmd.take_readab_order() == 0);
        assert(!feed_line(cmd, "TOE QUEUE DIAG START 0123456789abcdef"));
    }

    // 3) READAB rejects invalid order values (0 / 3) without latching used_,
    //    accepts order 1 or 2 once without starting 120s capture, then latches used_.
    {
        Command cmd1(nonce);
        assert(!feed_line(cmd1, "TOE QUEUE DIAG READAB 0123456789abcdef 0"));
        assert(!feed_line(cmd1, "TOE QUEUE DIAG READAB 0123456789abcdef 3"));
        assert(cmd1.take_readab_order() == 0);
        assert(!feed_line(cmd1, "TOE QUEUE DIAG READAB 0123456789abcdef 1"));
        assert(cmd1.take_readab_order() == 1);
        assert(cmd1.take_readab_order() == 0);
        assert(!cmd1.start_single_sector());
        assert(!feed_line(cmd1, "TOE QUEUE DIAG START 0123456789abcdef"));
        assert(!feed_line(cmd1, "TOE QUEUE DIAG READAB 0123456789abcdef 2"));
        assert(cmd1.take_readab_order() == 0);

        Command cmd2(nonce);
        assert(!feed_line(cmd2, "TOE QUEUE DIAG READAB 0123456789abcdef 2", '\r'));
        assert(cmd2.take_readab_order() == 2);
        assert(cmd2.take_readab_order() == 0);
    }

    // 4) WRSTRESS accepts 1..5 cycles once, rejects 0 and 6 without latching used_, then latches used_.
    {
        Command cmd1(nonce);
        assert(!feed_line(cmd1, "TOE QUEUE DIAG WRSTRESS 0123456789abcdef 0"));
        assert(!feed_line(cmd1, "TOE QUEUE DIAG WRSTRESS 0123456789abcdef 6"));
        assert(cmd1.take_wrstress_cycles() == 0);
        assert(!feed_line(cmd1, "TOE QUEUE DIAG WRSTRESS 0123456789abcdef 1"));
        assert(cmd1.take_wrstress_cycles() == 1);
        assert(cmd1.take_wrstress_cycles() == 0);
        assert(!feed_line(cmd1, "TOE QUEUE DIAG START 0123456789abcdef"));
        assert(!feed_line(cmd1, "TOE QUEUE DIAG WRSTRESS 0123456789abcdef 5"));
        assert(cmd1.take_wrstress_cycles() == 0);

        Command cmd2(nonce);
        assert(!feed_line(cmd2, "TOE QUEUE DIAG WRSTRESS 0123456789abcdef 5", '\r'));
        assert(cmd2.take_wrstress_cycles() == 5);
        assert(cmd2.take_wrstress_cycles() == 0);
    }

    std::puts("HOST_TOE_BENCH_PROTOCOL_TEST_PASS (TEST_ONLY UART command parser; hardware UART not run)");
    return 0;
}
