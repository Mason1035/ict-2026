"""Full direct-NODE v2 validation, durable intake, and transition alarms.

The existing Edge Intake remains the immutable snapshot boundary. This module
adds validation/storage around it; it does not invent B's calibration or LoRa's
unpublished binary layout. Risk values remain exactly the producer's values.
"""
from __future__ import annotations

import json
import math
from typing import Any
from uuid import uuid4

from edge_intake import receive_validated_telemetry
from edge_intake.intake import EdgeIntakeError
from .database import Database, utc_now

SCHEMA = "zhifang.telemetry.v2"
MAX_INTEGER = 9007199254740991
LEVELS = {"NORMAL": 0, "WATCH": 1, "WARNING": 2, "EMERGENCY": 3}
TOP = {"schema", "site_id", "device_id", "boot_id", "seq", "timestamp_ms", "uptime_ms", "time_synced", "imu", "soil", "experiment", "risk", "system"}
IMU_NUMBERS = {"ax", "ay", "az", "gx", "gy", "gz", "tilt_deg", "tilt_rate_dps", "vibration_rms"}
SOIL_RAW = {"top_raw", "middle_raw", "toe_raw"}
SOIL_NUMBERS = {"top_pct", "middle_pct", "toe_pct", "avg_pct", "growth_pct_min"}
SYSTEM = {"wifi_up", "mqtt_up", "lora_ready", "sd_ok", "edge_online", "sensor_degraded"}


def _is_finite_number(value: Any) -> bool:
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _valid_utf8(value: str) -> bool:
    try:
        value.encode("utf-8")
        return True
    except UnicodeError:
        return False


class IngestionError(ValueError):
    def __init__(self, status_code: int, detail: dict[str, Any] | str):
        self.status_code = status_code
        self.detail = detail if isinstance(detail, dict) else {"message": detail}
        super().__init__(self.detail["message"])


def validate_telemetry(payload: Any, *, topic: str | None = None) -> list[dict[str, str]]:
    """Validate the shared-contract full NODE profile without coercion/repair."""
    errors: list[dict[str, str]] = []

    def error(path: str, message: str) -> None:
        errors.append({"path": path, "message": message})

    def obj(value: Any, keys: set[str], path: str) -> bool:
        if not isinstance(value, dict):
            error(path, "expected object")
            return False
        for key in sorted(keys - set(value)):
            error(f"{path}.{key}", "required field")
        for key in set(value) - keys:
            error(path, "unknown field; transport and provenance belong in metadata")
        return True

    def integer(value: Any, path: str, nullable: bool = False, low: int = 0, high: int = MAX_INTEGER) -> None:
        if value is None and nullable:
            return
        if type(value) is not int or not low <= value <= high:
            error(path, f"expected integer {low}..{high}" + (" or null" if nullable else ""))

    def number(value: Any, path: str, low: float | None = None, high: float | None = None) -> None:
        if value is None:
            return
        if not _is_finite_number(value):
            error(path, "expected finite number or null")
        elif (low is not None and value < low) or (high is not None and value > high):
            error(path, "outside contract range")

    if not obj(payload, TOP, "payload"):
        return errors
    if payload.get("schema") != SCHEMA:
        error("payload.schema", f"must equal {SCHEMA}; LoRa partial profile is not implemented")
    for field in ("site_id", "device_id"):
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip() or len(value) > 128 or not _valid_utf8(value):
            error(f"payload.{field}", "expected nonempty UTF-8 string up to 128 characters")
        elif any(c in value for c in "/+#\x00"):
            error(f"payload.{field}", "must be a single MQTT topic segment")
    for field in ("boot_id", "seq", "uptime_ms", "timestamp_ms"):
        integer(payload.get(field), f"payload.{field}", nullable=field == "timestamp_ms")
    if type(payload.get("time_synced")) is not bool:
        error("payload.time_synced", "expected bool")
    elif payload["time_synced"] is False and payload.get("timestamp_ms") is not None:
        error("payload.timestamp_ms", "unsynchronized NODE time must be null")
    elif payload["time_synced"] is True and payload.get("timestamp_ms") is None:
        error("payload.timestamp_ms", "synchronized NODE time requires a UTC timestamp")
    imus = payload.get("imu")
    if not isinstance(imus, list) or len(imus) != 2:
        error("payload.imu", "expected top/toe array of size two")
    else:
        for i, imu in enumerate(imus):
            path = f"payload.imu[{i}]"
            if obj(imu, IMU_NUMBERS | {"id", "valid"}, path):
                if imu.get("id") != ("top", "toe")[i]:
                    error(f"{path}.id", "expected top followed by toe")
                if type(imu.get("valid")) is not bool:
                    error(f"{path}.valid", "expected bool in the full NODE profile")
                for field in IMU_NUMBERS:
                    number(imu.get(field), f"{path}.{field}")
                    if imu.get("valid") is False and imu.get(field) is not None:
                        error(f"{path}.{field}", "invalid IMU observations must be null")
    soil = payload.get("soil")
    if obj(soil, SOIL_RAW | SOIL_NUMBERS, "payload.soil"):
        for field in SOIL_RAW:
            integer(soil.get(field), f"payload.soil.{field}", nullable=True, low=-32768, high=32767)
        for field in SOIL_NUMBERS:
            number(soil.get(field), f"payload.soil.{field}", low=None if field == "growth_pct_min" else 0, high=None if field == "growth_pct_min" else 100)
    risk = payload.get("risk")
    if obj(risk, {"sensor_score", "level", "reason_mask"}, "payload.risk"):
        number(risk.get("sensor_score"), "payload.risk.sensor_score", 0, 100)
        if risk.get("level") is not None and (not isinstance(risk["level"], str) or risk["level"] not in LEVELS):
            error("payload.risk.level", "expected null or NORMAL/WATCH/WARNING/EMERGENCY")
        integer(risk.get("reason_mask"), "payload.risk.reason_mask", nullable=True)
        score = risk.get("sensor_score")
        if _is_finite_number(score) and 0 <= score <= 100:
            expected = "NORMAL" if score < 30 else "WATCH" if score < 60 else "WARNING" if score < 80 else "EMERGENCY"
            if risk.get("level") is not None and risk["level"] != expected:
                error("payload.risk.level", "level disagrees with shared-contract score boundaries")
    system = payload.get("system")
    if obj(system, SYSTEM, "payload.system"):
        for field in SYSTEM:
            if type(system.get(field)) is not bool:
                error(f"payload.system.{field}", "expected bool in the full NODE profile")
    experiment = payload.get("experiment")
    if obj(experiment, {"run_id", "rain_level"}, "payload.experiment"):
        if experiment.get("run_id") is not None and (not isinstance(experiment["run_id"], str) or len(experiment["run_id"]) > 256 or not _valid_utf8(experiment["run_id"])):
            error("payload.experiment.run_id", "expected UTF-8 string up to 256 characters or null")
        integer(experiment.get("rain_level"), "payload.experiment.rain_level", nullable=True, high=3)
    if topic is not None and topic != f"zhifang/v2/{payload.get('site_id')}/{payload.get('device_id')}/telemetry":
        error("topic", "MQTT topic site/device must match payload identity")
    return errors


