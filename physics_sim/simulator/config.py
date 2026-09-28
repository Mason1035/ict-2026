"""Strict, explicit V0.1.1 configuration with no implicit physics defaults."""

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path

import yaml

from physics_sim import __version__

STATES = ("NORMAL", "SATURATION", "CREEP", "INCIPIENT_SLIP", "FAILURE")
SOIL_SITES = ("top", "middle", "toe")
IMU_SITES = ("top", "toe")
# These tolerances address floating-point representation, not physical thresholds.
GRID_TOLERANCE = 1e-9


class ConfigError(ValueError):
    """A configuration cannot be interpreted safely."""


class _UniqueLoader(yaml.SafeLoader):
    """Reject duplicate YAML keys instead of silently losing parameters."""


def _unique_mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str):
            raise ConfigError("YAML keys must be strings")
        if key in result:
            raise ConfigError(f"duplicate YAML key: {key}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)


def _keys(value, expected, path):
    if not isinstance(value, dict):
        raise ConfigError(f"{path}: expected mapping")
    if set(value) != set(expected):
        missing = set(expected) - set(value)
        extra = set(value) - set(expected)
        raise ConfigError(f"{path}: missing={sorted(missing)}, unknown={sorted(extra, key=str)}")


def _number(value, path, minimum=None, maximum=None, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{path}: expected finite number")
    try:
        value = float(value)
    except OverflowError as exc:
        raise ConfigError(f"{path}: expected finite number") from exc
    if not math.isfinite(value):
        raise ConfigError(f"{path}: expected finite number")
    if positive and value <= 0:
        raise ConfigError(f"{path}: must be > 0")
    if minimum is not None and value < minimum:
        raise ConfigError(f"{path}: must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise ConfigError(f"{path}: must be <= {maximum}")
    return value


def grid_steps(seconds, dt, path):
    quotient = seconds / dt
    if not math.isfinite(quotient) or not math.isclose(
        quotient, round(quotient), rel_tol=0, abs_tol=GRID_TOLERANCE
    ):
        raise ConfigError(f"{path}: must be an integer multiple of dt_s")
    return round(quotient)


def validate_config(raw):
    """Return a detached, normalized config; reject typos and invalid units/ranges."""
    c = deepcopy(raw)
    _keys(c, ("simulator_version", "seed", "simulation", "slope", "soil", "rain", "state_model", "sensor"), "config")
    if c["simulator_version"] != __version__:
        raise ConfigError(f"simulator_version: expected {__version__}")
    if type(c["seed"]) is not int or c["seed"] < 0:
        raise ConfigError("seed: expected nonnegative integer")
    _keys(c["simulation"], ("duration_s", "dt_s"), "simulation")
    for key in ("duration_s", "dt_s"):
        c["simulation"][key] = _number(c["simulation"][key], f"simulation.{key}", positive=True)
    dt = c["simulation"]["dt_s"]
    duration = c["simulation"]["duration_s"]
    if grid_steps(duration, dt, "simulation.duration_s") < 1:
        raise ConfigError("simulation.duration_s: must be >= dt_s")
    _keys(c["slope"], ("theta_deg",), "slope")
    c["slope"]["theta_deg"] = _number(c["slope"]["theta_deg"], "slope.theta_deg", 0, 90)
    _keys(c["soil"], ("initial_moisture", "infiltration_rate", "drainage_rate"), "soil")
    for key in c["soil"]:
        c["soil"][key] = _number(c["soil"][key], f"soil.{key}", 0, 1 if key == "initial_moisture" else None)
    _keys(c["rain"], ("type", "start_s", "end_s", "intensity"), "rain")
    if c["rain"]["type"] not in ("none", "constant"):
        raise ConfigError("rain.type: expected none or constant")
    for key in ("start_s", "end_s", "intensity"):
        c["rain"][key] = _number(c["rain"][key], f"rain.{key}", 0)
    start, end = c["rain"]["start_s"], c["rain"]["end_s"]
    if not 0 <= start <= end <= duration:
        raise ConfigError("rain: require 0 <= start_s <= end_s <= duration_s")
    for key in ("start_s", "end_s"):
        grid_steps(c["rain"][key], dt, f"rain.{key}")
    if c["rain"]["type"] == "none" and c["rain"]["intensity"] != 0:
        raise ConfigError("rain.intensity: must be 0 for type none")
    if c["rain"]["type"] == "constant" and (start == end or c["rain"]["intensity"] <= 0):
        raise ConfigError("rain: constant requires end_s > start_s and intensity > 0")
    model = c["state_model"]
    thresholds = ("saturation_threshold", "creep_threshold", "slip_threshold", "failure_threshold")
    rates = ("creep_rate", "slip_rate", "failure_rate")
    _keys(model, thresholds + rates, "state_model")
    for key in thresholds:
        model[key] = _number(model[key], f"state_model.{key}", 0, 1, positive=True)
    if any(model[a] >= model[b] for a, b in zip(thresholds, thresholds[1:])):
        raise ConfigError("state_model: require saturation < creep < slip < failure")
    for key in rates:
        model[key] = _number(model[key], f"state_model.{key}", positive=True)
    if not model["creep_rate"] < model["slip_rate"] < model["failure_rate"]:
        raise ConfigError("state_model: require 0 < creep_rate < slip_rate < failure_rate")
    sensor = c["sensor"]
    _keys(sensor, ("imu_noise_std", "soil_noise_std", "vibration_noise_std", "soil_sites", "imu_sites"), "sensor")
    for key in ("imu_noise_std", "soil_noise_std", "vibration_noise_std"):
        sensor[key] = _number(sensor[key], f"sensor.{key}", 0)
    _keys(sensor["soil_sites"], SOIL_SITES, "sensor.soil_sites")
    for site, p in sensor["soil_sites"].items():
        path = f"sensor.soil_sites.{site}"
        _keys(p, ("response_coefficient", "delay_s"), path)
        p["response_coefficient"] = _number(p["response_coefficient"], f"{path}.response_coefficient", 0, 1)
        p["delay_s"] = _number(p["delay_s"], f"{path}.delay_s", 0, duration)
        grid_steps(p["delay_s"], dt, f"{path}.delay_s")
    _keys(sensor["imu_sites"], IMU_SITES, "sensor.imu_sites")
    for site, p in sensor["imu_sites"].items():
        path = f"sensor.imu_sites.{site}"
        _keys(p, ("base_tilt_deg", "tilt_gain_deg_per_m", "vibration_base_mps2", "vibration_gain_per_s"), path)
        p["base_tilt_deg"] = _number(p["base_tilt_deg"], f"{path}.base_tilt_deg")
        for key in ("tilt_gain_deg_per_m", "vibration_base_mps2", "vibration_gain_per_s"):
            p[key] = _number(p[key], f"{path}.{key}", 0)
    return c


def load_config(path):
    try:
        with Path(path).open(encoding="utf-8") as stream:
            raw = yaml.load(stream, Loader=_UniqueLoader)
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML: {exc}") from exc
    return validate_config(raw)


def parameter_hash(config):
    # Hash the validated full config (including seed/version), independent of YAML
    # formatting, mapping order, timestamps and output paths. Numeric normalization
    # makes 1 and 1.0 equivalent for continuous parameters; SHA-256 is not a run ID.
    normalized = validate_config(config)
    canonical = json.dumps(normalized, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
