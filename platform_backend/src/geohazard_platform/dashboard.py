"""Read projections only. Original NODE payloads and unknown values stay intact."""
from __future__ import annotations
from datetime import datetime, timezone
import base64
import json

LEVELS = {"NORMAL": "low", "WATCH": "moderate", "WARNING": "high", "EMERGENCY": "critical"}


def parse_time(value):
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def project(row, freshness_seconds=30):
    item = dict(row)
    payload = json.loads(item["payload_json"])
    context = json.loads(item.get("context_json") or "{}")
    imus = [i for i in payload["imu"] if i.get("valid")]
    def maximum(field):
        values = [i[field] for i in imus if i.get(field) is not None]
        return max(values) if values else None
    vibration = maximum("vibration_rms")
    display = context.get("demo_sensors", {}) if item["source"] == "MOCK" and item["transport"] == "backend_demo" else {}
    sensors = {"moisture": payload["soil"].get("avg_pct"), "tilt": maximum("tilt_deg"),
               "vibration": vibration/9.80665 if vibration is not None else None,
               "rain": display.get("rain"), "crack": display.get("crack")}
    received = parse_time(item["received_at"])
    now = datetime.now(timezone.utc)
    arrival_age = max(0, (now-received).total_seconds())
    source_age = (now.timestamp()-item["source_time"]/1000) if payload["time_synced"] and item["source_time"] is not None else None
    clock_error = source_age is not None and source_age < -freshness_seconds
    age = max(arrival_age, source_age or 0)
    score = payload["risk"]["sensor_score"]
    # Baseline vision is an observation, not a calibrated geological score.
    risk = {"sensor_score": score, "vision_score": None, "final_score": score,
            "level": LEVELS.get(payload["risk"]["level"], "unknown") if score is not None else "unknown",
            "mode": "sensor_only" if score is not None else "unavailable",
            "reason": "MOCK 演示评分；视觉未标定" if item["source"] == "MOCK" else "使用设备上报风险；视觉未标定，未执行正式融合"}
    return {"id": item["id"], "site_id": item["site_id"], "device_id": item["device_id"],
            "source": item["source"], "scope": item["scope"], "received_at": item["received_at"],
            "source_time": item["source_time"], "time_synced": payload["time_synced"],
            "age_seconds": round(age, 1), "stale": age > freshness_seconds or clock_error,
            "arrival_age_seconds": round(arrival_age,1), "source_age_seconds": round(source_age,1) if source_age is not None else None,
            "clock_error": clock_error,
            "freshness_basis": "arrival_only" if not payload["time_synced"] else "source_and_arrival",
            "capture_time_known": payload["time_synced"],
            "sensors": sensors, "risk": risk, "system": payload["system"],
            "identity": {"device_id": item["device_id"], "boot_id": item["boot_id"], "seq": item["seq"]},
            "is_backfill": bool(item["is_backfill"]), "payload": payload}


def history(db, *, device_id, site_id=None, source=None, limit=120, before=None, after=None, cursor=None):
    clauses, args = ["device_id=?"], [device_id]
    for name, value in (("site_id", site_id), ("source", source)):
        if value is not None:
            clauses.append(f"{name}=?")
            args.append(value)
    if before:
        clauses.append("received_at<?")
        args.append(before)
    if after:
        clauses.append("received_at>=?")
        args.append(after)
    if cursor:
        try:
            stamp, identifier = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
            if not isinstance(stamp,str) or not isinstance(identifier,str):
                raise ValueError
        except Exception as exc:
            raise ValueError("无效的历史游标") from exc
        clauses.append("(received_at<? OR (received_at=? AND id<?))")
        args.extend((stamp,stamp,identifier))
    with db.connection() as c:
        rows = c.execute("SELECT * FROM telemetry WHERE " + " AND ".join(clauses) + " ORDER BY received_at DESC,id DESC LIMIT ?", (*args,limit+1)).fetchall()
    visible = rows[:limit]
    continuation=base64.urlsafe_b64encode(json.dumps([visible[-1]["received_at"],visible[-1]["id"]]).encode()).decode() if len(rows)>limit else None
    return {"items": [project(r) for r in visible], "next_cursor": continuation}


def latest(db, *, device_id, site_id=None, source=None, freshness_seconds=30):
    clauses, args = ["device_id=?", "is_current=1"], [device_id]
    for name, value in (("site_id",site_id),("source",source)):
        if value is not None:
            clauses.append(f"{name}=?")
            args.append(value)
    with db.connection() as c:
        row = c.execute("SELECT * FROM telemetry WHERE "+" AND ".join(clauses), args).fetchone()
    return project(row, freshness_seconds) if row else None
