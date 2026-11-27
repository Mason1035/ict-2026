#include "node/experiment_control.hpp"
#include "node/acquisition_policy.hpp"
#include <cassert>
#include <cstdio>
#include <string>
using namespace node::runtime;
experiment::Request parse(const std::string& text) {
    experiment::Parser p; experiment::Request last;
    for (unsigned char c:text) { const auto r=p.feed(c,100);if(r.command!=experiment::Command::None)last=r; }
    return last;
}
int main() {
    using namespace experiment;
    for (unsigned bits=0;bits<8;++bits) {
        Session s; assert(!s.request_start(120));
        assert(s.ready(bits&1,bits&2,bits&4)==(bits==7));
        assert(s.observation().state==(bits==7 ? State::Ready : State::Initializing));
    }
    for (unsigned seconds:{30U,120U,180U,300U}) {
        const auto request=parse(" \tEXP START "+std::to_string(seconds)+" \r\n");
        assert(request.command==Command::Start && request.seconds==seconds);
        Session s;policy::CaptureWindow window(120);assert(s.ready(true,true,true));
        assert(!s.stop(10,Reason::UserStop));assert(s.request_start(seconds));
        assert(!s.request_start(30) && !s.stop(10,Reason::UserStop));
        assert(window.configure_before_begin(seconds));assert(s.begin(100));window.begin(100);
        assert(!s.begin(1000) && !window.configure_before_begin(30));
        const auto due=100+seconds*1000000ULL;
        assert(!window.poll(due-1) && window.poll(due));assert(s.stop(due,Reason::TimeLimit));
        assert(!s.stop(due+100,Reason::UserStop) && !window.request_stop(due+100));
        assert(!s.finalizing(false,true,false) && !s.finalizing(true,false,false) && !s.finalizing(true,true,true));
        assert(s.finalizing(true,true,false) && !s.finalizing(true,true,false));assert(s.complete(true,true));
        assert(s.observation().state==State::Finalized && s.observation().stopped_by==Reason::TimeLimit);
        assert(!s.request_start(120) && !s.complete(true,true) && !s.stop(due+200,Reason::UserStop));
    }
    for (const auto* input:{"EXP START 29\n","EXP START 301\n","EXP START 0\n","EXP START -30\n","EXP START +30\n","EXP START 1e2\n","EXP START 99999999999999\n","EXP START 30 x\n","EXP STATUS START 120\n","EXP STOP START 30\n","exp START 30\n","START 30\n","EXP MARK RAIN_START\n"})
        assert(parse(input).command==Command::Invalid);
    assert(parse("\r\n\t \n").command==Command::None);
    assert(parse("EXP STATUS\r\n").command==Command::Status);
    assert(parse("EXP START\n").command==Command::Start && parse("EXP START\n").seconds==120);
    assert(parse("EXP HELP\n").command==Command::Help && parse("EXP STOP\n").command==Command::Stop);
    assert(parse(std::string(80,'X')+"EXP START 30\n").command==Command::TooLong);
    assert(parse(std::string("EXP START ")+char(0)+"30\n").command==Command::Invalid);
    Parser partial;
    for(auto c:std::string("EXP STA"))assert(partial.feed(c,100).command==Command::None);
    assert(partial.expire(5000100).command==Command::Incomplete);
    for(auto c:std::string("RT 120\n"))assert(partial.feed(c,6000000).command==Command::None);
    Request complete;for(auto c:std::string("EXP START 30\n")){auto r=partial.feed(c,7000000);if(r.command!=Command::None)complete=r;}
    assert(complete.command==Command::Start);
    for(bool csv:{false,true})for(bool metadata:{false,true}) {
        Session s;assert(s.ready(true,true,true) && s.request_start(180) && s.begin(100));
        assert(!s.complete(true,true));assert(s.stop(123456,Reason::UserStop));
        assert(s.observation().stop_us==123456 && s.observation().seconds==180);
        assert(s.finalizing(true,true,false) && s.complete(csv,metadata));
        assert(s.observation().state==(csv&&metadata ? State::Finalized:State::Failed));
    }
    // Separate transport parsers never splice fragments into START.
    Parser uart,usb;for(auto c:std::string("EXP STA"))uart.feed(c,1);
    Request usb_result;for(auto c:std::string("RT 30\n")) {auto r=usb.feed(c,2);if(r.command!=Command::None)usb_result=r;}
    assert(usb_result.command==Command::Invalid);
    std::puts("HOST_EXPERIMENT_CONTROL_TEST_PASS (TEST_ONLY parser/range/session/deadline/stop/inflight gates/metadata status; UART/RTOS HARDWARE_NOT_RUN)");
}
