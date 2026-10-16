"""Explicit MOCK/TEST_ONLY source, persisted independently of operational devices."""
from __future__ import annotations

import json
from threading import RLock
from .database import Database, utc_now
from .telemetry import ingest_telemetry

SITE = "DEMO"
DEVICE = "DEMO-NODE-01"
SCENARIOS = {
    "A": {"moisture": 42.0, "tilt": 6.5, "vibration": .18, "rain": 8.0, "crack": 1.2},
    "B": {"moisture": 71.0, "tilt": 10.8, "vibration": .27, "rain": 43.0, "crack": 2.4},
    "C": {"moisture": 78.0, "tilt": 18.6, "vibration": .52, "rain": 36.0, "crack": 5.8},
    "D": {"moisture": 91.0, "tilt": 26.4, "vibration": .94, "rain": 67.0, "crack": 11.2},
}
RANGES = {"moisture": 100, "tilt": 45, "vibration": 2, "rain": 100, "crack": 20}
WEIGHTS = {"moisture": .16, "tilt": .28, "vibration": .20, "rain": .12, "crack": .24}


def demo_risk(sensors: dict) -> float:
    def weighted(values):
        return sum(max(0, min(1, values[key] / RANGES[key])) * WEIGHTS[key] for key in RANGES)
    points = [(0, 0), *[(weighted(v), score) for v, score in zip(SCENARIOS.values(), (18, 46, 72, 91))], (1, 100)]
    value = weighted(sensors)
    for lower, upper in zip(points, points[1:]):
        if value <= upper[0]:
            return max(0, min(100, lower[1] + (value-lower[0]) / (upper[0]-lower[0]) * (upper[1]-lower[1])))
    return 100.0


def fixture_payload(state: dict) -> dict:
    sensors = state["sensors"]
    score = demo_risk(sensors)
    level = "NORMAL" if score < 30 else "WATCH" if score < 60 else "WARNING" if score < 80 else "EMERGENCY"
    return {
        "schema": "zhifang.telemetry.v2", "site_id": SITE, "device_id": DEVICE,
        "boot_id": state["boot_id"], "seq": state["seq"],
        "timestamp_ms": None, "time_synced": False, "uptime_ms": state["elapsed_seconds"] * 1000,
        "imu": [{"id": name, "valid": True, "ax": 0.0, "ay": 0.0, "az": 9.80665,
                 "gx": 0.0, "gy": 0.0, "gz": 0.0, "tilt_deg": sensors["tilt"],
                 "tilt_rate_dps": 0.0, "vibration_rms": sensors["vibration"] * 9.80665}
                for name in ("top", "toe")],
        "soil": {"top_raw": 16000, "middle_raw": 16000, "toe_raw": 16000,
                 "top_pct": sensors["moisture"], "middle_pct": sensors["moisture"],
                 "toe_pct": sensors["moisture"], "avg_pct": sensors["moisture"], "growth_pct_min": 0.0},
        "experiment": {"run_id": "BACKEND-DEMO", "rain_level": None},
        "risk": {"sensor_score": score, "level": level, "reason_mask": None},
        # These flags describe the MOCK producer; actual broker status is separate.
        "system": {"wifi_up": False, "mqtt_up": False, "lora_ready": False,
                   "sd_ok": False, "edge_online": False, "sensor_degraded": False},
    }


class BackendDemo:
    def __init__(self, db: Database, enabled=True):
        self.db, self.enabled, self._lock = db, enabled, RLock()
        with db.connection() as c:
            c.execute("CREATE TABLE IF NOT EXISTS platform_settings(key TEXT PRIMARY KEY,value_json TEXT NOT NULL)")
        if self._load() is None:
            self._save({"running": bool(enabled), "scenario": "A", "elapsed_seconds": 0,
                        "boot_id": 1, "seq": 0, "sensors": dict(SCENARIOS["A"])})

    def _load(self):
        with self.db.connection() as c:
            row = c.execute("SELECT value_json FROM platform_settings WHERE key='demo'").fetchone()
        return json.loads(row[0]) if row else None

    def _save(self, value):
        with self.db.connection() as c:
            c.execute("INSERT INTO platform_settings VALUES('demo',?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json", (json.dumps(value),))

    def state(self):
        return {**self._load(), "enabled": self.enabled, "source": "MOCK", "scope": "TEST_ONLY"}

    def sample(self, *, advance=False):
        with self._lock:
            state = self._load()
            if not self.enabled:
                return self.state()
            state["seq"] += 1
            if advance:
                state["elapsed_seconds"] += 1
            self._save(state)
            ingest_telemetry(self.db, fixture_payload(state), source="MOCK", scope="TEST_ONLY", transport="backend_demo",
                             context={"demo_sensors": state["sensors"], "scenario": state["scenario"], "risk_model": "DEMO_ONLY_piecewise_v1"})
            return self.state()

    def tick(self):
        if self.enabled and self._load()["running"]:
            return self.sample(advance=True)

    def scenario(self, name: str):
        with self._lock:
            state = self._load()
            state.update(scenario=name, sensors=dict(SCENARIOS[name]))
            self._save(state)
            return self.sample()

    def control(self, running: bool):
        with self._lock:
            state = self._load()
            state["running"] = running
            self._save(state)
            return self.state()

    def reset(self):
        with self._lock:
            previous = self._load()
            with self.db.connection() as c:
                for table in ("telemetry", "alarms", "events"):
                    c.execute(f"DELETE FROM {table} WHERE device_id=? AND source='MOCK'", (DEVICE,))
                c.execute("DELETE FROM boot_sessions WHERE device_id=?", (DEVICE,))
            self._save({"running": self.enabled, "scenario": "A", "elapsed_seconds": 0,
                        "boot_id": previous["boot_id"] + 1, "seq": 0, "sensors": dict(SCENARIOS["A"])})
            return self.sample()
