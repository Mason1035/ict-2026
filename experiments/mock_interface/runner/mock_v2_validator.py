"""TEST_ONLY / MOCK_ONLY / NOT_PRODUCTION_VALIDATOR.

Minimal direct-NODE v2 shape/types for offline fixtures. This is NOT He Yuxuan's
production Validator, not a new formal Schema, and contains no Risk policy.
"""

import math

MAX_INTEGER = 9007199254740991
TOP = {"schema", "site_id", "device_id", "boot_id", "seq", "timestamp_ms", "uptime_ms",
       "time_synced", "imu", "soil", "experiment", "risk", "system"}
IMU_NUMBERS = {"ax", "ay", "az", "gx", "gy", "gz", "tilt_deg", "tilt_rate_dps", "vibration_rms"}
SOIL_RAW = {"top_raw", "middle_raw", "toe_raw"}
SOIL_NUMBERS = {"top_pct", "middle_pct", "toe_pct", "avg_pct", "growth_pct_min"}
SYSTEM = {"wifi_up", "mqtt_up", "lora_ready", "sd_ok", "edge_online", "sensor_degraded"}


def validate(payload):
    """Return ACCEPT/REJECT with field errors; never repair or mutate input."""
    errors = []

    def error(path, code, detail):
        errors.append({"path": path, "code": code, "detail": detail})

    def obj(value, keys, path):
        if not isinstance(value, dict):
            error(path, "TYPE", "expected object")
            return False
        for key in sorted(keys - set(value)):
            error(path + "." + key, "REQUIRED", "missing required field")
        for key in sorted(set(value) - keys):
            error(path + "." + key, "UNKNOWN_FIELD", "not a current v2 field")
        return True

    def integer(value, path, nullable=False, low=0, high=MAX_INTEGER):
        if value is None and nullable:
            return
        if type(value) is not int:
            error(path, "TYPE", "expected integer" + (" or null" if nullable else ""))
        elif not low <= value <= high:
            error(path, "RANGE", "integer outside supported contract range")

    def number(value, path, low=None, high=None):
        if value is None:
            return
        if type(value) not in (int, float):
            error(path, "TYPE", "expected finite number or null")
        elif not math.isfinite(value):
            error(path, "NONFINITE", "NaN/Infinity are not JSON observations")
        elif (low is not None and value < low) or (high is not None and value > high):
            error(path, "RANGE", "number outside contract range")

    if obj(payload, TOP, "payload"):
        if payload.get("schema") != "zhifang.telemetry.v2":
            error("payload.schema", "SCHEMA_NAME", "expected zhifang.telemetry.v2")
        for key in ("site_id", "device_id"):
            if key in payload and (not isinstance(payload[key], str) or not payload[key].strip()):
                error("payload." + key, "TYPE", "expected nonempty string")
        for key in ("boot_id", "seq", "uptime_ms", "timestamp_ms"):
            if key in payload:
                integer(payload[key], "payload." + key, nullable=(key == "timestamp_ms"))
        if "time_synced" in payload and type(payload["time_synced"]) is not bool:
            error("payload.time_synced", "TYPE", "expected bool")
        imus = payload.get("imu")
        if not isinstance(imus, list) or len(imus) != 2:
            error("payload.imu", "TYPE", "expected top/toe array of size 2")
        else:
            for index, imu in enumerate(imus):
                loc = "payload.imu[%d]" % index
                if obj(imu, IMU_NUMBERS | {"id", "valid"}, loc):
                    if imu.get("id") != ("top", "toe")[index]:
                        error(loc + ".id", "POSITION", "expected top then toe")
                    if "valid" in imu and type(imu["valid"]) is not bool:
                        error(loc + ".valid", "TYPE", "expected bool; false is allowed")
                    for key in sorted(IMU_NUMBERS & set(imu)):
                        number(imu[key], loc + "." + key)
        soil = payload.get("soil")
        if obj(soil, SOIL_RAW | SOIL_NUMBERS, "payload.soil"):
            for key in sorted(SOIL_RAW & set(soil)):
                integer(soil[key], "payload.soil." + key, nullable=True, low=-32768, high=32767)
            for key in sorted(SOIL_NUMBERS & set(soil)):
                number(soil[key], "payload.soil." + key)
        risk = payload.get("risk")
        if obj(risk, {"sensor_score", "level", "reason_mask"}, "payload.risk"):
            if "sensor_score" in risk:
                number(risk["sensor_score"], "payload.risk.sensor_score", low=0, high=100)
            if "level" in risk and risk["level"] not in (None, "NORMAL", "WATCH", "WARNING", "EMERGENCY"):
                error("payload.risk.level", "ENUM", "expected null or an existing risk level")
            if "reason_mask" in risk:
                integer(risk["reason_mask"], "payload.risk.reason_mask", nullable=True)
        system = payload.get("system")
        if obj(system, SYSTEM, "payload.system"):
            for key in sorted(SYSTEM & set(system)):
                if type(system[key]) is not bool:
                    error("payload.system." + key, "TYPE", "expected bool")
        experiment = payload.get("experiment")
        if obj(experiment, {"run_id", "rain_level"}, "payload.experiment"):
            if "run_id" in experiment and experiment["run_id"] is not None and not isinstance(experiment["run_id"], str):
                error("payload.experiment.run_id", "TYPE", "expected string or null")
            if "rain_level" in experiment:
                integer(experiment["rain_level"], "payload.experiment.rain_level", nullable=True, high=3)
    return {"status": "REJECT" if errors else "ACCEPT", "errors": errors,
            "scope": "TEST_ONLY / MOCK_ONLY / NOT_PRODUCTION_VALIDATOR"}
