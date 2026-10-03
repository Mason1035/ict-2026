#include "node/board.hpp"
#include "driver/gpio.h"

namespace node::board {
esp_err_t prepare_unverified_outputs() {
    gpio_config_t config{};
    for (int p : {pin::buzzer, pin::siren_out, pin::lora_m0, pin::lora_m1,
                  pin::lora_aux, pin::lora_tx, pin::lora_rx})
        config.pin_bit_mask |= (std::uint64_t{1} << p);
    config.mode = GPIO_MODE_INPUT;
    config.pull_up_en = GPIO_PULLUP_DISABLE;
    config.pull_down_en = GPIO_PULLDOWN_DISABLE;
    config.intr_type = GPIO_INTR_DISABLE;
    return gpio_config(&config);
}
} // namespace node::board
