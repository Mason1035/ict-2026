#pragma once
#include <cstdint>

namespace node::drivers {
// Internal diagnostic-only executor metadata. Not a sampling/Telemetry field.
struct I2cTraceOperation {
    std::uint16_t length = 0;
    std::uint8_t address = 0, reg = 0;
    char operation = '?';
};
}