def quarantine_message(db: Database, raw: Any, *, source: str, scope: str, transport: str, reason: str, connector_id: str | None = None, topic: str | None = None) -> str:
    identifier = str(uuid4())
    if isinstance(raw, bytes):
        raw_text = raw.decode("utf-8", errors="replace")
    elif isinstance(raw, str):
        raw_text = raw
    else:
        raw_text = json.dumps(raw, ensure_ascii=True, default=str)
    # Bound rejected raw data so a bad publisher cannot exhaust local storage per message.
    raw_text = raw_text.encode("utf-8", errors="backslashreplace").decode("utf-8")[:262144]
    with db.connection() as connection:
        connection.execute("INSERT INTO quarantine(id,source,scope,transport,connector_id,topic,raw_payload,reason,created_at) VALUES(?,?,?,?,?,?,?,?,?)", (identifier, source, scope, transport, connector_id, topic, raw_text, reason[:4096], utc_now()))
    return identifier


def ingest_telemetry(db: Database, payload: Any, *, source: str = "MOCK", scope: str = "TEST_ONLY", transport: str = "http_test", connector_id: str | None = None, topic: str | None = None, context: dict[str, Any] | None = None) -> dict[str, Any]:
    if source not in {"MOCK", "REAL"}:
        raise IngestionError(422, "backend provenance must be MOCK or REAL")
    errors = validate_telemetry(payload, topic=topic)
    if errors:
        quarantine_id = quarantine_message(db, payload, source=source, scope=scope, transport=transport, connector_id=connector_id, topic=topic, reason=json.dumps(errors, ensure_ascii=False))
        raise IngestionError(422, {"message": "Telemetry v2 validation failed", "errors": errors, "quarantine_id": quarantine_id})
    try:
        receipt = receive_validated_telemetry(payload, context={**(context or {}), "source": source, "scope": scope, "transport": transport, "connector_id": connector_id, "topic": topic})
    except EdgeIntakeError as exc:
        quarantine_id = quarantine_message(db, payload, source=source, scope=scope, transport=transport, connector_id=connector_id, topic=topic, reason=str(exc))
        raise IngestionError(422, {"message": "Telemetry payload and context must contain finite UTF-8 JSON values", "quarantine_id": quarantine_id}) from exc
    snapshot = receipt["payload"]
    original = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    identity = {field: snapshot[field] for field in ("site_id", "device_id", "boot_id", "seq")}
    now = utc_now()
    receipt_id = str(uuid4())
    sidecar_json = json.dumps(receipt["context"], ensure_ascii=False)
    conflict: str | None = None
    result: dict[str, Any] | None = None
    with db.connection() as connection:
        old = connection.execute("SELECT * FROM telemetry WHERE device_id=? AND boot_id=? AND seq=?", (snapshot["device_id"], snapshot["boot_id"], snapshot["seq"])).fetchone()
        if old:
            if old["payload_json"] == original and old["source"] == source:
                connection.execute("INSERT INTO intake_receipts(id,telemetry_id,status,source,scope,transport,connector_id,topic,context_json,received_at) VALUES(?,?,?,?,?,?,?,?,?,?)", (receipt_id, old["id"], "duplicate", source, scope, transport, connector_id, topic, sidecar_json, now))
                return {"receipt_id": receipt_id, "status": "duplicate", "telemetry_id": old["id"], "identity": identity, "source": old["source"], "scope": old["scope"], "durable": True, "node_cleanup_authorized": False, "risk": snapshot["risk"]}
            conflict = "same device/boot/seq already exists with different payload or provenance"
        registered = connection.execute("SELECT site_id,source FROM telemetry WHERE device_id=? LIMIT 1", (snapshot["device_id"],)).fetchone()
        if registered and (registered["site_id"] != snapshot["site_id"] or registered["source"] != source):
            conflict = "device_id is globally unique; site/provenance does not match existing registration"
        if conflict is None:
            previous = connection.execute("SELECT * FROM telemetry WHERE device_id=? AND is_current=1", (snapshot["device_id"],)).fetchone()
            session = connection.execute("SELECT ordinal FROM boot_sessions WHERE device_id=? AND boot_id=?", (snapshot["device_id"], snapshot["boot_id"])).fetchone()
            connection.execute("INSERT OR IGNORE INTO boot_sessions(device_id,boot_id,first_seen) VALUES(?,?,?)", (snapshot["device_id"], snapshot["boot_id"], now))
            current = previous is None
            if previous is not None:
                if previous["boot_id"] == snapshot["boot_id"]:
                    current = snapshot["seq"] > previous["seq"] and snapshot["uptime_ms"] >= previous["uptime_ms"]
                elif session is None:
                    current = not (snapshot["timestamp_ms"] is not None and previous["source_time"] is not None and snapshot["timestamp_ms"] < previous["source_time"])
            identifier = str(uuid4())
            if current:
                connection.execute("UPDATE telemetry SET is_current=0 WHERE device_id=? AND is_current=1", (snapshot["device_id"],))
            connection.execute("INSERT INTO telemetry(id,site_id,device_id,boot_id,seq,source,scope,transport,connector_id,topic,payload_json,context_json,source_time,uptime_ms,received_at,is_current,is_backfill) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (identifier, snapshot["site_id"], snapshot["device_id"], snapshot["boot_id"], snapshot["seq"], source, scope, transport, connector_id, topic, original, sidecar_json, snapshot["timestamp_ms"], snapshot["uptime_ms"], now, int(current), int(not current)))
            connection.execute("INSERT INTO intake_receipts(id,telemetry_id,status,source,scope,transport,connector_id,topic,context_json,received_at) VALUES(?,?,?,?,?,?,?,?,?,?)", (receipt_id, identifier, "accepted", source, scope, transport, connector_id, topic, sidecar_json, now))
            level = snapshot["risk"]["level"]
            # Compare the most recent *known* risk in the active boot. Unknown
            # readings do not clear an alarm or reset the escalation baseline.
            known = connection.execute("SELECT payload_json FROM telemetry WHERE device_id=? AND is_backfill=0 AND id<>? AND json_extract(payload_json,'$.risk.level') IS NOT NULL ORDER BY rowid DESC LIMIT 1", (snapshot["device_id"], identifier)).fetchone()
            previous_level = json.loads(known["payload_json"])["risk"]["level"] if known else None
            alarm_id = None
            if current and level is not None and LEVELS.get(level, -1) > max(0, LEVELS.get(previous_level, -1)):
                alarm_id = str(uuid4())
                reason = f"Producer-reported risk escalated to {level}; calibration is owned by the producer"
                connection.execute("INSERT INTO alarms(id,site_id,device_id,source,level,score,reason,source_message_id,created_at) VALUES(?,?,?,?,?,?,?,?,?)", (alarm_id, snapshot["site_id"], snapshot["device_id"], source, level, snapshot["risk"]["sensor_score"], reason, identifier, now))
                connection.execute("INSERT INTO events(id,kind,message,site_id,device_id,source,details_json,created_at) VALUES(?,?,?,?,?,?,?,?)", (str(uuid4()), "risk_escalation", reason, snapshot["site_id"], snapshot["device_id"], source, json.dumps({"telemetry_id": identifier, "alarm_id": alarm_id, "risk": snapshot["risk"]}), now))
            result = {"receipt_id": receipt_id, "status": "accepted", "telemetry_id": identifier, "identity": identity, "source": source, "scope": scope, "durable": True, "node_cleanup_authorized": False, "risk": snapshot["risk"], "is_current": current, "is_backfill": not current, "alarm_id": alarm_id}
    if conflict is not None:
        quarantine_id = quarantine_message(db, payload, source=source, scope=scope, transport=transport, connector_id=connector_id, topic=topic, reason=conflict)
        raise IngestionError(409, {"message": conflict, "quarantine_id": quarantine_id})
    assert result is not None
    return result
