#pragma once
#include "node/ports.hpp"
#include "esp_err.h"
#include "sdmmc_cmd.h"

namespace node::storage {
class SdCard final : public drivers::MicroSd {
public:
    PortStatus mount() override;
    // StorageTask must close every file before reset. Cleanup failure is latched:
    // the SDK may already have freed card resources even when unmount reports error.
    esp_err_t reset();
    PortStatus status() const override { return status_; }
    esp_err_t last_error() const { return error_; }
    static constexpr const char* mount_point = "/sdcard";
private:
    sdmmc_card_t* card_ = nullptr;
    PortStatus status_ = PortStatus::Unavailable;
    esp_err_t error_ = ESP_OK;
    esp_err_t cleanup_error_ = ESP_OK;
    bool spi_owned_ = false;
};
}
