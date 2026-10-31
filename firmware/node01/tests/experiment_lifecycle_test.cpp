#include "node/experiment_control.hpp"
#include "node/acquisition_policy.hpp"
#include "node/storage_recovery.hpp"
#include "node/experiment_metadata.hpp"
#include <cassert>
#include <cstdio>
#include <deque>
#include <filesystem>
#include <string>

using namespace node;
struct Files final:storage::Backend {
    storage::DiagnosticLog log;storage::ClosedSegment closed{};std::string root;unsigned closes=0;
    explicit Files(std::string p):root(std::move(p)){}
    bool recover()override{return log.open_new(root.c_str(),"# TEST_ONLY SYNTHETIC lifecycle input, not hardware\n");}
    bool open_next()override{return recover();}
    bool append(const sampling::AcquisitionRecord&r)override{return log.append(r);}
    bool flush()override{return log.flush();}
    bool close_and_verify()override{++closes;return log.close_for_verification(closed)&&storage::DiagnosticLog::verify_file(closed.path,closed.bytes,closed.crc32,closed.rows);}
    void abandon()override{log.abandon();}
};
void run(const std::string& root,unsigned tail_ms,unsigned backlog,bool user_stop) {
    assert(std::filesystem::create_directory(root));
    using namespace runtime::experiment;Session s;runtime::policy::CaptureWindow window(120);
    Files backend(root);storage::RecoveryWriter writer(backend,256,0xffffffffU);std::deque<sampling::AcquisitionRecord> queue;
    assert(!s.request_start(30) && !window.observation().started && !std::filesystem::exists(root+"/N0000001.CSV"));
    writer.step(0);assert(writer.active() && backend.log.rows()==0); // reserved, no experiment rows
    assert(s.ready(true,true,true) && s.request_start(30));assert(window.configure_before_begin(30));assert(s.begin(1));window.begin(1);
    unsigned produced=0,enqueued=0,dequeued=0,drops=0;bool stopped=false,ack=false;std::uint64_t last_index=0;bool have_index=false;
    const auto produce=[&](std::uint64_t now){sampling::AcquisitionRecord r;r.kind=sampling::RecordKind::Soil;r.channel=0;r.acquisition_index=produced++;
        r.attempted_uptime_us=now;r.soil.acquired_uptime_us=now+1;r.soil.validity=sampling::Validity::Valid;r.soil.raw=1234;
        if(queue.size()==512)++drops;else{queue.push_back(r);++enqueued;}};
    for(unsigned i=0;i<backlog;++i)produce(1);
    for(std::uint64_t now=1000;now<35000000 && !writer.finished();now+=1000) {
        if(!stopped) {
            if((user_stop && now>=2000000) || window.poll(now)) {
                assert(s.stop(now,user_stop?Reason::UserStop:Reason::TimeLimit));window.request_stop(now);stopped=true;
                assert(!s.finalizing(false,false,false)); // in-flight sample and producers not acked
                produce(now-1); // one real-in-model in-flight completion, never an invented replacement
            } else if(now%10000==0) {produce(now);produce(now);if(now%500000==0){produce(now);produce(now);produce(now);}}
        } else if(!ack) {window.producer_done(3);ack=true;}
        if(now>=1000+tail_ms*1000ULL)for(unsigned quota=0;quota<8 && !writer.finished();++quota) {
            if(writer.can_take_record()&&!queue.empty()) {auto r=queue.front();queue.pop_front();++dequeued;
                if(have_index) { assert(r.acquisition_index>last_index); }
                last_index=r.acquisition_index;have_index=true;assert(writer.take_record(r));}
            if(ack && queue.empty() && !writer.has_pending()) {writer.request_finish();s.finalizing(true,true,false);}
            writer.step(now/1000);
        }
    }
    assert(writer.finished() && backend.closes==1 && queue.empty() && produced==enqueued+drops && dequeued==enqueued);
    assert(writer.stats().verified_rows==enqueued && !writer.stats().errors);
    storage::ExperimentRecord record;record.source="TEST_ONLY_SYNTHETIC";record.experiment_id="TEST_ONLY_LIFECYCLE";
    record.elf_sha256="0000000000000000000000000000000000000000000000000000000000000000";record.csv_path=backend.closed.path;
    const auto observation=s.observation();record.requested_seconds=observation.seconds;record.start_us=observation.start_us;record.stop_us=observation.stop_us;
    record.stop_reason=reason(observation.stopped_by);record.produced=produced;record.enqueued=enqueued;record.dequeued=dequeued;
    record.accepted=writer.stats().append_accepted;record.verified_rows=writer.stats().verified_rows;record.queue_drop=drops;
    record.csv_verified=true;record.csv_bytes=backend.closed.bytes;record.csv_crc=backend.closed.crc32;record.storage_clean=drops==0;
    storage::ExperimentMetadata metadata;assert(metadata.save(record,true));assert(s.complete(drops==0,true));
    assert(s.observation().state==(drops ? State::Failed:State::Finalized));
    assert(!s.complete(true,true) && !s.request_start(30));
    std::printf("EXPERIMENT_LIFECYCLE_CASE TEST_ONLY tail_ms=%u backlog=%u user_stop=%d produced=%u saved=%u drop=%u closes=%u state=%s\n",tail_ms,backlog,user_stop,produced,enqueued,drops,backend.closes,name(s.observation().state));
}
int main(int argc,char**argv) {
    assert(argc==2);const std::string root=argv[1];assert(std::filesystem::create_directory(root));
    for(unsigned ms:{0U,200U,500U,700U,1000U})run(root+"/T"+std::to_string(ms),ms,0,true);
    run(root+"/full",1000,500,true);run(root+"/auto",700,0,false);
    std::puts("HOST_EXPERIMENT_LIFECYCLE_TEST_PASS cases=7 (TEST_ONLY SYNTHETIC virtual delay/real writer+metadata/inflight/drain/single close/drop; not RTOS/hardware)");
}
