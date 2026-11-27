constexpr EventBits_t bench_sd_ready=1U<<15, bench_sd_done=1U<<16;
struct SdBenchBlock {
    std::uint64_t write_us=0, sync_us=0, read_us=0, end_us=0;
    bool verified=false;
};
struct SdBenchResult {
    char path[32]{};
    std::uint32_t seed=0, expected_crc=0, actual_crc=0;
    std::size_t written=0, readback=0;
    unsigned blocks=0;
    bool eof=false;
    int error=0;
    esp_err_t unmount_rc=ESP_ERR_INVALID_STATE;
    const char* failed="none";
    std::uint64_t mount_start_us=0, mount_end_us=0, final_read_us=0, final_end_us=0;
    std::array<SdBenchBlock,sd_bench::total_blocks> steps{};
};
SdBenchResult bench_sd{};
esp_err_t bench_sd_mount_result=ESP_ERR_INVALID_STATE;

void bench_sd_fail(const char* stage, int error) {
    if (bench_sd.error) return;
    bench_sd.failed=stage;
    bench_sd.error=error ? error : EIO;
}
bool bench_sd_compare(const sd_bench::Block& bytes, unsigned block) {
    for (std::size_t index=0;index<bytes.size();++index)
        if (bytes[index]!=sd_bench::expected(bench_sd.seed,block,index)) return false;
    return true;
}
bool bench_sd_read_block(int file, sd_bench::Block& bytes, unsigned block) {
    const auto count=read(file,bytes.data(),bytes.size());
    if (count!=static_cast<ssize_t>(bytes.size())) {
        bench_sd_fail("read",count<0 ? errno : EIO);
        return false;
    }
    if (!bench_sd_compare(bytes,block)) {
        bench_sd_fail("compare",EIO);
        return false;
    }
    return true;
}
void bench_sd_capture() {
    static sd_bench::Block bytes{};
    bench_sd.seed=esp_random();
    std::snprintf(bench_sd.path,sizeof(bench_sd.path),"/sdcard/D%07lX.T18",
                  static_cast<unsigned long>(bench_sd.seed & 0x0fffffff));
    const auto epoch=capture_observation().started_us;
    auto expected_crc=0xffffffffU;
    for (unsigned block=0;block<sd_bench::total_blocks && !bench_sd.error;++block) {
        const auto target=epoch+block*1000000ULL;
        while (static_cast<std::uint64_t>(esp_timer_get_time())<target && !capture_should_stop()) vTaskDelay(1);
        if (capture_should_stop()) { bench_sd_fail("cutoff",ETIMEDOUT); break; }
        for (std::size_t index=0;index<bytes.size();++index)
            bytes[index]=sd_bench::expected(bench_sd.seed,block,index);
        if (capture_should_stop()) { bench_sd_fail("cutoff",ETIMEDOUT); break; }
        auto& step=bench_sd.steps[bench_sd.blocks++];
        step.write_us=esp_timer_get_time();
        const int writer=block ? open(bench_sd.path,O_WRONLY | O_APPEND) :
            open(bench_sd.path,O_CREAT | O_EXCL | O_WRONLY,0600);
        if (writer<0) bench_sd_fail(block ? "open_append" : "exclusive_open",errno);
        ssize_t count=-1;
        int write_error=0;
        if (writer>=0) {
            count=write(writer,bytes.data(),bytes.size());
            write_error=errno;
        }
        step.sync_us=esp_timer_get_time();
        if (count>0) bench_sd.written+=static_cast<std::size_t>(count);
        if (writer>=0) {
            if (count!=static_cast<ssize_t>(bytes.size())) bench_sd_fail("write",count<0 ? write_error : EIO);
            else if (fsync(writer)!=0) bench_sd_fail("fsync",errno);
            if (close(writer)!=0) bench_sd_fail("close_writer",errno);
        }
        step.read_us=esp_timer_get_time();
        if (!bench_sd.error) {
            expected_crc=sd_bench::add_crc(expected_crc,bytes);
            const int reader=open(bench_sd.path,O_RDONLY);
            const auto offset=static_cast<off_t>(block * bytes.size());
            if (reader<0) bench_sd_fail("reopen",errno);
            else {
                if (lseek(reader,offset,SEEK_SET)!=offset) bench_sd_fail("seek",errno);
                else step.verified=bench_sd_read_block(reader,bytes,block);
                if (close(reader)!=0) bench_sd_fail("close_reader",errno);
            }
        }
        step.end_us=esp_timer_get_time();
    }
    bench_sd.expected_crc=expected_crc ^ 0xffffffffU;
    if (bench_sd.error) return;
    // Final reopen after the capture cutoff. Independent of in-window reads.
    while (!capture_should_stop()) vTaskDelay(1);
    bench_sd.final_read_us=esp_timer_get_time();
    const int reader=open(bench_sd.path,O_RDONLY);
    if (reader<0) { bench_sd_fail("final_open",errno); return; }
    auto actual_crc=0xffffffffU;
    for (unsigned block=0;block<sd_bench::total_blocks && !bench_sd.error;++block) {
        if (bench_sd_read_block(reader,bytes,block)) {
            bench_sd.readback+=bytes.size();
            actual_crc=sd_bench::add_crc(actual_crc,bytes);
        }
    }
    if (!bench_sd.error) {
        std::uint8_t extra=0;
        const auto count=read(reader,&extra,1);
        bench_sd.eof=count==0;
        if (!bench_sd.eof) bench_sd_fail("eof",count<0 ? errno : EIO);
    }
    if (close(reader)!=0) bench_sd_fail("final_close",errno);
    bench_sd.final_end_us=esp_timer_get_time();
    bench_sd.actual_crc=actual_crc ^ 0xffffffffU;
    if (bench_sd.expected_crc!=bench_sd.actual_crc) bench_sd_fail("crc",EIO);
}
[[noreturn]] void bench_sd_task(void*) {
    await_start();
    const auto start=xEventGroupWaitBits(events,slow_initialized | startup_aborted,pdFALSE,pdFALSE,portMAX_DELAY);
    if (!(start & startup_aborted) && slow_startup.load()==startup::InitState::Ready) {
        storage::SdCard card;
        bench_sd.mount_start_us=esp_timer_get_time();
        const auto mounted=card.mount();
        bench_sd.mount_end_us=esp_timer_get_time();
        bench_sd_mount_result=mounted==PortStatus::Ready ? ESP_OK : card.last_error();
        ESP_LOGI(tag,"TOE_SD_MOUNT rc=%d start_us=%" PRIu64 " end_us=%" PRIu64,
                 bench_sd_mount_result,bench_sd.mount_start_us,bench_sd.mount_end_us);
        xEventGroupSetBits(events,bench_sd_ready);
        if (mounted==PortStatus::Ready) {
            const auto released=xEventGroupWaitBits(events,capture_ready | startup_aborted,pdFALSE,pdFALSE,portMAX_DELAY);
            if (!(released & startup_aborted)) bench_sd_capture();
            bench_sd.unmount_rc=card.reset();
        }
    }
    xEventGroupSetBits(events,bench_sd_done);
    for (;;) vTaskDelay(pdMS_TO_TICKS(1000));
}
void bench_sd_export() {
    for (unsigned block=0;block<bench_sd.blocks;++block) {
        const auto& step=bench_sd.steps[block];
        ESP_LOGI(tag,"TOE_SD_BLOCK seq=%u write_us=%" PRIu64 " sync_us=%" PRIu64 " read_us=%" PRIu64 " end_us=%" PRIu64 " verified=%d",
                 block+1,step.write_us,step.sync_us,step.read_us,step.end_us,step.verified);
        vTaskDelay(1);
    }
    ESP_LOGI(tag,"TOE_SD_RESULT kind=SYNTHETIC_TEST_ONLY path=%s seed=%08lx blocks=%u written=%u readback=%u eof=%d"
             " expected_crc=%08lx actual_crc=%08lx err=%d failed=%s unmount_rc=%d final_start_us=%" PRIu64 " final_end_us=%" PRIu64,
             bench_sd.path,static_cast<unsigned long>(bench_sd.seed),bench_sd.blocks,
             static_cast<unsigned>(bench_sd.written),static_cast<unsigned>(bench_sd.readback),bench_sd.eof,
             static_cast<unsigned long>(bench_sd.expected_crc),static_cast<unsigned long>(bench_sd.actual_crc),
             bench_sd.error,bench_sd.failed,bench_sd.unmount_rc,bench_sd.final_read_us,bench_sd.final_end_us);
    vTaskDelay(1);
}
