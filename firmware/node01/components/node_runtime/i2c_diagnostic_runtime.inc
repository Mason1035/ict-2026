// Included in runtime.cpp private namespace only in the independent candidate.
lock_diagnostic::FiniteTrace finite_i2c_trace;
std::uint8_t finite_ads_stage = 0; // SlowSensorTask is sole writer/reader
bool finite_trace_printed = false; // HealthTask only
std::atomic<std::uint32_t> finite_trace_cs_max_us{0};
std::uint8_t finite_task_id(TaskHandle_t task) {
    if (!task) return 254; // explicit kernel null holder, distinct from unknown task
    for (unsigned i=0;i<handles.size();++i) if(handles[i] && handles[i]==task)return static_cast<std::uint8_t>(i);
    return lock_diagnostic::unavailable;
}
lock_diagnostic::Stamp finite_stamp() {
    // Kernel holder is a separate non-atomic sample, never taken under the
    // recorder spinlock. Unknown/no holder uses 255; owner events disambiguate.
    const auto holder=finite_task_id(xSemaphoreGetMutexHolder(i2c_mutex));
    return {static_cast<std::uint64_t>(esp_timer_get_time()),static_cast<std::uint32_t>(xTaskGetTickCount()),
        finite_task_id(xTaskGetCurrentTaskHandle()),static_cast<std::uint8_t>(uxTaskPriorityGet(nullptr)),
        static_cast<std::uint8_t>(xPortGetCoreID()),holder};
}
template<class Function> void finite_locked(Function function) {
    portENTER_CRITICAL(&i2c_trace_lock);
    const auto begin=esp_timer_get_time();function();
    const auto elapsed=static_cast<std::uint32_t>(esp_timer_get_time()-begin);
    if(elapsed>finite_trace_cs_max_us.load(std::memory_order_relaxed))finite_trace_cs_max_us.store(elapsed,std::memory_order_relaxed);
    portEXIT_CRITICAL(&i2c_trace_lock);
    // This is recorder critical-body wall time, not lock acquisition latency
    // or a proof of worst-case scheduler disturbance.
}
esp_err_t finite_i2c_executor(I2cTransaction,void*,const drivers::I2cTraceOperation&,const bool*);
void finite_ads_begin(unsigned channel) {
    finite_ads_stage=1;
    const auto stamp=finite_stamp();finite_locked([&]{finite_i2c_trace.ads_begin(stamp,static_cast<std::uint8_t>(channel));});
}
void finite_ads_end(int error,PortStatus status) {
    const auto stamp=finite_stamp();finite_locked([&]{finite_i2c_trace.ads_end(stamp,error,static_cast<std::uint8_t>(status));});
    finite_ads_stage=0;
}
lock_diagnostic::TraceOutput finite_output;
void start_finite_i2c_trace() {
    if(finite_trace_printed)return;
    // Both producers are parked, Storage is finished. Seal is a flag change;
    // index preparation/sorting/link checks below are outside the spinlock.
    finite_trace_printed=true;
    finite_locked([&]{finite_i2c_trace.seal();});
    finite_output.begin(finite_i2c_trace,handles.size());
}
void service_finite_i2c_trace() {
    finite_output.pump([&](const lock_diagnostic::OutputLine& line){
        using lock_diagnostic::OutputKind;
        if(line.kind==OutputKind::Begin) {
            ESP_LOGW(tag,"I2C_TRACE_BEGIN format=REQUEST_WINDOW_V2 mode=TEST_ONLY_I2C_MUTEX_DIAGNOSTIC mutex=1 event_bytes=%u recorder_bytes=%u pre_requests=24 post_requests=24 ads_pre=24 ads_post=24 batch_lines=4 batch_us=20000 long_wait_us=2000; finite first-anomaly context, no full-run history claim",
                static_cast<unsigned>(sizeof(lock_diagnostic::Event)),static_cast<unsigned>(sizeof(finite_i2c_trace)));
        } else if(line.kind==OutputKind::Task) {
            ESP_LOGI(tag,"I2C_TRACE_TASK id=%u name=%s; 254=NONE 255=UNAVAILABLE",line.task,config::tasks[line.task].name);
        } else if(line.kind==OutputKind::Event) {
            const auto& e=line.event;
            ESP_LOGI(tag,"I2C_TRACE_EVENT banks=%u seq=%lu us=%" PRIu64 " tick=%lu kind=%s mutex=1 req=%lu gen=%lu link=%lu prev_release=%lu task=%u pri=%u core=%u holder=%u owner_gen=%lu owner_pri=%u budget=%lu wait_us=%lu wait_ticks=%lu addr=0x%02x op=%c reg=0x%02x len=%u ads=%lu channel=%u stage=%u result=%ld flags=%u",
            1U<<line.bank,static_cast<unsigned long>(e.seq),e.us,static_cast<unsigned long>(e.tick),lock_diagnostic::kind_name(e.kind),
            static_cast<unsigned long>(e.request),static_cast<unsigned long>(e.generation),static_cast<unsigned long>(e.link),static_cast<unsigned long>(e.previous_release),
            e.task,e.priority,e.core,e.holder,static_cast<unsigned long>(e.owner_generation),e.owner_priority,
            static_cast<unsigned long>(e.budget_ticks),static_cast<unsigned long>(e.wait_us),static_cast<unsigned long>(e.wait_ticks),
            e.address,e.operation,e.reg,e.length,static_cast<unsigned long>(e.ads_request),e.channel,e.stage,static_cast<long>(e.result),e.flags);

        } else {
            const auto& s=finite_output.summary();
            ESP_LOGW(tag,"I2C_TRACE_END selected=%u history=%u anomalies=%u last_seq=%lu requests=%lu generations=%lu first_anomaly=%lu trace_overflow=%lu prehistory_evicted=%lu missing_links=%lu active=%lu metadata_errors=%lu id_exhausted=%d recorder_cs_body_max_us=%lu filtered_events=%lu anomalies_total=%lu anomalies_outside_window=%lu boundary_links=%lu no_anomaly_observed=%d incomplete_requests=%lu ads_active=%d integrity=%s",
                static_cast<unsigned>(s.selected),static_cast<unsigned>(s.history),static_cast<unsigned>(s.anomalies),
                static_cast<unsigned long>(s.last_seq),static_cast<unsigned long>(s.requests),static_cast<unsigned long>(s.generations),static_cast<unsigned long>(s.first_anomaly),static_cast<unsigned long>(s.trace_overflow),static_cast<unsigned long>(s.history_evicted),static_cast<unsigned long>(finite_output.missing()),static_cast<unsigned long>(s.active),static_cast<unsigned long>(s.metadata_errors),s.id_exhausted,static_cast<unsigned long>(finite_trace_cs_max_us.load()),static_cast<unsigned long>(s.filtered_events),static_cast<unsigned long>(s.anomalies_total),static_cast<unsigned long>(s.anomalies_outside_window),static_cast<unsigned long>(finite_output.boundary()),s.first_anomaly==0,static_cast<unsigned long>(s.incomplete_requests),s.ads_active,finite_output.integrity());
        }
    },[]{return static_cast<std::uint64_t>(esp_timer_get_time());});
}
