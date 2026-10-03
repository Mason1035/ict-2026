idf_component_register(SRCS "runtime.cpp" INCLUDE_DIRS "include"
    REQUIRES node_board node_contracts node_logic freertos esp_timer esp_system)
