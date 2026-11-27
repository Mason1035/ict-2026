// Owned by ImuTask except the bounded ISR edge arrays. UART-only, one per boot.
std::array<drivers::toe_trace::Trace, 2> bench_trace;
bool bench_armed = false; // irq_lock
char bench_id[17]{};
#ifdef CONFIG_NODE01_REAL_TEST_ONLY
// The console pauses before capture while the communication owner resolves this request.
std::atomic<unsigned> publish_request{0};
#endif
std::uint64_t bench_request_us = 0, bench_prearm_end_us = 0;
int bench_prearm_level[2][2]{};
std::array<std::uint64_t, 2> bench_arm_us{}, bench_arm_end_us{};
std::array<esp_err_t, 2> bench_arm_result{ESP_ERR_INVALID_STATE, ESP_ERR_INVALID_STATE};
std::array<unsigned, 2> bench_status_ok{}, bench_status_empty{}, bench_status_ready{}, bench_status_errors{};
std::array<unsigned, 2> bench_sdk_259{}, bench_local_errors{};
std::uint64_t bench_last_edge_us = 0, bench_last_valid_us = 0, bench_lock_wait_us = 0;
char bench_origin = 'A';
drivers::toe_trace::Request bench_pending{};
bool bench_status_pending = false;
std::atomic<unsigned> bench_foreign_reads{0};

constexpr gpio_num_t bench_pins[]{static_cast<gpio_num_t>(board::pin::imu_top_int1),
                                  static_cast<gpio_num_t>(board::pin::imu_toe_int1)};
struct BenchCounter {
    pcnt_unit_handle_t unit = nullptr;
    pcnt_channel_handle_t channel = nullptr;
    bool enabled = false, running = false;
};
std::array<BenchCounter,4> bench_counters{};
std::array<int,4> bench_pre_start{}, bench_pre_end{}, bench_begin{}, bench_end{};

