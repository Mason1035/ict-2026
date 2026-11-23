"""Causal, durable, display-only risk. Never mutates telemetry or creates alarms."""
from __future__ import annotations

import json
import math

from . import provisional_config as cfg
from .research_features import _angle as angle_between_vectors
from .dashboard import normalize_time_filter
from . import soil_calibration


def moisture_index(raw, channel):
    if channel not in cfg.SOIL_ENDPOINTS:
        return None, ["UNKNOWN_SOIL_CHANNEL"]
    if raw is None:
        return None, ["SOIL_MISSING"]
    dry, wet = cfg.SOIL_ENDPOINTS[channel]
    index = (dry - raw) / (dry - wet)
    return max(0.0, min(1.0, index)), (["SOIL_INDEX_CLIPPED"] if not 0 <= index <= 1 else [])


def rms(values):
    return math.hypot(*values) / math.sqrt(len(values)) if values else None


def map_level(features):
    """Return ordinal severity + explicit feature/threshold contributions."""
    reasons = []
    available = False
    severity = 0
    reference = cfg.reference_config()
    for sensor, metrics in features["imu"].items():
        for metric in ("direction_angle_deg", "vibration_rms_mps2", "gyro_rms_dps"):
            value = metrics[metric]
            if value is None:
                continue
            available = True
            threshold = reference["channels"]["imu_" + sensor]["metrics"][metric]["frozen_value"]
            rank = 2 if value > threshold * cfg.WARNING_REFERENCE_MULTIPLIER else 1 if value > threshold else 0
            if rank:
                severity = max(severity, rank)
                reasons.append({"feature": f"imu.{sensor}.{metric}", "value": value,
                    "attention_threshold": threshold,
                    "warning_threshold": threshold * cfg.WARNING_REFERENCE_MULTIPLIER,
                    "threshold_source": cfg.REFERENCE_PATH + f"#channels.imu_{sensor}.metrics.{metric}",
                    "severity_source": cfg.VERSION, "level": ("NORMAL", "ATTENTION", "WARNING")[rank]})
    level = ("NORMAL", "ATTENTION", "WARNING")[severity] if available else None
    return level, cfg.LEVEL_SCORES.get(level), reasons


def compute(payload, state=None, *, context=None):
    """Only current/past samples; caller partitions by site/device/boot/source/scope."""
    state = json.loads(json.dumps(state)) if state else {"imus": {}}
    firmware = (context or {}).get("firmware_elf_sha256")
    if "firmware_binding" not in state:
        state["firmware_binding"] = firmware
    if state["firmware_binding"] != firmware:
        state["firmware_binding_conflict"] = True
    now = payload["uptime_ms"]
    flags = ["SOIL_SEVERITY_NOT_CALIBRATED", "ONE_HZ_SAMPLED_NOT_HIGH_FREQUENCY_VIBRATION"]
    features = {"soil_index": {}, "imu": {}}
    percentages, quality, calibration = soil_calibration.evaluate(payload["soil"], context)
    calibration["session_identity"] = {key: payload[key] for key in ("site_id", "device_id", "boot_id")}
    calibration["session_binding_consistent"] = not state.get("firmware_binding_conflict", False)
    if state.get("firmware_binding_conflict"):
        percentages = dict.fromkeys(percentages)
        quality.append("FIRMWARE_DECLARATION_CHANGED_WITHIN_BOOT")
        calibration["applicable"] = False
    features["soil_w_rel_pct"] = percentages
    features["soil_index"] = {channel: value / 100 if value is not None else None for channel,value in percentages.items()}
    flags.extend(quality)
    window_ms = cfg.reference_config()["parameters"]["rms_window_us"] / 1000
    for imu in payload["imu"]:
        sensor = imu["id"]
        s = state["imus"].setdefault(sensor, {"baseline": [], "window": []})
        metrics = dict.fromkeys(("tilt_deg", "direction_angle_deg", "vibration_rms_mps2", "gyro_rms_dps"))
        features["imu"][sensor] = metrics
        vector = [imu[k] for k in ("ax", "ay", "az")]
        gyro = [imu[k] for k in ("gx", "gy", "gz")]
        if not imu["valid"] or any(v is None for v in vector) or math.hypot(*vector) <= 1e-12:
            s["window"] = []
            flags.append(f"imu.{sensor}:INVALID_ACCEL")
            continue
        metrics["tilt_deg"] = angle_between_vectors(vector, (0, 0, 1))
        if len(s["baseline"]) < cfg.BASELINE_SAMPLES:
            s["baseline"].append(vector)
        if len(s["baseline"]) == cfg.BASELINE_SAMPLES:
            baseline = [sum(v[i] for v in s["baseline"]) / cfg.BASELINE_SAMPLES for i in range(3)]
            metrics["direction_angle_deg"] = angle_between_vectors(vector, baseline)
        else:
            flags.append(f"imu.{sensor}:BASELINE_WARMUP")
        if s["window"] and now - s["window"][-1][0] > cfg.MAX_GAP_MS:
            s["window"] = []
            flags.append(f"imu.{sensor}:RMS_GAP_RESET")
        s["window"] = [v for v in s["window"] if now - window_ms < v[0] < now]
        s["window"].append([now, math.hypot(*vector) - cfg.GRAVITY_MPS2,
                            math.hypot(*gyro) if all(v is not None for v in gyro) else None])
        s["window"] = s["window"][-cfg.MAX_WINDOW_SAMPLES:]
        if len(s["window"]) >= cfg.MIN_RMS_SAMPLES:
            metrics["vibration_rms_mps2"] = rms([v[1] for v in s["window"]])
            if all(v[2] is not None for v in s["window"]):
                metrics["gyro_rms_dps"] = rms([v[2] for v in s["window"]])
        else:
            flags.append(f"imu.{sensor}:RMS_WARMUP")
    level, score, reasons = map_level(features)
    # A partial observation cannot establish safety; flags remain visible even at NORMAL.
    result = {"status": "PROVISIONAL", "calibration_version": None,
        "disclaimer": cfg.DISCLAIMER, "fusion_eligible": False, "uncalibrated": True,
        "production_alarm_eligible": False, "level": level, "score": score,
        "features": features, "reasons": reasons, "quality_flags": sorted(set(flags)),
        "threshold_provenance": cfg.provenance(), "soil_calibration": calibration}
    return result, state


