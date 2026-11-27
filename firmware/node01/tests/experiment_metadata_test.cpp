#include "node/experiment_metadata.hpp"
#include <cassert>
#include <cerrno>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <string>
#include <vector>
#include <unistd.h>

namespace fault {
enum class Kind { None, Write, Partial, Flush, Sync, Close, Reopen, Read, Corrupt, Truncate, Extra, VerifyClose };
Kind next=Kind::None;unsigned fired=0,closes=0;
bool take(Kind k) { if(next!=k)return false;next=Kind::None;++fired;errno=EIO;return true; }
}
extern "C" {
std::size_t __real_fwrite(const void*,std::size_t,std::size_t,FILE*);
std::size_t __wrap_fwrite(const void* p,std::size_t n,std::size_t count,FILE* f) {
    if(f!=stdout && f!=stderr && fault::take(fault::Kind::Write))return 0;
    if(f!=stdout && f!=stderr && fault::take(fault::Kind::Partial))return __real_fwrite(p,n,count/2,f);
    return __real_fwrite(p,n,count,f);
}
int __real_fflush(FILE*);
int __wrap_fflush(FILE* f) {if(f!=stdout && f!=stderr && fault::take(fault::Kind::Flush))return EOF;return __real_fflush(f);}
int __real_fclose(FILE*);
int __wrap_fclose(FILE* f) {
    const int r=__real_fclose(f);++fault::closes;
    if(fault::take(fault::Kind::Close) || (fault::closes==2 && fault::take(fault::Kind::VerifyClose)))return EOF;
    return r;
}
FILE* __real_fopen(const char*,const char*);
FILE* __wrap_fopen(const char* name,const char* mode) {
    if(std::strcmp(mode,"rb")==0 && fault::take(fault::Kind::Reopen))return nullptr;
    return __real_fopen(name,mode);
}
std::size_t __real_fread(void*,std::size_t,std::size_t,FILE*);
std::size_t __wrap_fread(void* data,std::size_t size,std::size_t count,FILE* f) {
    if(fault::take(fault::Kind::Read))return 0;
    const auto n=__real_fread(data,size,count,f);
    if(n && fault::take(fault::Kind::Corrupt))static_cast<char*>(data)[0]^=1;
    if(n && fault::take(fault::Kind::Truncate))return n/2;
    if(!n && fault::take(fault::Kind::Extra)) {static_cast<char*>(data)[0]='X';return 1;}
    return n;
}
#ifdef _WIN32
using Commit=int(*)(int);extern Commit __real___imp__commit;
int wrapped_commit(int fd){if(fault::take(fault::Kind::Sync))return -1;return __real___imp__commit(fd);}
Commit __wrap___imp__commit=wrapped_commit;
#else
int __real_fsync(int);
int __wrap_fsync(int fd){if(fault::take(fault::Kind::Sync))return -1;return __real_fsync(fd);}
#endif
}
std::string bytes(const std::string& p){std::ifstream f(p,std::ios::binary);return {std::istreambuf_iterator<char>(f),{}};}
int main(int argc,char**argv) {
    assert(argc==2);const std::string root=argv[1];assert(std::filesystem::create_directory(root));
    node::storage::ExperimentRecord r;r.source="TEST_ONLY_SYNTHETIC";r.experiment_id="TEST_ONLY_SESSION";
    r.elf_sha256="0000000000000000000000000000000000000000000000000000000000000000";
    r.requested_seconds=180;r.start_us=100;r.stop_us=2000000;r.last_producer_ack_us=2000500;r.stop_reason="USER_STOP";
    const std::string path=root+"/N0000001.CSV";r.csv_path=path.c_str();
    node::storage::ExperimentMetadata metadata;assert(metadata.save(r,false));
    const auto begin=bytes(metadata.path());assert(begin.find("TEST_ONLY_SYNTHETIC")!=std::string::npos);
    assert(!metadata.save(r,false) && metadata.last_error()==EEXIST && bytes(root+"/N0000001.BEG")==begin);
    r.csv_verified=true;r.storage_clean=true;r.produced=r.enqueued=r.dequeued=r.accepted=r.verified_rows=400;
    assert(metadata.save(r,true));const auto end=bytes(metadata.path());
    assert(end.find("\"actual_duration_us\":1999900")!=std::string::npos && end.find("\"csv_verified\":true")!=std::string::npos);
    assert(!metadata.save(r,true) && metadata.last_error()==EEXIST && bytes(root+"/N0000001.END")==end);
    unsigned index=2,cases=0;
    for(auto kind:{fault::Kind::Write,fault::Kind::Partial,fault::Kind::Flush,fault::Kind::Sync,fault::Kind::Close,fault::Kind::Reopen,fault::Kind::Read,fault::Kind::Corrupt,fault::Kind::Truncate,fault::Kind::Extra,fault::Kind::VerifyClose}) {
        char name[24];std::snprintf(name,sizeof(name),"/N%07u.CSV",index++);const auto p=root+name;r.csv_path=p.c_str();
        fault::next=kind;fault::fired=fault::closes=0;
        assert(!metadata.save(r,true) && metadata.last_error()!=0);
        assert(fault::next==fault::Kind::None && fault::fired==1);++cases;
        const auto original=bytes(metadata.path());
        assert(!metadata.save(r,true) && metadata.last_error()==EEXIST && bytes(metadata.path())==original);
    }
    const auto missing=root+"/missing/N0000001.CSV";r.csv_path=missing.c_str();assert(!metadata.save(r,true));++cases;
    r.csv_path=path.c_str();r.experiment_id="UNSAFE\"ID";assert(!metadata.save(r,true) && metadata.last_error()==EINVAL);
    r.experiment_id="TEST_ONLY";r.requested_seconds=301;assert(!metadata.save(r,true));
    r.requested_seconds=30;r.start_us=r.stop_us=0;r.stop_reason="NONE";r.csv_verified=r.storage_clean=false;
    const std::string intent=root+"/intent.CSV";r.csv_path=intent.c_str();assert(metadata.save(r,false));
    assert(bytes(metadata.path()).find("START_INTENT")!=std::string::npos && bytes(metadata.path()).find("\"start_us\":0")!=std::string::npos);
    std::printf("HOST_EXPERIMENT_METADATA_TEST_PASS injected_failures=%u (TEST_ONLY real CRT sidecar/CRC/bytes/EOF/exclusive-create; SD HARDWARE_NOT_RUN)\n",cases);
}
