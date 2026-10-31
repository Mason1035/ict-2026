#pragma once
#include <cstdint>

namespace node::runtime::diagnostic {
enum class Mode { Acquisition, SensorsOnly, StorageOnly, SandboxExperiment };
constexpr bool sensors_enabled(Mode mode) { return mode != Mode::StorageOnly; }
constexpr bool storage_enabled(Mode mode) { return mode != Mode::SensorsOnly; }
constexpr bool isolated(Mode mode) { return mode != Mode::Acquisition; }
constexpr const char* name(Mode mode) {
    if (mode == Mode::SandboxExperiment) return "SANDBOX_EXPERIMENT_CAPTURE";
    return mode == Mode::SensorsOnly ? "SENSORS_ONLY_TEST_ONLY" :
        mode == Mode::StorageOnly ? "STORAGE_ONLY_SYNTHETIC_TEST_ONLY" : "ACQUISITION_DIAGNOSTIC";
}
constexpr const char* source(Mode mode) {
    if (mode == Mode::SandboxExperiment) return "REAL_SENSOR_EXPERIMENT_UNCALIBRATED";
    return mode == Mode::StorageOnly ? "SYNTHETIC" : "REAL_SENSOR_DIAGNOSTIC";
}
constexpr const char* time_source(Mode mode) {
    return mode == Mode::StorageOnly ? "runtime_generation" : "host_read_completion";
}
// 2 synthetic IMU records each 10ms loop, plus 3 synthetic Soil records each
// 50th loop: 103 records/0.5s at the target loop rate. No retrospective catch-up
// or made-up acquisition times: the runtime supplies its actual generation time.
constexpr unsigned probe_soil_records(std::uint32_t cycle) { return cycle % 50 == 0 ? 3 : 0; }
}
