#include "node/board.hpp"
#include "node/runtime.hpp"
#include "esp_app_desc.h"
#include "esp_log.h"
#include "esp_system.h"

extern "C" void app_main() {
    constexpr const char* tag = "NODE-01";
    ESP_ERROR_CHECK(node::board::prepare_unverified_outputs());
    const auto* app = esp_app_get_description();
    ESP_LOGI(tag, "Zhishao disaster prevention / NODE-01 firmware=%s ESP-IDF=%s",
             app->version, esp_get_idf_version());
    ESP_LOGI(tag, "board=%s target=%s reset_reason=%d", node::board::identity,
             node::board::target, static_cast<int>(esp_reset_reason()));
    ESP_LOGW(tag, "boot_id=UNAVAILABLE; durable identity not implemented; publication DISABLED");
    ESP_LOGW(tag, "Outputs high impedance, polarity/external bias: TBD_HARDWARE_TEST");
    ESP_ERROR_CHECK(node::runtime::start());
    ESP_LOGI(tag, "NODE-01 firmware framework started; runtime skeleton=STARTED");
    ESP_LOGW(tag, "Hardware sensor drivers: NOT_VERIFIED");
    ESP_LOGW(tag, "Risk calibration: NOT_READY; sensor_score=null level=null reason_mask=null");
    ESP_LOGW(tag, "MQTT: NOT_CONNECTED; LoRa: NOT_VERIFIED; Storage: NOT_VERIFIED");
}
