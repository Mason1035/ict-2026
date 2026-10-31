#include "node/board.hpp"
#include "node/runtime.hpp"
#include "esp_app_desc.h"
#include "esp_log.h"
#include "esp_system.h"
#include <cstdio>

extern "C" void app_main() {
    constexpr const char* tag = "NODE-01";
    ESP_ERROR_CHECK(node::board::prepare_unverified_outputs());
    const auto* app = esp_app_get_description();
    ESP_LOGI(tag, "Zhishao disaster prevention / NODE-01 firmware=%s ESP-IDF=%s",
             app->version, esp_get_idf_version());
    ESP_LOGI(tag, "board=%s target=%s reset_reason=%d", node::board::identity,
             node::board::target, static_cast<int>(esp_reset_reason()));
    char elf_sha256[65]{};
    for (unsigned i = 0; i < sizeof(app->app_elf_sha256); ++i)
        std::snprintf(elf_sha256 + 2*i, 3, "%02x", app->app_elf_sha256[i]);
    ESP_LOGI(tag, "DIAG_V6 app_elf_sha256=%s; gated DRDY startup + 4KiB writer/phase timing/256-row tail buffer; hardware NEED_HARDWARE_RETEST", elf_sha256);
    ESP_LOGW(tag, "Formal publication requires enabled network + provisioned persistent identity; no auto-seeding");
    ESP_LOGW(tag, "Outputs high impedance, polarity/external bias: TBD_HARDWARE_TEST");
    ESP_ERROR_CHECK(node::runtime::start());
    ESP_LOGI(tag, "NODE-01 V0.1 tasks started; sensor/SD initialization results follow asynchronously");
    ESP_LOGW(tag, "Patched firmware integration acceptance: NEED_HARDWARE_RETEST; prior first-board result was PARTIAL only");
    ESP_LOGW(tag, "Risk calibration: NOT_READY; sensor_score=null level=null reason_mask=null");
    ESP_LOGW(tag, "LoRa: NOT_IMPLEMENTED; Alarm GPIO disabled; diagnostic CSV is not an experimental dataset");
}