void close_bench_counters() {
    for (auto& c : bench_counters) {
        if (c.running) { pcnt_unit_stop(c.unit); c.running = false; }
        if (c.enabled) { pcnt_unit_disable(c.unit); c.enabled = false; }
        if (c.channel) { pcnt_del_channel(c.channel); c.channel = nullptr; }
        if (c.unit) { pcnt_del_unit(c.unit); c.unit = nullptr; }
    }
}
esp_err_t prepare_bench_counters() {
    for (unsigned i = 0; i < bench_counters.size(); ++i) {
        auto& c = bench_counters[i];
        pcnt_unit_config_t unit{};
        unit.high_limit = 30000;
        unit.low_limit = -30000;
        unit.flags.accum_count = true;
        auto e = pcnt_new_unit(&unit, &c.unit);
        if (e != ESP_OK) return e;
        pcnt_chan_config_t channel{};
        channel.edge_gpio_num = bench_pins[i/2];
        channel.level_gpio_num = -1;
        e = pcnt_new_channel(c.unit, &channel, &c.channel);
        // The local IDF PCNT driver enables an input pull-up during channel
        // setup. Restore the acquisition pin's floating configuration before
        // starting the counter or observing the pre-ARM window.
        const auto pull = gpio_set_pull_mode(bench_pins[i/2], GPIO_FLOATING);
        if (e != ESP_OK) return e;
        if (pull != ESP_OK) return pull;
        const auto increase = PCNT_CHANNEL_EDGE_ACTION_INCREASE;
        const auto hold = PCNT_CHANNEL_EDGE_ACTION_HOLD;
        e = pcnt_channel_set_edge_action(c.channel, i%2 ? hold : increase, i%2 ? increase : hold);
        if (e == ESP_OK) e = pcnt_unit_add_watch_point(c.unit, unit.high_limit);
        if (e == ESP_OK) e = pcnt_unit_add_watch_point(c.unit, unit.low_limit);
        if (e == ESP_OK) e = pcnt_unit_enable(c.unit);
        if (e != ESP_OK) return e;
        c.enabled = true;
        e = pcnt_unit_clear_count(c.unit);
        if (e == ESP_OK) e = pcnt_unit_start(c.unit);
        if (e != ESP_OK) return e;
        c.running = true;
    }
    return ESP_OK;
}
bool snapshot_bench_counters(std::array<int,4>& counts) {
    bool good = true;
    for (unsigned i = 0; i < counts.size(); ++i) {
        if (pcnt_unit_get_count(bench_counters[i].unit, &counts[i]) != ESP_OK) good = false;
    }
    return good;
}
bool bench_fail(const char* reason, esp_err_t rc) {
    close_bench_counters();
#ifdef CONFIG_NODE01_TOE_BENCH_ADS
    xEventGroupSetBits(events,startup_aborted);
#endif
    ESP_LOGE(tag,"TOE_BENCH_ABORT boot=%s reason=%s rc=%d",bench_id,reason,static_cast<int>(rc));
    return false;
}
bool wait_bench_start(bool initialized) {
    const auto a = esp_random();
    const auto b = esp_random();
    std::snprintf(bench_id,sizeof(bench_id),"%08" PRIx32 "%08" PRIx32,a,b);
    if (!initialized || !imu_irqs_ready) return bench_fail("INIT_OR_GPIO",ESP_ERR_INVALID_STATE);
    if (const auto e = prepare_bench_counters(); e != ESP_OK) return bench_fail("PCNT_INIT",e);
    const int flags = fcntl(STDIN_FILENO,F_GETFL,0);
    if (flags < 0 || fcntl(STDIN_FILENO,F_SETFL,flags | O_NONBLOCK) != 0)
        return bench_fail("UART0_INPUT",ESP_FAIL);
    toe_bench::Command parser(bench_id);
#if defined(CONFIG_NODE01_TOE_BENCH_SD) && !defined(CONFIG_NODE01_TOE_BENCH_QUEUE_SD)
    ESP_LOGW(tag,"TOE_SD_READY mount_rc=0 sd=1 queue=0 storage_task=0 network=0 sd_khz=%d",CONFIG_NODE01_SD_KHZ);
#endif
#ifdef CONFIG_NODE01_TOE_BENCH_SD
    constexpr int sd_active=1;
#else
    constexpr int sd_active=0;
#endif
    ESP_LOGW(tag,"TOE_BENCH_READY schema=1 boot=%s source=REAL_SENSOR_TEST_ONLY top_gpio=%d toe_gpio=%d window_s=%u sd=%d queue=%d network=0 auto_start=0",
        bench_id,bench_pins[0],bench_pins[1],toe_bench::window_seconds,sd_active,config::storage_enabled);
    for (;;) {
#ifdef CONFIG_NODE01_REAL_TEST_ONLY
        if (publish_request.load() != 0) {
            vTaskDelay(1);
            continue;
        }
#endif
        for (unsigned i = 0; i < 48; ++i) {
            char ch;
            if (read(STDIN_FILENO,&ch,1) != 1) break;
            const bool start = parser.feed(ch);
#ifdef CONFIG_NODE01_TOE_BENCH_QUEUE_SD
            if (const auto order = parser.take_readab_order()) {
                close_bench_counters();
                bench_readab_request.store(order);
                ESP_LOGW(tag,"TOE_READAB_ACCEPT boot=%s order=%u target=/sdcard/N0000195.CSV",bench_id,order);
                while (!bench_readab_done.load()) vTaskDelay(pdMS_TO_TICKS(50));
                park_startup(TaskId::Imu,"TOE_READAB_COMPLETE");
            }
            if (const auto cycles = parser.take_wrstress_cycles()) {
                close_bench_counters();
                bench_wrstress_request.store(cycles);
                ESP_LOGW(tag, "TOE_WRSTRESS_ACCEPT boot=%s cycles=%u target=/sdcard/WRSTRESS.TMP", bench_id, cycles);
                while (!bench_wrstress_done.load()) vTaskDelay(pdMS_TO_TICKS(50));
                park_startup(TaskId::Imu, "TOE_WRSTRESS_COMPLETE");
            }
#endif
#ifdef CONFIG_NODE01_REAL_TEST_ONLY
            if (const auto limit = parser.take_publish_limit()) {
                publish_request.store(limit);
                break;
            }
#endif
            if (!start) continue;
#ifdef CONFIG_NODE01_TOE_BENCH_QUEUE_SD
            if (parser.start_single_sector()) {
                bench_verify_subread.store(storage::IncrementalVerifier::sector_bytes);
                ESP_LOGW(tag,"TOE_BENCH_SUBREAD subread=512");
            } else {
                bench_verify_subread.store(storage::IncrementalVerifier::read_quantum);
            }
            bench_open_request.store(true);
            const auto open_wait_begin = esp_timer_get_time();
            while (!bench_file_ready_atomic.load() &&
                   !(xEventGroupGetBits(events) & startup_aborted) &&
                   esp_timer_get_time() - open_wait_begin < 10000000LL) {
                vTaskDelay(pdMS_TO_TICKS(10));
            }
            if (!bench_file_ready_atomic.load() || (xEventGroupGetBits(events) & startup_aborted)) {
                return bench_fail("QUEUE_SD_FILE_READY", ESP_ERR_INVALID_STATE);
            }
#endif
            bench_request_us = esp_timer_get_time();
            ESP_LOGW(tag,"TOE_BENCH_ACCEPT boot=%s request_us=%" PRIu64,bench_id,bench_request_us);
            if (!snapshot_bench_counters(bench_pre_start)) return bench_fail("PCNT_PRE_START",ESP_FAIL);
            for (unsigned j=0;j<2;++j) bench_prearm_level[0][j]=gpio_get_level(bench_pins[j]);
            vTaskDelay(drivers::timing::guarded_wait_ticks(toe_bench::prearm_ms,configTICK_RATE_HZ));
            if (!snapshot_bench_counters(bench_pre_end)) return bench_fail("PCNT_PRE_END",ESP_FAIL);
            for (unsigned j=0;j<2;++j) bench_prearm_level[1][j]=gpio_get_level(bench_pins[j]);
            bench_prearm_end_us = esp_timer_get_time();
            portENTER_CRITICAL(&irq_lock);
            bench_armed = true;
            portEXIT_CRITICAL(&irq_lock);
            return true;
        }
        vTaskDelay(1);
    }
}
void append_bench_status(unsigned site) {
    if (!bench_status_pending) return;
    auto& r = bench_pending;
    if (r.status_present) {
        ++bench_status_ok[site];
        if (r.status & 8) ++bench_status_ready[site];
        else ++bench_status_empty[site];
    } else if (r.sdk_entered) {
        ++bench_status_errors[site];
        if (r.result == ESP_ERR_INVALID_STATE) ++bench_sdk_259[site];
    } else {
        ++bench_local_errors[site];
    }
    bench_trace[site].note_request(r, ESP_ERR_INVALID_STATE);
#ifdef CONFIG_NODE01_TOE_BENCH_ADS
    r.seq = bench_trace[site].total_requests;
    bench_latest_status[site] = r;
#endif
    bench_status_pending = false;
}
void print_bench_read(const char* site,const char* window,const drivers::toe_trace::Request& r) {
    ESP_LOGI(tag,"TOE_BENCH_READ site=%s window=%s seq=%lu origin=%c task=ImuTask addr=0x%02x reg=0x2d len=1"
        " request_us=%" PRIu64 " sdk_begin_us=%" PRIu64 " sdk_end_us=%" PRIu64 " end_us=%" PRIu64
        " lock_wait_us=%" PRIu64 " sdk_entered=%d rc=%ld status_present=%d status=0x%02x drdy=%d"
        " edge_us=%" PRIu64 " valid_us=%" PRIu64 " raw_entered=%d raw_begin_us=%" PRIu64 " raw_end_us=%" PRIu64 " raw_rc=%ld",
        site,window,static_cast<unsigned long>(r.seq),r.origin,site[2]=='P' ? 0x68 : 0x69,
        r.request_us,r.sdk_begin_us,r.sdk_end_us,r.end_us,r.lock_wait_us,r.sdk_entered,static_cast<long>(r.result),
        r.status_present,r.status,r.status_present ? ((r.status & 8) ? 1 : 0) : -1,r.last_edge_us,r.last_valid_us,
        r.raw_entered,r.raw_begin_us,r.raw_end_us,static_cast<long>(r.raw_result));
    vTaskDelay(1);
}
[[noreturn]] void finish_bench() {
    bool count_ok = snapshot_bench_counters(bench_end);
    close_bench_counters();
#ifdef CONFIG_NODE01_TOE_BENCH_QUEUE_SD
    acknowledge_producer_stop(producer_imu);
#endif
#ifdef CONFIG_NODE01_TOE_BENCH_ADS
    if (!(xEventGroupWaitBits(events,bench_ads_done,pdFALSE,pdTRUE,pdMS_TO_TICKS(750)) & bench_ads_done)) {
        bench_fail("ADS_DRAIN_TIMEOUT",ESP_ERR_TIMEOUT);
        park_startup(TaskId::Imu,"ADS_DRAIN_TIMEOUT");
    }
    bench_bus_active = false;
#endif
#ifdef CONFIG_NODE01_TOE_BENCH_QUEUE_SD
    if (!(xEventGroupWaitBits(events,bench_queue_done,pdFALSE,pdTRUE,pdMS_TO_TICKS(125000)) & bench_queue_done)) {
        bench_fail("QUEUE_SD_DRAIN_TIMEOUT",ESP_ERR_TIMEOUT);
        park_startup(TaskId::Imu,"QUEUE_SD_DRAIN_TIMEOUT");
    }
#endif
    const auto c = capture_observation();
    ESP_LOGW(tag,"TOE_BENCH_EXPORT boot=%s start_us=%" PRIu64 " stop_us=%" PRIu64 " prearm_end_us=%" PRIu64 " pcnt_ok=%d foreign_reads=%u",
        bench_id,c.started_us,c.requested_stop_us,bench_prearm_end_us,count_ok,bench_foreign_reads.load());
    for (unsigned i=0;i<2;++i) {
        const char* site=i ? "TOE" : "TOP";
        const auto irq=irq_observation(i);
        const auto& trace=bench_trace[i];
        const auto& d=imus.diagnostic(static_cast<sampling::ImuSite>(i));
        const auto rises=bench_end[2*i]-bench_begin[2*i];
        const auto falls=bench_end[2*i+1]-bench_begin[2*i+1];
        const auto clipped_edges=irq.edges - static_cast<std::uint32_t>(trace.edge_count);
        ESP_LOGI(tag,"TOE_BENCH_PHASE site=%s arm_us=%" PRIu64 " arm_end_us=%" PRIu64 " arm_rc=%d arm_status_seen=%d arm_status=0x%02x"
            " pre_rising=%d pre_falling=%d pre_level_first=%d pre_level_last=%d rising=%d falling=%d",
            site,bench_arm_us[i],bench_arm_end_us[i],static_cast<int>(bench_arm_result[i]),
            d.startup_status_observed,d.startup_status,bench_pre_end[2*i]-bench_pre_start[2*i],
            bench_pre_end[2*i+1]-bench_pre_start[2*i+1],bench_prearm_level[0][i],bench_prearm_level[1][i],rises,falls);
        vTaskDelay(1);
        ESP_LOGI(tag,"TOE_BENCH_SITE site=%s irq_total=%lu capture_irq=%lu saved_edges=%u edge_not_retained=%lu"
            " notify=%lu notify_coalesced=%lu service=%u irq_empty=%u poll=%u valid=%u sample_errors=%u empty=%u gap_us=%u",
            site,static_cast<unsigned long>(irq.edges),static_cast<unsigned long>(irq.capture_edges),
            static_cast<unsigned>(trace.edge_count),static_cast<unsigned long>(clipped_edges),
            static_cast<unsigned long>(irq.notify_claims),static_cast<unsigned long>(irq.notify_coalesced),
            imu_irq_services[i].load(),imu_irq_empty[i].load(),imu_irq_fallbacks[i].load(),
            imu_valid[i].load(),imu_failed[i].load(),imu_no_data[i].load(),imu_max_gap_us[i].load());
        vTaskDelay(1);
        // The retained windows can overlap. Count unique sequence slots.
        unsigned retained=static_cast<unsigned>(trace.first_count);
        auto count_unique=[&](const drivers::toe_trace::Request& row) { if(row.seq>trace.first_count) ++retained; };
        for (std::size_t j=0;j<trace.before_count;++j) count_unique(trace.before[j]);
        for (std::size_t j=0;j<trace.after_count;++j) count_unique(trace.after[j]);
        if (trace.first_error_seq) count_unique(trace.first_error);
        ESP_LOGI(tag,"TOE_BENCH_TX site=%s total=%lu sdk_ok=%u sdk_errors=%u errors_259=%u local_errors=%u drdy=%u absent_drdy=%u"
            " first=%u before=%u after=%u first_259=%lu request_not_retained=%lu",
            site,static_cast<unsigned long>(trace.total_requests),bench_status_ok[i],bench_status_errors[i],
            bench_sdk_259[i],bench_local_errors[i],bench_status_ready[i],bench_status_empty[i],
            static_cast<unsigned>(trace.first_count),static_cast<unsigned>(trace.before_count),
            static_cast<unsigned>(trace.after_count),static_cast<unsigned long>(trace.first_error_seq),
            static_cast<unsigned long>(trace.total_requests-retained));
        vTaskDelay(1);
        if (i==1 && drivers::toe_trace::Trace::rate_abnormal(irq.capture_edges,c.requested_stop_us-c.started_us)) {
            ESP_LOGW(tag,"TOE_IRQ_RATE_ABNORMAL capture=%lu window_us=%" PRIu64 " threshold_hz=500",
                static_cast<unsigned long>(irq.capture_edges),c.requested_stop_us-c.started_us);
            vTaskDelay(1);
        }
        for (std::size_t j=0;j<trace.edge_count;++j) {
            const auto& x=trace.edges[j];
            ESP_LOGI(tag,"TOE_BENCH_EDGE site=%s irq=%lu us=%" PRIu64 " level=%d trigger=RISING",
                site,static_cast<unsigned long>(x.irq_number),x.us,x.level_high);
            vTaskDelay(1);
        }
        for (std::size_t j=0;j<trace.first_count;++j) print_bench_read(site,"first",trace.first[j]);
        for (std::size_t j=0;j<trace.before_count;++j) print_bench_read(site,"before",trace.before[j]);
        if (trace.first_error_seq) print_bench_read(site,"error",trace.first_error);
        for (std::size_t j=0;j<trace.after_count;++j) print_bench_read(site,"after",trace.after[j]);
    }
#ifdef CONFIG_NODE01_TOE_BENCH_ADS
    bench_ads_export();
    for (unsigned site=0; site<2; ++site) {
        const char* name=site ? "TOE" : "TOP";
        if (bench_first_empty[site].seq) print_bench_read(name,"first_empty",bench_first_empty[site]);
        if (bench_first_gap[site].seq) print_bench_read(name,"first_gap",bench_first_gap[site]);
        if (bench_first_error[site].seq) print_bench_read(name,"first_sample_error",bench_first_error[site]);
    }
#endif
#ifdef CONFIG_NODE01_TOE_BENCH_QUEUE_SD
    ESP_LOGI(tag,"TOE_QUEUE_IO append_max_us=%" PRIu64 " flush_max_us=%" PRIu64
             " long_total=%" PRIu64 " long_omitted=%" PRIu64 " context_errors=%" PRIu64,
             storage_latency.append().maximum(),storage_latency.flush().maximum(),storage_latency.total_events(),
             storage_latency.overwritten_history(),storage_latency.context_errors());
    vTaskDelay(1);
    for (auto seq=storage_latency.overwritten_history()+1;seq<=storage_latency.total_events();++seq) {
        if (const auto* row=storage_latency.event(seq)) {
            ESP_LOGI(tag,"TOE_QUEUE_IO_SPAN seq=%" PRIu64 " operation=%u begin_us=%" PRIu64 " end_us=%" PRIu64
                     " q_before=%u q_after=%u success=%d",
                     seq,row->operation,row->started_us,row->finished_us,row->queue_before,row->queue_after,row->success);
            vTaskDelay(1);
        }
    }
#elif defined(CONFIG_NODE01_TOE_BENCH_SD)
    if (!(xEventGroupWaitBits(events,bench_sd_done,pdFALSE,pdTRUE,pdMS_TO_TICKS(8000)) & bench_sd_done)) {
        bench_fail("SD_DRAIN_TIMEOUT",ESP_ERR_TIMEOUT);
        park_startup(TaskId::Imu,"SD_DRAIN_TIMEOUT");
    }
    bench_sd_export();
#endif
    ESP_LOGW(tag,"TOE_BENCH_END schema=1 boot=%s pcnt_ok=%d",bench_id,count_ok);
    for (;;) vTaskDelay(pdMS_TO_TICKS(1000));
}

