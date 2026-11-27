#include "node/i2c_read_retry.hpp"
#include "node/i2c_diagnostics.hpp"
#include "node/runtime_policy.hpp"
#include "node/sensors.hpp"
#include <array>
#include <cassert>
#include <cstdio>
#include <cstring>
#include <mutex>
#include <thread>

// TEST_ONLY: production retry policy + real sensor state machine; simulated
// SDK/bus, no serial/network. These tests do not prove physical recovery/100Hz.
namespace {
using namespace node;
using namespace node::drivers;
struct Lock { void lock() {} void unlock() {} };
void policy_boundaries() {
    assert(retry::reread_safe(0x48,0,2)); assert(retry::reread_safe(0x48,1,2));
    for (auto a : {0x68,0x69}) {
        assert(retry::reread_safe(a,0x75,1)); assert(retry::reread_safe(a,0x76,1));
        assert(!retry::reread_safe(a,0x2d,1)); // destructive DRDY status
        assert(!retry::reread_safe(a,0x1f,12)); // freshness is not proven for replay
    }
    assert(!retry::reread_safe(0x48,1,1)); assert(!retry::reread_safe(0x48,3,2));
    assert(!retry::reread_safe(0x49,1,2));
    for (auto original : {ESP_OK,ESP_ERR_INVALID_ARG,ESP_ERR_INVALID_RESPONSE}) {
        unsigned calls=0,waits=0,clears=0;
        const auto r=retry::read_once_then_maybe_retry(0x48,1,2,
            [&]{++calls;return retry::Attempt{original,true};},[&]{++waits;},[&]{++clears;});
        assert(calls==1 && waits==0 && clears==0 && !r.attempted && r.final.error==original);
    }
    for (bool entered : {false,true}) for (auto reg : {0x2d,0x1f}) {
        unsigned calls=0,waits=0;
        const auto r=retry::read_once_then_maybe_retry(0x69,reg,reg==0x2d?1:12,
            [&]{++calls;return retry::Attempt{ESP_ERR_INVALID_STATE,entered};},[&]{++waits;},[]{});
        assert(calls==1 && waits==0 && !r.attempted && r.final.error==ESP_ERR_INVALID_STATE);
    }
    for (auto error : {ESP_ERR_INVALID_STATE,ESP_ERR_TIMEOUT}) {
        unsigned calls=0;
        const auto r=retry::read_once_then_maybe_retry(0x48,1,2,
            [&]{++calls;return retry::Attempt{error,false};},[]{assert(false);},[]{assert(false);});
        assert(calls==1 && !r.attempted); // outer lock/local failures never retried
    }
}
void one_retry_and_fresh_bytes() {
    for (auto original : {ESP_ERR_INVALID_STATE,ESP_ERR_TIMEOUT}) {
        for (auto final : {ESP_OK,ESP_ERR_INVALID_STATE,ESP_ERR_TIMEOUT,ESP_ERR_INVALID_ARG}) {
            unsigned calls=0,waits=0;std::array<unsigned char,2> bytes{0x12,0x34};
            const auto r=retry::read_once_then_maybe_retry(0x48,0,2,[&] {
                if (++calls==1) { bytes={0xde,0xad};return retry::Attempt{original,true}; }
                assert(bytes[0]==0 && bytes[1]==0);
                bytes={0x50,0x21}; return retry::Attempt{final,final!=ESP_ERR_INVALID_ARG};
            },[&]{++waits;},[&]{bytes={0,0};});
            assert(calls==2 && waits==1 && r.attempted);
            assert(r.first.error==original && r.final.error==final);
            if (final==ESP_OK) assert((bytes==std::array<unsigned char,2>{0x50,0x21}));
            else assert((bytes==std::array<unsigned char,2>{0,0}));
        }
    }
}
void mutex_released_before_wait() {
    std::mutex mutex;unsigned attempts=0;bool other_owner=false;
    const auto r=retry::read_once_then_maybe_retry(0x48,1,2,[&] {
        const auto e=runtime::policy::locked_transaction([&]{mutex.lock();return true;},
            [&]{mutex.unlock();},[&]{return ++attempts==1?ESP_ERR_INVALID_STATE:ESP_OK;},ESP_ERR_TIMEOUT);
        return retry::Attempt{e,true};
    },[&] {
        // A different task can own the same bus while the requester yields.
        std::thread contender([&]{std::lock_guard<std::mutex> guard(mutex);other_owner=true;});
        contender.join();
    },[]{});
    assert(r.final.error==ESP_OK && attempts==2 && other_owner);
}
void diagnostic_original_error_survives() {
    I2cDiagnosticRegistry<Lock> d({0x68,0x69,0x48});
    d.record(0x48,1,2,true,true,ESP_ERR_INVALID_STATE,8000,{0,1,1,1});
    d.record_retry(0x48,1,2,ESP_ERR_INVALID_STATE,true,ESP_OK,600);
    auto s=d.snapshot()[2];
    assert(s.transfers==1 && s.reads==1 && s.sdk_calls==2 && s.errors==1);
    assert(s.first_errors==1 && s.first_invalid_states==1 && s.invalid_states==1);
    assert(s.retry_attempts==1 && s.retry_recovered==1 && s.retry_failed==0 && s.retry_sdk_calls==1);
    assert(s.last_error==ESP_OK && s.last_failed_error==ESP_ERR_INVALID_STATE);
    assert(s.last_failed_lines.before_sda==0 && s.last_retry_original_error==ESP_ERR_INVALID_STATE);
    d.record(0x48,0,2,true,true,ESP_ERR_TIMEOUT,9000);
    d.record_retry(0x48,0,2,ESP_ERR_TIMEOUT,false,ESP_ERR_TIMEOUT,20000);
    s=d.snapshot()[2];
    assert(s.transfers==2 && s.sdk_calls==3 && s.errors==3 && s.first_errors==2);
    assert(s.retry_attempts==2 && s.retry_recovered==1 && s.retry_failed==1 && s.retry_sdk_calls==1);
    assert(s.timeouts==2 && s.local_errors==1 && s.last_failed_error==ESP_ERR_TIMEOUT);
    assert(d.snapshot()[0].errors==0 && d.snapshot()[1].errors==0);
}
class Bus final : public RegisterBus {
public:
    std::uint64_t clock=0,started=0;
    std::uint16_t config=0x4383;
    bool active=false,held=false,bad_config=false,force_busy=false;
    int inject_reg=-1;unsigned remaining_failures=0,sdk_calls=0,yields=0,writes=0;
    unsigned yield_us=10000;esp_err_t injected=ESP_ERR_INVALID_STATE;
    I2cDiagnosticRegistry<Lock> diagnostics{{0x68,0x69,0x48}};
    esp_err_t read(std::uint8_t address,std::uint8_t reg,std::uint8_t* out,std::size_t size) override {
        const auto r=retry::read_once_then_maybe_retry(address,reg,size,[&] {
            assert(!held);held=true;++sdk_calls;clock+=100;
            esp_err_t e=ESP_OK;
            if (reg==inject_reg && remaining_failures) {
                --remaining_failures;std::memset(out,0xa5,size);e=injected;
            } else {
                std::uint16_t value=reg==0?20620:static_cast<std::uint16_t>(config&0x7fff);
                if (reg==1 && !force_busy && (!active || clock-started>=8000)) value|=0x8000;
                if (reg==1 && bad_config) value^=0x1000;
                assert(size==2);out[0]=static_cast<std::uint8_t>(value>>8);out[1]=static_cast<std::uint8_t>(value);
            }
            held=false;return retry::Attempt{e,true};
        },[&]{assert(!held);++yields;clock+=yield_us;},[&]{std::memset(out,0,size);});
        diagnostics.record(address,reg,size,true,r.first.sdk_entered,r.first.error,100);
        if (r.attempted) diagnostics.record_retry(address,reg,size,r.first.error,r.final.sdk_entered,r.final.error,100);
        return r.final.error;
    }
    esp_err_t write(std::uint8_t,std::uint8_t reg,const std::uint8_t* p,std::size_t size) override {
        assert(reg==1 && size==2);++writes;config=static_cast<std::uint16_t>((p[0]<<8)|p[1]);
        active=(config&0x8000)!=0;started=clock;return ESP_OK;
    }
    void delay_ms(unsigned ms) override {assert(!held);clock+=ms*1000ULL;}
    std::uint64_t now_us() const override {return clock;}
};
void real_ads_state_machine_guards() {
    {
        Bus b;SoilAds1115 adc(b);assert(adc.initialize()==ESP_OK);
        b.inject_reg=1;b.remaining_failures=1;const auto before=b.writes;
        assert(adc.start_conversion(2)==PortStatus::Ready && b.writes==before+1);
        assert(b.config==0xe383 && b.yields==1); // only READ retried, OS start written once
        sampling::SoilSample s;b.delay_ms(8);assert(adc.try_read_conversion(s)==PortStatus::Ready);
        assert(s.validity==sampling::Validity::Valid && s.raw==20620);
        assert(b.diagnostics.snapshot()[2].first_errors==1);
    }
    {
        Bus b;SoilAds1115 adc(b);assert(adc.initialize()==ESP_OK);b.inject_reg=1;b.remaining_failures=2;
        const auto before=b.writes;assert(adc.start_conversion(0)==PortStatus::Error && b.writes==before);
        assert(adc.last_error()==ESP_ERR_INVALID_STATE && b.yields==1);
    }
    for (unsigned failures : {1U,2U}) {
        Bus b;SoilAds1115 adc(b);assert(adc.initialize()==ESP_OK);assert(adc.start_conversion(2)==PortStatus::Ready);
        b.delay_ms(8);b.inject_reg=0;b.remaining_failures=failures;
        sampling::SoilSample s;const auto result=adc.try_read_conversion(s);
        if (failures==1) assert(result==PortStatus::Ready && s.raw==20620 && s.validity==sampling::Validity::Valid);
        else assert(result==PortStatus::Error && !s.raw && s.validity==sampling::Validity::Error);
    }
    {
        Bus b;SoilAds1115 adc(b);assert(adc.initialize()==ESP_OK);assert(adc.start_conversion(2)==PortStatus::Ready);
        b.delay_ms(8);b.inject_reg=0;b.remaining_failures=1;b.yield_us=40000;
        sampling::SoilSample s;assert(adc.try_read_conversion(s)==PortStatus::Error);
        assert(adc.last_error()==ESP_ERR_TIMEOUT && !s.raw && s.validity==sampling::Validity::Error);
    }
    {
        Bus b;SoilAds1115 adc(b);assert(adc.initialize()==ESP_OK);assert(adc.start_conversion(1)==PortStatus::Ready);
        b.delay_ms(8);b.bad_config=true;sampling::SoilSample s;
        assert(adc.try_read_conversion(s)==PortStatus::Error && !s.raw);
        assert(adc.last_error()==ESP_ERR_INVALID_RESPONSE); // retry cannot bypass config match
    }
    {
        Bus b;SoilAds1115 adc(b);assert(adc.initialize()==ESP_OK);assert(adc.start_conversion(0)==PortStatus::Ready);
        sampling::SoilSample s;assert(adc.try_read_conversion(s)==PortStatus::Unavailable && !s.raw);
        b.delay_ms(8);b.force_busy=true;assert(adc.try_read_conversion(s)==PortStatus::Unavailable && !s.raw);
    }
}
}
int main() {
    policy_boundaries();one_retry_and_fresh_bytes();mutex_released_before_wait();
    diagnostic_original_error_survives();real_ads_state_machine_guards();
    std::puts("I2C_READ_RETRY_HOST_PASS: 5 groups; bounded/read-safe/RAII/original-errors/real-ADS guards; HARDWARE_NOT_RUN");
}
