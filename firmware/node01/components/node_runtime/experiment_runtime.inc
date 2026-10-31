// Included only by runtime.cpp in its private namespace and only for sandbox.
// Hardware/file ownership stays in the original sensor/Storage tasks.
experiment::Session experiment_session; // snapshot_lock
TaskHandle_t experiment_console_handle = nullptr;
std::atomic<bool> experiment_console_initialized{false}, experiment_console_ok{false};
std::atomic<bool> experiment_start_storage_ok{false}; // Storage verifies intent sidecar before epoch
char experiment_id[64]{}, experiment_csv[128]{}; // Storage writes once before SD_OK
std::uint64_t experiment_producers_done_us = 0; // snapshot_lock, actual last producer acknowledgement
void await_start();
bool capture_should_stop();
experiment::Observation experiment_observation() {
    portENTER_CRITICAL(&snapshot_lock);
    const auto value = experiment_session.observation();
    portEXIT_CRITICAL(&snapshot_lock); return value;
}
void experiment_stop_log(std::uint64_t now, experiment::Reason reason) {
    ESP_LOGW(tag, "EXPERIMENT_STOP_REQUEST actual_us=%" PRIu64 " reason=%s; finish in-flight records, wait producers/drain/close/readback",now,experiment::reason(reason));
}
bool experiment_request_stop(std::uint64_t now, experiment::Reason reason) {
    portENTER_CRITICAL(&snapshot_lock);
    const bool first = experiment_session.stop(now,reason);
    if (first) capture_window.request_stop(now);
    portEXIT_CRITICAL(&snapshot_lock);
    if (first) experiment_stop_log(now,reason);
    return first;
}
void experiment_fail(const char* why) {
    portENTER_CRITICAL(&snapshot_lock); experiment_session.fail(); portEXIT_CRITICAL(&snapshot_lock);
    ESP_LOGE(tag,"EXPERIMENT_FINALIZE_FAILED reason=%s; retain files/log; no safe-power-off promise",why);
}
void experiment_command(experiment::Request request, unsigned endpoint) {
    if (request.command == experiment::Command::None) return;
    capture_should_stop(); // elapsed deadline takes precedence if already observed now
    const auto now = static_cast<std::uint64_t>(esp_timer_get_time());
    if (request.command == experiment::Command::Start) {
        portENTER_CRITICAL(&snapshot_lock);
        const bool accepted = experiment_session.request_start(request.seconds);
        const auto state = experiment_session.observation().state;
        portEXIT_CRITICAL(&snapshot_lock);
        ESP_LOGI(tag,"EXP_ACK endpoint=%u command=START accepted=%d seconds=%u state=%s; accepted request is not BEGIN",endpoint,accepted,request.seconds,experiment::name(state));
    } else if (request.command == experiment::Command::Stop) {
        const bool first = experiment_request_stop(now,experiment::Reason::UserStop);
        ESP_LOGI(tag,"EXP_ACK endpoint=%u command=STOP first=%d state=%s; no state/reason reset",endpoint,first,experiment::name(experiment_observation().state));
    } else if (request.command == experiment::Command::Status) {
        const auto s = experiment_observation();
        ESP_LOGI(tag,"EXP_STATUS endpoint=%u state=%s requested_seconds=%u start_us=%" PRIu64 " stop_us=%" PRIu64 " reason=%s q=%u console_hwm_bytes=%u",endpoint,
            experiment::name(s.state),s.seconds,s.start_us,s.stop_us,experiment::reason(s.stopped_by),
            static_cast<unsigned>(uxQueueMessagesWaiting(storage_queue)),static_cast<unsigned>(uxTaskGetStackHighWaterMark(nullptr)));
    } else if (request.command == experiment::Command::Help) {
        ESP_LOGI(tag,"EXP_HELP EXP STATUS | EXP START [30..300 seconds, default120] | EXP STOP | EXP HELP; uppercase ASCII, max47 bytes, CR/LF; one experiment/boot; MARK NOT_IMPLEMENTED");
    } else ESP_LOGW(tag,"EXP_REJECT endpoint=%u parser_error=%u; no action; use EXP HELP",endpoint,static_cast<unsigned>(request.command));
}
void experiment_console_task(void*) {
    await_start();
    // SDK stdin is UART0; /dev/secondary is separately registered for USB
    // Serial/JTAG. No driver installation, pin changes, or output redirection.
    const int flags = fcntl(STDIN_FILENO,F_GETFL,0);
    const int primary = flags >= 0 && fcntl(STDIN_FILENO,F_SETFL,flags | O_NONBLOCK) == 0 ? STDIN_FILENO : -1;
    const int secondary = open("/dev/secondary",O_RDONLY | O_NONBLOCK);
    experiment_console_ok = primary >= 0 || secondary >= 0;
    experiment_console_initialized = true;
    ESP_LOGI(tag,"EXPERIMENT_CONSOLE primary_uart0=%d secondary_usb=%d stack_bytes=4096; RX path/COM mapping HARDWARE_NOT_RUN; max one reply per100ms",primary>=0,secondary>=0);
    static std::array<experiment::Parser,2> parser;
    const int endpoints[]{primary,secondary}; unsigned first = 0;
    for (;;) {
        bool replied = false;
        const auto now = static_cast<std::uint64_t>(esp_timer_get_time());
        for (unsigned offset = 0; offset < 2 && !replied; ++offset) {
            const auto i = (first+offset)%2;
            auto request = parser[i].expire(now);
            if (request.command != experiment::Command::None) { experiment_command(request,i);replied=true;break; }
            if (endpoints[i] < 0) continue;
            for (unsigned budget = 0; budget < 64; ++budget) {
                unsigned char ch;
                if (read(endpoints[i],&ch,1) != 1) break; // empty/disconnect cannot imply STOP
                request = parser[i].feed(ch,now);
                if (request.command != experiment::Command::None) { experiment_command(request,i);replied=true;break; }
            }
        }
        first = (first+1)%2;
        vTaskDelay(pdMS_TO_TICKS(100));
    }
}