def record(db, telemetry_id, payload, *, source, scope, received_at, context=None):
    """Called under intake transaction, isolated by its own savepoint.

    Store bounded rolling state with each result so restarts retain the baseline.
    Late/reversed observations get an unavailable result and cannot advance state.
    """
    with db.connection() as c:
        previous = c.execute("""SELECT p.state_json,t.seq,t.uptime_ms FROM provisional_risk p
            JOIN telemetry t ON t.id=p.telemetry_id
            WHERE t.site_id=? AND t.device_id=? AND t.boot_id=? AND t.source=? AND t.scope=?
            AND p.state_json IS NOT NULL ORDER BY t.seq DESC LIMIT 1""",
            (payload["site_id"], payload["device_id"], payload["boot_id"], source, scope)).fetchone()
        late = previous and (payload["seq"] <= previous["seq"] or payload["uptime_ms"] <= previous["uptime_ms"])
        result, state = compute(payload, json.loads(previous["state_json"]) if previous and not late else None, context=context)
        if late:
            result.update(level=None, score=None, reasons=[], features={"soil_index": {}, "soil_w_rel_pct": {}, "imu": {}})
            result["quality_flags"].append("OUT_OF_ORDER_NOT_EVALUATED")
        result.update(telemetry_id=telemetry_id, site_id=payload["site_id"], device_id=payload["device_id"],
            boot_id=payload["boot_id"], seq=payload["seq"], uptime_ms=payload["uptime_ms"],
            source=source, scope=scope, received_at=received_at)
        c.execute("INSERT INTO provisional_risk(telemetry_id,result_json,state_json) VALUES(?,?,?)",
                  (telemetry_id, json.dumps(result, allow_nan=False), None if late else json.dumps(state, allow_nan=False)))
        return result


def history(db, *, site_id, device_id, source=None, scope=None, boot_id=None, limit=120, before=None, after=None):
    where, args = ["t.site_id=?", "t.device_id=?"], [site_id, device_id]
    for name, value in (("source", source), ("scope", scope), ("boot_id", boot_id)):
        if value is not None:
            where.append(f"t.{name}=?")
            args.append(value)
    for op, value, field in (("<", before, "before"), (">=", after, "after")):
        if value is not None:
            where.append(f"t.received_at{op}?")
            args.append(normalize_time_filter(value, field))
    with db.connection() as c:
        rows = c.execute("SELECT p.result_json FROM provisional_risk p JOIN telemetry t ON t.id=p.telemetry_id WHERE "
                         + " AND ".join(where) + " ORDER BY p.rowid DESC LIMIT ?", (*args, limit)).fetchall()
    return {"items": [json.loads(row[0]) for row in rows]}


def latest(db, **filters):
    return next(iter(history(db, **filters, limit=1)["items"]), None)
