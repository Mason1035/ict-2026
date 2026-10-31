idf_component_register(SRCS "runtime.cpp" INCLUDE_DIRS "include"
    REQUIRES node_board node_contracts node_logic node_drivers node_storage node_comm freertos esp_timer esp_system esp_app_format esp_driver_gpio)
