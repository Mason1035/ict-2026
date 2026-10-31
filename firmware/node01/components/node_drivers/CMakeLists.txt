idf_component_register(SRCS "sensors.cpp" "i2c_bus.cpp" INCLUDE_DIRS "include"
    REQUIRES node_board node_contracts esp_driver_i2c esp_timer freertos)
