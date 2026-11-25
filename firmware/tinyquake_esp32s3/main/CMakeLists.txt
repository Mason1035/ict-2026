idf_component_register(SRCS "app_main.cc" "tinyquake_runner.cc" "model_data.cc"
                       INCLUDE_DIRS "."
                       PRIV_REQUIRES esp_wifi esp_event esp_netif nvs_flash mqtt json esp_timer)
