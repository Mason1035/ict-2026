idf_component_register(SRCS "telemetry.cpp" "identity.cpp" "network.cpp" INCLUDE_DIRS "include"
    REQUIRES node_contracts node_board node_drivers esp_wifi esp_netif esp_event nvs_flash mqtt esp_timer mbedtls)
