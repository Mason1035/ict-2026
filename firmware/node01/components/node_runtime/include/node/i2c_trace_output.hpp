#pragma once
#include "node/i2c_finite_trace.hpp"
#include <algorithm>
#include <array>

namespace node::runtime::lock_diagnostic {
enum class OutputKind { Begin, Task, Event, End };
struct OutputLine { OutputKind kind=OutputKind::End;unsigned task=0,bank=0;Event event{}; };

// HealthTask only. Recorder must be sealed; all sorting/reference checks and
// rendering occur OUTSIDE recorder/application locks. No copy of the recorder.
class TraceOutput {
public:
    static constexpr unsigned batch_lines=4;
    static constexpr std::uint64_t batch_us=20000;
    bool begin(const FiniteTrace& trace,unsigned task_count) {
        if(started_ || !trace.summary().sealed)return false;
        started_=true;trace_=&trace;summary_=trace.summary();tasks_=task_count;
        missing_=trace.missing_links();boundary_=trace.boundary_links();
        if(summary_.first_anomaly) {
            Event event{};
            for(unsigned bank=0;bank<2;++bank)for(std::size_t i=0;trace.get(bank,i,event);++i)
                refs_[count_++]={event.seq,static_cast<std::uint16_t>(i),static_cast<std::uint8_t>(bank)};
            std::sort(refs_.begin(),refs_.begin()+count_,[](const Ref& a,const Ref& b){return a.seq<b.seq;});
        }
        state_=0;return true;
    }
    bool pending() const {return started_ && state_!=4;}
    bool next(OutputLine& out) {
        if(!pending())return false;
        if(state_==0){out={};out.kind=OutputKind::Begin;state_=summary_.first_anomaly?1:3;return true;}
        if(state_==1 && task_<tasks_){out={};out.kind=OutputKind::Task;out.task=task_++;return true;}
        state_=state_==1?2:state_;
        if(state_==2 && cursor_<count_){const auto r=refs_[cursor_++];out={};out.kind=OutputKind::Event;out.bank=r.bank;
            trace_->get(r.bank,r.index,out.event);return true;}
        out={};out.kind=OutputKind::End;state_=4;return true;
    }
    // A slow/paused log call cannot be preempted by this budget. Check between
    // complete lines and always block in Runtime after a batch, even at EOF.
    template<class Emit,class Now> unsigned pump(Emit emit,Now now) {
        const auto start=now();unsigned n=0;
        for(;n<batch_lines;++n){if(n && now()-start>=batch_us)break;OutputLine line;
            if(!next(line))break;
            emit(line);}
        return n;
    }
    const Summary& summary() const {return summary_;}
    std::uint32_t missing() const {return missing_;}
    std::uint32_t boundary() const {return boundary_;}
    const char* integrity() const {
        if(summary_.trace_overflow || missing_>boundary_ || summary_.active || summary_.incomplete_requests || summary_.ads_active || summary_.metadata_errors || summary_.id_exhausted)return "INCOMPLETE";
        if(!summary_.first_anomaly)return "SUMMARY_ONLY";
        return boundary_?"BOUNDARY_LIMITED":"RETAINED_CHAINS_COMPLETE";
    }
private:
    struct Ref {std::uint32_t seq;std::uint16_t index;std::uint8_t bank;};
    std::array<Ref,FiniteTrace::selected_capacity+FiniteTrace::history_capacity> refs_{};
    const FiniteTrace* trace_=nullptr;Summary summary_{};
    std::size_t count_=0,cursor_=0;unsigned tasks_=0,task_=0,state_=4;
    std::uint32_t missing_=0,boundary_=0;bool started_=false;
};
static_assert(sizeof(FiniteTrace)+sizeof(TraceOutput)<48496,
    "Recorder and dump index together must fit below former recorder RAM");
}
