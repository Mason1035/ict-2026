#pragma once
#include "node/protocol.hpp"
#include "node/sampling.hpp"

namespace node {
enum class PortStatus { Disabled, NotImplemented, NotVerified, Unavailable, Ready, Error };
namespace drivers {
class Icm42688p {
public:
    virtual ~Icm42688p() = default;
    virtual PortStatus status() const = 0;
    virtual PortStatus read(sampling::ImuSite, sampling::ImuSample&) = 0;
};
class Ads1115 {
public:
    virtual ~Ads1115() = default;
    virtual PortStatus status() const = 0;
    // Separate short bus transactions. Release I2C mutex during ADC conversion.
    virtual PortStatus start_conversion(unsigned channel) = 0;
    virtual PortStatus try_read_conversion(sampling::SoilSample&) = 0;
};
class MicroSd {
public:
    virtual ~MicroSd() = default;
    virtual PortStatus status() const = 0;
    virtual PortStatus mount() = 0;
};
} // namespace drivers
namespace storage {
enum class RecordClass { Telemetry, Event, Alarm };
class Store {
public:
    virtual ~Store() = default;
    virtual PortStatus append(const protocol::MessageIdentity&, RecordClass,
                              const std::uint8_t*, std::size_t) = 0;
    // Event windows and durable offline_queue recovery are NOT implemented.
    // No deletion API until authenticated Atlas durable-receipt contract exists.
};
} // namespace storage
namespace app_mqtt { // document boundary: mqtt_client; avoids IDF name collision
class Transport {
public:
    virtual ~Transport() = default;
    virtual PortStatus status() const = 0;
    virtual PortStatus publish(const protocol::MessageIdentity&, std::string_view topic,
                               const std::uint8_t*, std::size_t) = 0;
};
} // namespace app_mqtt
namespace lora {
struct LoRaFrameV2; // TBD-11: intentionally incomplete, no packed layout/CRC/flags.
class Transport {
public:
    virtual ~Transport() = default;
    virtual PortStatus status() const = 0;
    virtual PortStatus send(const LoRaFrameV2&) = 0;
};
} // namespace lora
namespace comm_supervisor {
enum class LinkState { Disabled, Unavailable, Connecting, Available, Fault };
enum class Route { Unavailable, Primary, Backup, OfflineLocal };
struct State {
    LinkState mqtt = LinkState::Disabled;
    LinkState lora = LinkState::Disabled;
    bool edge_online = false;
    Route route = Route::Unavailable;
};
// Selection/reconnect/fallback timing require actual observed links; no fake FSM transitions.
} // namespace comm_supervisor
} // namespace node
