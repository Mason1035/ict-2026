constexpr EventBits_t bench_ads_done = 1U << 14;
using BenchBusTx = drivers::bench_bus::Transaction;
struct BenchAdsSample {
    std::array<BenchBusTx, 16> tx{};
    std::uint64_t request = 0, acquired = 0, end = 0;
    unsigned channel = 0, count = 0, omitted = 0;
    int raw = 0;
    esp_err_t rc = ESP_OK;
    sampling::Validity validity = sampling::Validity::Unavailable;
};
struct BenchBusStats {
    std::uint64_t wall = 0, sdk_time = 0, lock = 0;
    std::uint32_t count = 0, sdk_ok = 0, sdk_error = 0, local_error = 0, sdk_259 = 0;
    std::uint32_t timeout = 0, retry = 0, wall_max = 0, sdk_max = 0, lock_max = 0;
    BenchBusTx first_failure{}, longest{}, lock_longest{};
};
std::array<BenchBusStats,3> bench_bus_stats{};
using BenchAdsSamples=std::array<BenchAdsSample, (toe_bench::window_seconds * 1000 / config::soil_period_ms + 2)*3>;
BenchAdsSamples* bench_ads_samples=nullptr;
static_assert(std::is_trivially_destructible_v<BenchAdsSamples>);
bool prepare_bench_ads_trace() {
    void* memory=heap_caps_malloc(sizeof(BenchAdsSamples),MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (memory) bench_ads_samples=::new(memory) BenchAdsSamples{};
    ESP_LOGI(tag,"TOE_ADS_TRACE_BUFFER storage=PSRAM rows=%u bytes=%u allocated=%d",
        static_cast<unsigned>(std::tuple_size_v<BenchAdsSamples>),static_cast<unsigned>(sizeof(BenchAdsSamples)),
        bench_ads_samples!=nullptr);
    return bench_ads_samples!=nullptr;
}
BenchAdsSample bench_ads_preflight{};
BenchAdsSample* bench_ads_current = nullptr;
unsigned bench_ads_count = 0, bench_ads_omitted = 0;
std::uint32_t bench_ads_lock_wait_us = 0;
std::atomic<bool> bench_bus_active{false};
std::array<drivers::toe_trace::Request,2> bench_latest_status{}, bench_first_empty{}, bench_first_gap{}, bench_first_error{};

void bench_note_imu(unsigned site, PortStatus state, std::optional<std::uint64_t> acquired, std::uint64_t previous) {
    if (state == PortStatus::Unavailable && !bench_first_empty[site].seq)
        bench_first_empty[site] = bench_latest_status[site];
    if (state == PortStatus::Error && !bench_first_error[site].seq)
        bench_first_error[site] = bench_latest_status[site];
    if (acquired && previous && *acquired > previous + 2 * config::imu_period_ms * 1000ULL && !bench_first_gap[site].seq)
        bench_first_gap[site] = bench_latest_status[site];
}
void bench_note_bus(const BenchBusTx& tx) {
    const unsigned site = tx.addr == board::bus::imu_top_address ? 0 :
        tx.addr == board::bus::imu_toe_address ? 1 : 2;
    if (site == 2 && bench_ads_current) {
        auto& sample = *bench_ads_current;
        if (sample.count < sample.tx.size()) sample.tx[sample.count++] = tx;
        else ++sample.omitted;
    }
    if (!bench_bus_active.load()) return;
    auto& stats = bench_bus_stats[site];
    const auto wall = static_cast<std::uint32_t>(tx.end_us - tx.request_us);
    const auto sdk = static_cast<std::uint32_t>(tx.sdk_end_us - tx.sdk_begin_us);
    if (++stats.count == 1 || wall > stats.wall_max) { stats.wall_max = wall; stats.longest = tx; }
    if (stats.count == 1 || tx.lock_us > stats.lock_max) { stats.lock_max = tx.lock_us; stats.lock_longest = tx; }
    stats.wall += wall; stats.sdk_time += sdk; stats.lock += tx.lock_us;
    if (sdk > stats.sdk_max) stats.sdk_max = sdk;
    if (tx.rc != ESP_OK && !stats.first_failure.end_us) stats.first_failure = tx;
    stats.sdk_ok += tx.sdk && tx.rc == ESP_OK;
    stats.sdk_error += tx.sdk && tx.rc != ESP_OK;
    stats.local_error += !tx.sdk && tx.rc != ESP_OK;
    stats.sdk_259 += tx.sdk && tx.rc == ESP_ERR_INVALID_STATE;
    stats.timeout += tx.rc == ESP_ERR_TIMEOUT;
    stats.retry += tx.retry;
}
void bench_sample_ads(BenchAdsSample& row, unsigned channel) {
    bench_ads_current = &row;
    row.channel = channel;
    row.request = esp_timer_get_time();
    auto state = adc.start_conversion(channel);
    sampling::SoilSample sample;
    if (state == PortStatus::Ready) {
        const auto conversion = policy::wait_conversion(adc, sample,
            drivers::ads_conversion_timeout_us, config::ads_max_polls,
            [] { return static_cast<std::uint64_t>(esp_timer_get_time()); }, [] { vTaskDelay(1); });
        state = conversion.status;
        if (conversion.timed_out) adc.cancel_conversion(ESP_ERR_TIMEOUT);
    }
    row.rc = adc.last_error();
    row.validity = state == PortStatus::Ready ? sample.validity :
        state == PortStatus::Error ? sampling::Validity::Error : sampling::Validity::Unavailable;
    if (sample.raw) row.raw = *sample.raw;
    if (sample.acquired_uptime_us) row.acquired = *sample.acquired_uptime_us;
    row.end = esp_timer_get_time();
    bench_ads_current = nullptr;
}
#ifdef CONFIG_NODE01_TOE_BENCH_QUEUE_SD
void bench_enqueue_ads(const BenchAdsSample& row) {
    sampling::AcquisitionRecord record;
    record.kind=sampling::RecordKind::Soil;
    record.channel=row.channel;
    record.attempted_uptime_us=row.request;
    record.error=row.rc;
    record.soil.validity=row.validity;
    if (row.validity==sampling::Validity::Valid) {
        record.soil.raw=static_cast<std::int16_t>(row.raw);
        record.soil.acquired_uptime_us=row.acquired;
        soil_valid[row.channel].fetch_add(1);
    } else if (row.validity==sampling::Validity::Error) {
        soil_failed[row.channel].fetch_add(1);
    }
    enqueue_record(record);
}
#endif
void bench_print_tx(const char* phase, unsigned seq, unsigned order, const BenchBusTx& tx) {
    ESP_LOGI(tag,"TOE_ADS_BUS phase=%s seq=%u order=%u addr=0x%02x reg=0x%02x op=%c sdk=%d retry=%d rc=%d word=%d"
        " request_us=%" PRIu64 " sdk_begin_us=%" PRIu64 " sdk_end_us=%" PRIu64 " end_us=%" PRIu64 " lock_us=%lu",
        phase,seq,order,tx.addr,tx.reg,tx.op,tx.sdk,tx.retry,tx.rc,tx.config_word,
        tx.request_us,tx.sdk_begin_us,tx.sdk_end_us,tx.end_us,static_cast<unsigned long>(tx.lock_us));
    vTaskDelay(1);
}
void bench_print_ads(const char* phase, unsigned seq, const BenchAdsSample& row) {
    ESP_LOGI(tag,"TOE_ADS_SAMPLE phase=%s seq=%u channel=%u validity=%u rc=%d timeout=%d raw=%d"
        " request_us=%" PRIu64 " acquired_us=%" PRIu64 " end_us=%" PRIu64 " tx=%u omitted=%u",
        phase,seq,row.channel,static_cast<unsigned>(row.validity),row.rc,row.rc==ESP_ERR_TIMEOUT,row.raw,
        row.request,row.acquired,row.end,row.count,row.omitted);
    vTaskDelay(1);
    for (unsigned i=0;i<row.count;++i) bench_print_tx(phase,seq,i+1,row.tx[i]);
}
[[noreturn]] void bench_ads_task() {
    await_start();
    if (!wait_startup_stage(imu_initialized,"ADS_WAIT_IMU") ||
        imu_startup[0].load()!=startup::InitState::Ready || imu_startup[1].load()!=startup::InitState::Ready) {
        abort_startup("ADS_IMU_PREREQUISITE");
        park_startup(TaskId::SlowSensor,"ADS_IMU_PREREQUISITE");
    }
    bench_ads_current = &bench_ads_preflight;
    const auto init = adc.initialize();
    bench_ads_current = nullptr;
    int word = -1;
    for (unsigned i=0;i<bench_ads_preflight.count;++i) {
        const auto& tx=bench_ads_preflight.tx[i];
        bench_print_tx("init",0,i+1,tx);
        if (tx.op=='R' && tx.rc==ESP_OK) word=tx.config_word;
    }
    ESP_LOGI(tag,"TOE_ADS_INIT addr=0x48 rc=%d word=%d pga_mv=%u sps=%u period_ms=%u",
        init,word,drivers::ads_pga_mv,drivers::ads_sps,config::soil_period_ms);
    bool ready = init == ESP_OK && word >= 0 && (word & 0x7fff) == 0x4383;
    for (unsigned channel=0;ready && channel<3;++channel) {
        BenchAdsSample row{};
        bench_sample_ads(row,channel);
        bench_print_ads("preflight",channel+1,row);
        ready = row.validity==sampling::Validity::Valid && row.acquired && !row.omitted;
    }
#ifdef CONFIG_NODE01_TOE_BENCH_QUEUE_SD
    ESP_LOGW(tag,"TOE_ADS_PREFLIGHT ready=%d sd=0 queue=1 storage_task=1 network=0",ready);
#else
    ESP_LOGW(tag,"TOE_ADS_PREFLIGHT ready=%d sd=0 queue=0 storage_task=0 network=0",ready);
#endif
    slow_startup = ready ? startup::InitState::Ready : startup::InitState::Failed;
    xEventGroupSetBits(events,slow_initialized);
    if (!ready) park_startup(TaskId::SlowSensor,"ADS_PREFLIGHT_FAILED");
    const auto released=xEventGroupWaitBits(events,capture_ready | startup_aborted,pdFALSE,pdFALSE,portMAX_DELAY);
    if (released & startup_aborted) park_startup(TaskId::SlowSensor,"CAPTURE_START_BLOCKED");
    auto last_wake=xTaskGetTickCount();
    while (!capture_should_stop()) {
        for (unsigned channel=0;channel<3 && !capture_should_stop();++channel) {
            if (bench_ads_count==bench_ads_samples->size()) {
                BenchAdsSample extra{};
                bench_sample_ads(extra,channel);
#ifdef CONFIG_NODE01_TOE_BENCH_QUEUE_SD
                bench_enqueue_ads(extra);
#endif
                ++bench_ads_omitted;
            } else {
                auto& row=(*bench_ads_samples)[bench_ads_count++];
                bench_sample_ads(row,channel);
#ifdef CONFIG_NODE01_TOE_BENCH_QUEUE_SD
                bench_enqueue_ads(row);
#endif
            }
        }
        const bool delayed=xTaskDelayUntil(&last_wake,pdMS_TO_TICKS(config::soil_period_ms))==pdTRUE;
        if (policy::period_outcome(delayed,last_wake,xTaskGetTickCount())==policy::PeriodOutcome::Late) {
            vTaskDelay(1);
            policy::rebase_after_yield(last_wake,xTaskGetTickCount());
        }
    }
#ifdef CONFIG_NODE01_TOE_BENCH_QUEUE_SD
    acknowledge_producer_stop(producer_slow);
#endif
    xEventGroupSetBits(events,bench_ads_done);
    for (;;) vTaskDelay(pdMS_TO_TICKS(1000));
}
void bench_ads_export() {
    ESP_LOGI(tag,"TOE_ADS_CAPTURE rows=%u omitted=%u",bench_ads_count,bench_ads_omitted);
    for (unsigned i=0;i<bench_ads_count;++i) bench_print_ads("capture",i+1,(*bench_ads_samples)[i]);
    constexpr unsigned addresses[]{0x68,0x69,0x48};
    for (unsigned i=0;i<3;++i) {
        const auto& stats=bench_bus_stats[i];
        ESP_LOGI(tag,"TOE_ADS_BUS_SUM addr=0x%02x attempts=%u sdk_ok=%u sdk_error=%u local_error=%u sdk_259=%u timeout=%u retry=%u"
            " wall_us=%" PRIu64 " sdk_us=%" PRIu64 " lock_us=%" PRIu64 " wall_max=%u sdk_max=%u lock_max=%u",
            addresses[i],stats.count,stats.sdk_ok,stats.sdk_error,stats.local_error,stats.sdk_259,stats.timeout,stats.retry,
            stats.wall,stats.sdk_time,stats.lock,stats.wall_max,stats.sdk_max,stats.lock_max);
        vTaskDelay(1);
        if (stats.count) {
            bench_print_tx("longest",addresses[i],1,stats.longest);
            bench_print_tx("lock_longest",addresses[i],1,stats.lock_longest);
        }
        if (stats.first_failure.end_us) bench_print_tx("first_failure",addresses[i],1,stats.first_failure);
    }
}
