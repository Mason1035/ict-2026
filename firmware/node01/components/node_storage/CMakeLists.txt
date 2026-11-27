idf_component_register(SRCS "sd_card.cpp" "diagnostic_log.cpp" "storage_recovery.cpp" "experiment_metadata.cpp" INCLUDE_DIRS "include"
    REQUIRES node_drivers node_board fatfs sdmmc esp_driver_sdspi esp_driver_spi esp_timer)
