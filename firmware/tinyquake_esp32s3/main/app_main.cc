#include "tinyquake_runner.h"
#include <cmath>
#include <cstdio>
#include <cstring>
#include <cstdlib>
#include <initializer_list>
#include "cJSON.h"
#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_random.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/task.h"
#include "mqtt_client.h"
#include "nvs_flash.h"
#include "sdkconfig.h"

namespace {
constexpr char kTag[]="tq-reference";
uint32_t boot_id;
uint32_t sequence=0;
#ifdef CONFIG_TINYQUAKE_MQTT_ENABLE
EventGroupHandle_t network;
constexpr EventBits_t kMqttReady=BIT0;
esp_mqtt_client_handle_t mqtt;
bool mqtt_started=false;
void wifi_event(void*,esp_event_base_t base,int32_t event,void*) {
    if (base==WIFI_EVENT && event==WIFI_EVENT_STA_DISCONNECTED) xEventGroupClearBits(network,kMqttReady);
    if (base==WIFI_EVENT && (event==WIFI_EVENT_STA_START || event==WIFI_EVENT_STA_DISCONNECTED)) esp_wifi_connect();
    if (base==IP_EVENT && event==IP_EVENT_STA_GOT_IP && !mqtt_started) { ESP_ERROR_CHECK(esp_mqtt_client_start(mqtt)); mqtt_started=true; }
}
void mqtt_event(void*,esp_event_base_t,int32_t event,void*) {
    if (event==MQTT_EVENT_CONNECTED) xEventGroupSetBits(network,kMqttReady);
    if (event==MQTT_EVENT_DISCONNECTED) xEventGroupClearBits(network,kMqttReady);
}
void start_network() {
    network=xEventGroupCreate();
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();
    const wifi_init_config_t init=WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&init));
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT,ESP_EVENT_ANY_ID,wifi_event,nullptr));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT,IP_EVENT_STA_GOT_IP,wifi_event,nullptr));
    wifi_config_t wifi={};
    strlcpy(reinterpret_cast<char*>(wifi.sta.ssid),CONFIG_TINYQUAKE_WIFI_SSID,sizeof(wifi.sta.ssid));
    strlcpy(reinterpret_cast<char*>(wifi.sta.password),CONFIG_TINYQUAKE_WIFI_PASSWORD,sizeof(wifi.sta.password));
    esp_mqtt_client_config_t config={};
    config.broker.address.uri=CONFIG_TINYQUAKE_BROKER_URI;
    config.credentials.username=CONFIG_TINYQUAKE_MQTT_USERNAME;
    config.credentials.authentication.password=CONFIG_TINYQUAKE_MQTT_PASSWORD;
    config.credentials.client_id=CONFIG_TINYQUAKE_DEVICE_ID;
    mqtt=esp_mqtt_client_init(&config);
    if (!mqtt) abort();
    ESP_ERROR_CHECK(esp_mqtt_client_register_event(mqtt,static_cast<esp_mqtt_event_id_t>(ESP_EVENT_ANY_ID),mqtt_event,nullptr));
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA,&wifi));
    ESP_ERROR_CHECK(esp_wifi_start());
}
#endif
void publish_reference(int index,const float scores[3],int64_t inference_us) {
    cJSON* body=cJSON_CreateObject();
    cJSON_AddStringToObject(body,"schema","zhifang.tinyquake.result.v1");
    cJSON_AddStringToObject(body,"site_id",CONFIG_TINYQUAKE_SITE_ID);
    cJSON_AddStringToObject(body,"device_id",CONFIG_TINYQUAKE_DEVICE_ID);
    cJSON_AddStringToObject(body,"sensor_id","reference");
    cJSON_AddNumberToObject(body,"boot_id",boot_id);
    cJSON_AddNumberToObject(body,"seq",++sequence);
    cJSON_AddStringToObject(body,"model_sha256",kTinyQuakeModelSha256);
    cJSON_AddStringToObject(body,"input_source","REFERENCE");
    cJSON_AddNumberToObject(body,"sample_rate_hz",40);
    cJSON_AddNumberToObject(body,"sample_count",80);
    cJSON_AddNumberToObject(body,"inference_us",static_cast<double>(inference_us));
    cJSON_AddBoolToObject(body,"quality_valid",true);
    cJSON_AddStringToObject(body,"quality_reason","reference_vector");
    cJSON_AddStringToObject(body,"preprocessing_id","tinyquake.reference.preprocessed.v1");
    cJSON_AddNumberToObject(body,"reference_index",kReferenceIndexes[index]);
    for (const char* name : {"window_start_uptime_ms","window_end_uptime_ms","frame_id","calibration_version"}) cJSON_AddNullToObject(body,name);
    cJSON* values=cJSON_AddArrayToObject(body,"probabilities");
    for (int i=0;i<3;++i) cJSON_AddItemToArray(values,cJSON_CreateNumber(scores[i]));
    char* encoded=cJSON_PrintUnformatted(body);
    if (encoded) {
        printf("TINYQUAKE_RESULT %s\n",encoded);
#ifdef CONFIG_TINYQUAKE_MQTT_ENABLE
        if (xEventGroupGetBits(network)&kMqttReady) {
            char topic[450];
            snprintf(topic,sizeof(topic),"zhifang/experimental/tinyquake/v1/%s/%s/reference/result",CONFIG_TINYQUAKE_SITE_ID,CONFIG_TINYQUAKE_DEVICE_ID);
            const int result=esp_mqtt_client_publish(mqtt,topic,encoded,0,0,0);
            if (result<0) ESP_LOGW(kTag,"MQTT publish not queued; no delivery claimed");
        } else ESP_LOGW(kTag,"MQTT not connected; serial result only");
#endif
        cJSON_free(encoded);
    }
    cJSON_Delete(body);
}
}

extern "C" void app_main() {
    ESP_LOGW(kTag,"EXPERIMENTAL REFERENCE INPUT ONLY; no ICM data, no risk score, no earthquake prediction");
    if (!tinyquake_init()) { ESP_LOGE(kTag,"Model initialization failed; stop"); return; }
    // Fail closed before publishing if reference outputs differ from desktop.
    for (int i=0;i<3;++i) {
        float scores[3]; int64_t elapsed;
        if (!tinyquake_infer_preprocessed(kReferenceInputs[i],scores,&elapsed)) return;
        for (int j=0;j<3;++j) if (std::abs(scores[j]-kReferenceOutputs[i][j])>1e-4f) {
            ESP_LOGE(kTag,"Reference parity failed index=%d class=%d; no MQTT output",i,j); return;
        }
    }
    ESP_LOGI(kTag,"Reference parity PASS (3 vectors, abs tolerance 1e-4); arena used=%u",static_cast<unsigned>(tinyquake_arena_used()));
    boot_id=esp_random();
#ifdef CONFIG_TINYQUAKE_MQTT_ENABLE
    const esp_err_t nvs=nvs_flash_init();
    // Do not erase existing NVS automatically; flashing is only for a spare board.
    if (nvs!=ESP_OK) { ESP_LOGE(kTag,"NVS init failed; network disabled without erasing storage"); return; }
    start_network();
#endif
    for (int i=0;;i=(i+1)%3) {
        float scores[3]; int64_t elapsed;
        if (tinyquake_infer_preprocessed(kReferenceInputs[i],scores,&elapsed)) publish_reference(i,scores,elapsed);
        else ESP_LOGE(kTag,"Invoke failed; result not published");
        vTaskDelay(pdMS_TO_TICKS(2000));
    }
}
