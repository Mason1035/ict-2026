idf_component_register(SRCS "telemetry.cpp" "identity.cpp" "network.cpp" INCLUDE_DIRS "include"
    REQUIRES node_contracts node_board node_drivers esp_wifi esp_netif esp_event nvs_flash esp_timer mqtt mbedtls freertos esp_hw_support)
if(CONFIG_NODE01_NETWORK_ENABLE)
    target_sources(${COMPONENT_LIB} PRIVATE "network_mqtt.cpp")
endif()

if(CONFIG_NODE01_MQTT_ONLY)
    target_sources(${COMPONENT_LIB} PRIVATE "mqtt_only.cpp")
endif()
