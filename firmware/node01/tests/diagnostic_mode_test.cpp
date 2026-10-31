#include "node/diagnostic_mode.hpp"
#include <cassert>
#include <cstring>

int main() {
    using namespace node::runtime::diagnostic;
    static_assert(sensors_enabled(Mode::Acquisition) && storage_enabled(Mode::Acquisition));
    static_assert(sensors_enabled(Mode::SensorsOnly) && !storage_enabled(Mode::SensorsOnly));
    static_assert(!sensors_enabled(Mode::StorageOnly) && storage_enabled(Mode::StorageOnly));
    static_assert(!isolated(Mode::Acquisition) && isolated(Mode::StorageOnly) && isolated(Mode::SensorsOnly));
    static_assert(sensors_enabled(Mode::SandboxExperiment) && storage_enabled(Mode::SandboxExperiment) && isolated(Mode::SandboxExperiment));
    assert(std::strcmp(name(Mode::SandboxExperiment),"SANDBOX_EXPERIMENT_CAPTURE")==0);
    assert(std::strcmp(source(Mode::SandboxExperiment),"REAL_SENSOR_EXPERIMENT_UNCALIBRATED")==0);
    assert(std::strcmp(source(Mode::StorageOnly), "SYNTHETIC") == 0);
    assert(std::strcmp(time_source(Mode::StorageOnly), "runtime_generation") == 0);
    assert(std::strcmp(time_source(Mode::Acquisition), "host_read_completion") == 0);
    assert(std::strstr(name(Mode::StorageOnly), "TEST_ONLY"));
    assert(std::strstr(name(Mode::SensorsOnly), "TEST_ONLY"));
    unsigned records = 0;
    for (unsigned cycle = 0; cycle < 100; ++cycle) records += 2 + probe_soil_records(cycle);
    assert(records == 206); // generator count, not a measured ESP32 production rate
}
