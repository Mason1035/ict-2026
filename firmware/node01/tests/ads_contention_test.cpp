#include "node/sensors.hpp"
#include "node/runtime_policy.hpp"
#include "node/i2c_diagnostics.hpp"
#include <array>
#include <cassert>
#include <cstdio>
#include <mutex>

namespace {
using namespace node;
// Deterministic RegisterBus uses the actual ADS driver, counter registry and
// Take/Give ownership policy. No real RTOS scheduler, I2C SDK or ADC is run.
class Bus final:public drivers::RegisterBus {
public:
    std::uint64_t clock=0,conversion_start=0,next_imu=1000000;
    std::uint16_t config=0x4383;
    bool converting=false,held=false,fail_take=false;
    esp_err_t sdk_error=ESP_OK;
    unsigned request=0,sdk=0,gives=0,failed_gives=0;
    drivers::I2cDiagnosticRegistry<std::mutex> diagnostics{{0x68,0x69,0x48}};
    esp_err_t read(std::uint8_t address,std::uint8_t reg,std::uint8_t* out,std::size_t n) override {
        return execute(address,reg,n,true,[&] {
            if(n==2) {
                const auto value=reg==1?static_cast<std::uint16_t>((config&0x7fff)|((!converting||clock-conversion_start>=8000)?0x8000:0)):std::uint16_t(1234);
                out[0]=value>>8;out[1]=value&255;
            }
        });
    }
    esp_err_t write(std::uint8_t address,std::uint8_t reg,const std::uint8_t* bytes,std::size_t n) override {
        return execute(address,reg,n,false,[&] {
            if(address==0x48 && reg==1 && n==2) {
                config=static_cast<std::uint16_t>((bytes[0]<<8)|bytes[1]);
                converting=(config&0x8000)!=0;conversion_start=clock;
            }
        });
    }
    void advance_to(std::uint64_t target) {
        assert(!held);
        while(next_imu<target) {
            if(clock<next_imu) clock=next_imu;
            next_imu+=10000; // 100 Hz, two register reads per IMU per frame
            for(auto address:{0x68,0x69}) {
                std::uint8_t data[12]{};
                assert(read(address,0x2d,data,1)==ESP_OK);
                assert(read(address,0x1f,data,12)==ESP_OK);
            }
        }
        if(clock<target) clock=target;
    }
    void delay_ms(unsigned ms) override {advance_to(clock+ms*1000);}
    std::uint64_t now_us() const override{return clock;}
private:
    template<class Operation> esp_err_t execute(std::uint8_t address,std::uint8_t reg,std::size_t n,bool reading,Operation operation) {
        const auto begin=clock;++request;bool entered=false,acquired=false;
        const auto result=runtime::policy::locked_transaction([&] {
            // Inject the ADS config-poll failure, never the interleaved IMU
            // traffic serviced during conversion wait.
            if(fail_take && address==0x48 && reg==1 && reading) {fail_take=false;clock+=11101;return false;}
            assert(!held);held=acquired=true;return true;
        },[&] {assert(held);held=false;++gives;},[&] {
            assert(held);entered=true;++sdk;clock+=500;
            if(sdk_error!=ESP_OK) {const auto error=sdk_error;sdk_error=ESP_OK;return error;}
            operation();return ESP_OK;
        },ESP_ERR_TIMEOUT);
        if(!acquired && held) ++failed_gives;
        diagnostics.record(address,reg,n,reading,entered,result,clock-begin);
        return result;
    }
};
}
int main() {
    using namespace node;
    Bus bus;drivers::SoilAds1115 adc(bus);assert(adc.initialize()==ESP_OK);
    std::array<unsigned,3> valid{},errors{};sampling::SoilSample sample;
    for(unsigned sweep=0;sweep<240;++sweep) {
        bus.advance_to(1000000ULL+sweep*500000ULL);
        for(unsigned channel=0;channel<3;++channel) {
            assert(adc.start_conversion(channel)==PortStatus::Ready);
            // delay_ms services the deterministic 100 Hz IMU register stream
            // between conversion start/result. No mutex is held during wait.
            if(!sweep && !channel) bus.fail_take=true;
            const auto result=runtime::policy::wait_conversion(adc,sample,drivers::ads_conversion_timeout_us,5,
                [&]{return bus.clock;},[&]{bus.delay_ms(10);});
            if(result.status==PortStatus::Ready) {
                assert(sample.validity==sampling::Validity::Valid && sample.raw && *sample.raw==1234);++valid[channel];
            } else {
                assert(!result.timed_out && adc.last_error()==ESP_ERR_TIMEOUT);
                assert(sample.validity==sampling::Validity::Error && !sample.raw && !sample.acquired_uptime_us);++errors[channel];
            }
            assert(!bus.held);
        }
    }
    bus.advance_to(121000000); // full 120s synthetic load, not a physical timer
    const auto d=bus.diagnostics.snapshot();const auto& ads=d[2];
    assert((valid==std::array<unsigned,3>{239,240,240}) && (errors==std::array<unsigned,3>{1,0,0}));
    assert(ads.transfers==2881 && ads.sdk_calls==2880 && ads.local_errors==1 && ads.sdk_errors==0 && ads.timeouts==1);
    assert(ads.last_failed_reg==1 && ads.last_failed_read && ads.last_failed_size==2 && !ads.last_failed_executed);
    assert(d[0].transfers==24000 && d[1].transfers==24000 && !d[0].errors && !d[1].errors);
    // A real entered SDK error must stay in its own cause bucket and release
    // ownership, followed by a successful next conversion on another channel.
    assert(adc.start_conversion(0)==PortStatus::Ready);bus.delay_ms(10);bus.sdk_error=ESP_ERR_INVALID_STATE;
    assert(adc.try_read_conversion(sample)==PortStatus::Error && adc.last_error()==ESP_ERR_INVALID_STATE && !sample.raw);
    assert(!bus.held);assert(adc.start_conversion(1)==PortStatus::Ready);bus.delay_ms(10);
    assert(adc.try_read_conversion(sample)==PortStatus::Ready && sample.validity==sampling::Validity::Valid);
    const auto final=bus.diagnostics.snapshot()[2];assert(final.sdk_errors==1 && final.local_errors==1 && !bus.failed_gives);
    std::puts("HOST_ADS_CONTENTION_TEST_PASS (TEST_ONLY actual ADS driver/120s simulated sweeps/2881 requests/local vs SDK errors; hardware and scheduler NOT_RUN)");
}
