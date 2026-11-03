"""PROVISIONAL v1 R4-only threshold freezing; replaceable versioned JSON contract."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
import statistics

from .research_features import compute_features, validate_session
from .sd_replay import SENSORS


R4_EXPERIMENT_ID = "NODE01-2e379f02688fd631-N0000005.CSV"
SCHEMA_VERSION = "research-rule-config-v1"
METHOD_VERSION = "PROVISIONAL-v1"
REASON_KEYS = ("ORIENTATION_IMU_TOP", "ORIENTATION_IMU_TOE", "SOIL_TOP", "SOIL_MIDDLE",
               "SOIL_TOE", "VIBRATION_IMU_TOP", "VIBRATION_IMU_TOE")
DEFAULT_PARAMETERS = {
    "baseline_window_us": 10_000_000, "evaluation_step_us": 250_000,
    "gravity_tau_s": 1.0, "rms_window_us": 2_000_000,
    "sta_window_us": 1_000_000, "lta_window_us": 10_000_000,
    "imu_max_gap_us": 30_000, "imu_expected_interval_us": 10_000,
    "minimum_coverage": 0.9, "soil_max_gap_us": 1_500_000,
    "ain2_median_samples": 5, "ain2_adjacent_guard_adc": 1e30,
    "noise_floor_energy": {"imu_top": 1e-12, "imu_toe": 1e-12},
    "orientation_dwell_us": 3_000_000, "soil_dwell_us": 3_000_000,
    "vibration_dwell_us": 1_000_000, "recovery_dwell_us": 1_000_000,
    "recovery_ratio": 0.8,
}
METRICS = {
    "imu": {"direction_angle_deg": 1e-6, "tilt_rate_deg_s": 1e-6,
            "vibration_rms_mps2": 1e-9, "sta_lta": 1e-6,
            "gyro_rms_dps": 1e-6, "lta_energy": 1e-12},
    "soil": {"relative_change_fraction": 1e-6, "adc_rate_code_s": 1e-6,
             "adjacent_delta_adc_code": 1.0},
}


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"


def config_digest(config):
    return hashlib.sha256(canonical_json({k: v for k, v in config.items() if k != "config_sha256"}).encode()).hexdigest()


def describe(values, minimum_margin):
    values = sorted(abs(v) for v in values if v is not None)
    if len(values) < 20 or any(not math.isfinite(v) for v in values):
        raise ValueError("insufficient finite R4 observations to freeze a channel metric")
    median = statistics.median(values)
    mad = statistics.median(abs(v - median) for v in values)

    def quantile(q):
        pos = (len(values) - 1) * q
        lo = int(pos)
        return values[lo] + (values[min(lo + 1, len(values) - 1)] - values[lo]) * (pos - lo)

    return {"count": len(values), "median": median, "mad": mad,
            "p95": quantile(.95), "p99": quantile(.99), "maximum": values[-1],
            "minimum_margin": minimum_margin,
            "frozen_value": values[-1] + max(6 * 1.4826 * mad, minimum_margin),
            "method": "max(abs(R4)) + max(6 * 1.4826 * MAD(abs(R4)), minimum_margin)"}


def freeze_config(session, *, generated_at=None):
    """Only the designated R4 DTO is accepted; never inspect a rain session."""
    validate_session(session)
    m = session.metadata
    if m["experiment_id"] != R4_EXPERIMENT_ID or m["session_type"] != "post_rain_static":
        raise ValueError("PROVISIONAL v1 freezing accepts only designated R4 post_rain_static")
    if m.get("sensor_errors_present"):
        raise ValueError("R4 reference contains sensor errors")
    parameters = deepcopy(DEFAULT_PARAMETERS)
    initial = compute_features(session, parameters)
    guard = describe((x["values"].get("adjacent_delta_adc_code") for x in initial["soil_toe"]), 1.0)
    parameters["ain2_adjacent_guard_adc"] = guard["frozen_value"]
    for sensor in ("imu_top", "imu_toe"):
        lta = [x["values"]["lta_energy"] for x in initial[sensor] if x["state"] == "READY"]
        if not lta:
            raise ValueError("R4 has no covered IMU windows")
        parameters["noise_floor_energy"][sensor] = max(statistics.median(lta) * .1, 1e-12)
    features = compute_features(session, parameters)
    channels = {}
    for series in session.channels:
        ready = [x for x in features[series.sensor_id] if x["state"] == "READY"]
        if not ready or any(x["state"] in ("INVALID", "INSUFFICIENT_BASELINE")
                            for x in features[series.sensor_id]):
            raise ValueError("R4 reference has invalid/gapped/undefined channel baseline")
        channels[series.sensor_id] = {
            "metrics": {key: describe((x["values"].get(key) for x in ready), margin)
                        for key, margin in METRICS[series.kind].items()},
            "source_experiment_id": R4_EXPERIMENT_ID, "method_version": METHOD_VERSION,
        }
    # The guard includes adjacent differences during baseline warmup as well.
    channels["soil_toe"]["metrics"]["adjacent_delta_adc_code"] = guard
    timestamp = generated_at or datetime.now(timezone.utc).isoformat()
    if datetime.fromisoformat(timestamp.replace("Z", "+00:00")).tzinfo is None:
        raise ValueError("generated_at must include a timezone")
    config = {
        "schema_version": SCHEMA_VERSION, "method_version": METHOD_VERSION,
        "reference_version": "r4-post-rain-static-provisional-v1",
        "rule_version": "research-causal-rules-v1", "generated_at": timestamp,
        "scope": "RESEARCH", "uncalibrated": True,
        "source": {"experiment_id": R4_EXPERIMENT_ID, "session_type": m["session_type"],
                   "adapter_version": m["adapter_version"], "replay_id": m["replay_id"],
                   "file_sha256": deepcopy(m["integrity"]["file_sha256"]),
                   "quality_flags": list(m["quality_flags"])},
        "parameters": parameters, "channels": channels,
        "reason_definition_version": "PROVISIONAL-platform-reason-v1-awaiting-B",
        "reason_bits": {key: 1 << i for i, key in enumerate(REASON_KEYS)},
        "interpretation": "R4 is post-rain static, not a dry/calibrated baseline. Self-check is in-sample only.",
    }
    config["config_sha256"] = config_digest(config)
    validate_config(config)
    return config


def validate_config(config):
    """Check the data contract, independent of B's future method/bit assignments."""
    if not isinstance(config, dict):
        raise ValueError("research rule config must be an object")
    try:
        if (config["schema_version"] != SCHEMA_VERSION or config["scope"] != "RESEARCH"
                or config["uncalibrated"] is not True or config["config_sha256"] != config_digest(config)):
            raise ValueError("invalid research config schema/scope/digest")
        for key in ("method_version", "reference_version", "rule_version", "reason_definition_version", "generated_at"):
            if not isinstance(config[key], str) or not config[key]:
                raise ValueError("missing version/provenance")
        p = config["parameters"]
        if not isinstance(p, dict) or set(p) != set(DEFAULT_PARAMETERS):
            raise ValueError("unsupported parameter contract")
        for key, value in p.items():
            if key == "noise_floor_energy":
                if not isinstance(value, dict) or set(value) != {"imu_top", "imu_toe"}:
                    raise ValueError("noise floor channel contract")
                values = value.values()
            else:
                values = (value,)
            if any(isinstance(v, bool) or not isinstance(v, (float, int))
                   or not math.isfinite(v) or v <= 0 for v in values):
                raise ValueError("parameters must be finite and positive")
        if not (0 < p["recovery_ratio"] < 1 and 0 < p["minimum_coverage"] <= 1):
            raise ValueError("invalid ratio")
        if (not isinstance(p["ain2_median_samples"], int) or p["ain2_median_samples"] % 2 != 1):
            raise ValueError("AIN2 filter needs an odd sample count")
        if set(config["channels"]) != set(SENSORS.values()):
            raise ValueError("missing channel thresholds")
        for (kind, _), sensor in SENSORS.items():
            metrics = config["channels"][sensor]["metrics"]
            for key in METRICS[kind]:
                v = metrics[key]["frozen_value"]
                if isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) or v <= 0:
                    raise ValueError("invalid threshold")
        bits = config["reason_bits"]
        if (set(bits) != set(REASON_KEYS) or len(set(bits.values())) != len(bits)
                or any(type(v) is not int or v <= 0 or v & (v - 1) for v in bits.values())):
            raise ValueError("reason bits must be unique powers of two")
        if not config["source"]["file_sha256"] or not config["source"]["experiment_id"]:
            raise ValueError("missing source provenance")
    except (KeyError, TypeError, OverflowError) as exc:
        raise ValueError("malformed research rule config") from exc
