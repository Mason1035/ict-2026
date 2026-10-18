#pragma once
#include <array>
#include <cstdint>
#include "esp_err.h"

namespace node::board {
// Sole source of application pin/bus numbers; SSOT 00, baseline 1.0, section 4.
inline constexpr char device_id[] = "NODE-01";
inline constexpr char target[] = "esp32s3";
inline constexpr char identity[] = "ESP32-S3-DevKitC-1 v1.1 / WROOM-1 N8R8";
inline constexpr unsigned flash_mb = 8, psram_mb = 8;
namespace pin {
inline constexpr int imu_top_int1 = 4, imu_toe_int1 = 5;
inline constexpr int buzzer = 6, lora_aux = 7;
inline constexpr int i2c_sda = 8, i2c_scl = 9;
inline constexpr int sd_cs = 10, sd_mosi = 11, sd_sclk = 12, sd_miso = 13;
inline constexpr int siren_out = 14, lora_m0 = 15, lora_m1 = 16;
inline constexpr int lora_tx = 17, lora_rx = 18;
inline constexpr int user_button = 21, board_rgb = 38;
inline constexpr std::array<int, 2> spare{1, 2};
inline constexpr std::array<int, 2> reserved{47, 48};
inline constexpr std::array<int, 4> jtag{39, 40, 41, 42};
inline constexpr std::array<int, 2> uart0{43, 44};
inline constexpr std::array<int, 2> usb{19, 20};
inline constexpr std::array<int, 3> psram_internal{35, 36, 37};
inline constexpr std::array<int, 4> strapping{0, 3, 45, 46};
inline constexpr std::array<int, 17> assigned{
    imu_top_int1, imu_toe_int1, buzzer, lora_aux, i2c_sda, i2c_scl,
    sd_cs, sd_mosi, sd_sclk, sd_miso, siren_out, lora_m0, lora_m1,
    lora_tx, lora_rx, user_button, board_rgb};
constexpr bool assignments_valid() {
    for (unsigned i = 0; i < assigned.size(); ++i) {
        for (unsigned j = i + 1; j < assigned.size(); ++j)
            if (assigned[i] == assigned[j]) return false;
        for (int p : psram_internal) if (assigned[i] == p) return false;
        for (int p : strapping) if (assigned[i] == p) return false;
        for (int p : reserved) if (assigned[i] == p) return false;
        for (int p : jtag) if (assigned[i] == p) return false;
        for (int p : uart0) if (assigned[i] == p) return false;
        for (int p : usb) if (assigned[i] == p) return false;
    }
    return true;
}
static_assert(assignments_valid(), "Invalid or conflicting business GPIO");
} // namespace pin
namespace bus {
inline constexpr std::uint32_t i2c_hz = 400000;
inline constexpr std::uint8_t imu_top_address = 0x68, imu_toe_address = 0x69;
inline constexpr std::uint8_t ads1115_address = 0x48, optional_ssd1306_address = 0x3c;
inline constexpr unsigned soil_top_channel = 0, soil_middle_channel = 1;
inline constexpr unsigned soil_toe_channel = 2, ads_reserved_channel = 3;
inline constexpr std::uint32_t sd_initial_hz = 20000000;
inline constexpr unsigned lora_uart = 1, lora_baud = 9600;
inline constexpr unsigned lora_data_bits = 8, lora_stop_bits = 1;
inline constexpr bool lora_parity_enabled = false;
} // namespace bus
// High impedance/no pulls: no assertion about external load OFF or E220 mode.
// TBD_HARDWARE_TEST: external bias, power-up transient and output polarity.
esp_err_t prepare_unverified_outputs();
} // namespace node::board
