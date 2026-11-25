"""Dedicated SQLite store and read-only projection for NODE-01-REAL-TEST.

Reserved NODE-01-REAL-TEST intake, quarantine, receipts, and connector records
are stored in a dedicated SQLite file separate from platform.sqlite3 and
research.sqlite3. This view reads test telemetry strictly from that dedicated
store while optionally running a read-only probe against platform.sqlite3 for
historical boot_id checks or unexpected legacy rows without migrating or
mutating platform.sqlite3.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any

from .database import Database
from .settings import _same_path, validate_real_test_database_path

SITE_ID = "NODE01-STAGE23-TEST"
DEVICE_ID = "NODE-01-REAL-TEST"
TOPIC = f"zhifang/v2/{SITE_ID}/{DEVICE_ID}/telemetry"
STORE_ID = "real_test_dedicated_sqlite"
IMU_FIELDS = ("ax", "ay", "az", "gx", "gy", "gz")
SOIL_RAW = ("top_raw", "middle_raw", "toe_raw")
WHERE = "site_id=? AND device_id=? AND source='REAL' AND scope='TEST_ONLY' AND transport='mqtt' AND topic=?"
PROBE_TABLES = (
    "telemetry",
    "alarms",
    "events",
    "quarantine",
    "boot_sessions",
    "intake_receipts",
    "connectors",
    "provisional_risk",
)


def is_reserved_payload(payload: Any) -> bool:
    return isinstance(payload, dict) and (
        payload.get("site_id") == SITE_ID or payload.get("device_id") == DEVICE_ID
    )


def is_reserved_topic(topic: str | None) -> bool:
    if not isinstance(topic, str) or not topic:
        return False
    parts = topic.split("/")
    return topic == TOPIC or SITE_ID in parts or DEVICE_ID in parts


def is_reserved_intake(payload: Any, *, topic: str | None = None) -> bool:
    return is_reserved_payload(payload) or is_reserved_topic(topic)


def is_reserved_connector(data: dict[str, Any] | None, old: dict[str, Any] | None = None) -> bool:
    for candidate in (data, old):
        if not isinstance(candidate, dict):
            continue
        config = candidate.get("config")
        if not isinstance(config, dict):
            continue
        if config.get("site_id") == SITE_ID or is_reserved_topic(config.get("topic")):
            return True
    return False


def same_sqlite_target(first: Database, second: Database) -> bool:
    if first is second:
        return True
    if first.path == ":memory:" or second.path == ":memory:":
        return False
    return _same_path(Path(first.path), Path(second.path))


class RealTestDatabase(Database):
    store_role = "real_test"

    def __init__(
        self,
        path: str | Path,
        *,
        platform_db_path: Path | None = None,
        research_db_path: Path | None = None,
        path_kind: str = "custom",
    ):
        self.platform_db_path = Path(platform_db_path) if platform_db_path is not None else None
        self.research_db_path = Path(research_db_path) if research_db_path is not None else None
        self.path_kind = "memory_test" if str(path) == ":memory:" else path_kind
        super().__init__(path)
        self.validate_isolation()

    def validate_isolation(self) -> None:
        if self.path == ":memory:":
            return
        candidate = Path(self.path)
        if self.platform_db_path is not None and self.research_db_path is not None:
            validate_real_test_database_path(candidate, self.platform_db_path, self.research_db_path)
            return
        raw = str(candidate).strip()
        if not raw or raw.startswith("file:"):
            raise ValueError("GEOHAZARD_REAL_TEST_DATABASE must be a regular local SQLite file path")
        resolved = candidate.expanduser().resolve(strict=False)
        if resolved.exists() and resolved.is_dir():
            raise ValueError("GEOHAZARD_REAL_TEST_DATABASE must point to a file, not a directory")
        if self.platform_db_path is not None and _same_path(candidate, self.platform_db_path):
            raise ValueError("GEOHAZARD_REAL_TEST_DATABASE must not share the platform.sqlite3 path")
        if self.research_db_path is not None and _same_path(candidate, self.research_db_path):
            raise ValueError("GEOHAZARD_REAL_TEST_DATABASE must not share the research registry path")

    def initialize(self) -> None:
        self.validate_isolation()
        super().initialize()

    def storage_descriptor(self) -> dict[str, Any]:
        return {
            "engine": "sqlite_wal",
            "store_id": STORE_ID,
            "isolated": True,
            "path_kind": self.path_kind,
            "store_name": ":memory:" if self.path == ":memory:" else Path(self.path).name,
            "platform_db_shared": False,
        }


def _run_platform_probe(connection: sqlite3.Connection) -> dict[str, Any]:
    existing_tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    }
    counts = {table: 0 for table in PROBE_TABLES}
    platform_boots: list[dict[str, Any]] = []
    device_like = f"%/{DEVICE_ID}/%"
    site_like = f"%/{SITE_ID}/%"
    if "telemetry" in existing_tables:
        counts["telemetry"] = connection.execute(
            "SELECT count(*) FROM telemetry WHERE device_id=? OR site_id=?",
            (DEVICE_ID, SITE_ID),
        ).fetchone()[0]
        platform_boots = [
            {**dict(row), "store": "platform_db"}
            for row in connection.execute(
                "SELECT boot_id, source, scope, count(*) AS samples, min(received_at) AS first_received_at,"
                " max(received_at) AS last_received_at FROM telemetry WHERE device_id=?"
                " GROUP BY boot_id, source, scope ORDER BY boot_id",
                (DEVICE_ID,),
            ).fetchall()
        ]
    if "alarms" in existing_tables:
        counts["alarms"] = connection.execute(
            "SELECT count(*) FROM alarms WHERE device_id=? OR site_id=?",
            (DEVICE_ID, SITE_ID),
        ).fetchone()[0]
    if "events" in existing_tables:
        counts["events"] = connection.execute(
            "SELECT count(*) FROM events WHERE device_id=? OR site_id=?",
            (DEVICE_ID, SITE_ID),
        ).fetchone()[0]
    if "boot_sessions" in existing_tables:
        counts["boot_sessions"] = connection.execute(
            "SELECT count(*) FROM boot_sessions WHERE device_id=?",
            (DEVICE_ID,),
        ).fetchone()[0]
    if "quarantine" in existing_tables:
        counts["quarantine"] = connection.execute(
            "SELECT count(*) FROM quarantine WHERE topic=? OR topic LIKE ? OR topic LIKE ?",
            (TOPIC, device_like, site_like),
        ).fetchone()[0]
    if "intake_receipts" in existing_tables:
        counts["intake_receipts"] = connection.execute(
            "SELECT count(*) FROM intake_receipts WHERE topic=? OR topic LIKE ? OR topic LIKE ?",
            (TOPIC, device_like, site_like),
        ).fetchone()[0]
    if "connectors" in existing_tables:
        connector_rows = connection.execute("SELECT config_json FROM connectors").fetchall()
        reserved_connectors = 0
        for row in connector_rows:
            try:
                config = json.loads(row["config_json"])
            except (TypeError, ValueError):
                continue
            if is_reserved_connector({"config": config}):
                reserved_connectors += 1
        counts["connectors"] = reserved_connectors
    if "provisional_risk" in existing_tables and "telemetry" in existing_tables:
        counts["provisional_risk"] = connection.execute(
            "SELECT count(*) FROM provisional_risk WHERE telemetry_id IN ("
            "SELECT id FROM telemetry WHERE device_id=? OR site_id=?)",
            (DEVICE_ID, SITE_ID),
        ).fetchone()[0]
    unexpected = any(value > 0 for value in counts.values())
    warning = (
        "Unexpected NODE-01-REAL-TEST / NODE01-STAGE23-TEST rows detected in platform.sqlite3 "
        "(read-only probe; not merged into real-test readings and not migrated, deleted, or modified)"
        if unexpected
        else None
    )
    return {
        "performed": True,
        "mode": "read_only",
        "unexpected_rows_detected": unexpected,
        "warning": warning,
        "counts": counts,
        "observed_boot_ids": platform_boots,
    }


def probe_platform_db(platform_db: Database | None) -> dict[str, Any]:
    empty_counts = {table: 0 for table in PROBE_TABLES}
    if platform_db is None:
        return {
            "performed": False,
            "mode": "skipped",
            "unexpected_rows_detected": False,
            "warning": None,
            "counts": empty_counts,
            "observed_boot_ids": [],
        }
    if platform_db.path != ":memory:":
        db_file = Path(platform_db.path).expanduser().resolve(strict=False)
        if not db_file.is_file():
            return {
                "performed": True,
                "mode": "read_only_missing",
                "unexpected_rows_detected": False,
                "warning": None,
                "counts": empty_counts,
                "observed_boot_ids": [],
            }
        with closing(sqlite3.connect(db_file.as_uri() + "?mode=ro", uri=True, timeout=5)) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only=ON")
            return _run_platform_probe(connection)
    with platform_db._lock:
        if platform_db._connection is None:
            return {
                "performed": True,
                "mode": "read_only_uninitialized",
                "unexpected_rows_detected": False,
                "warning": None,
                "counts": empty_counts,
                "observed_boot_ids": [],
            }
        return _run_platform_probe(platform_db._connection)


def _sample(row, arrival_order: int):
    payload = json.loads(row["payload_json"])
    return {
        "telemetry_id": row["id"], "received_at": row["received_at"], "arrival_order": arrival_order,
        "boot_id": payload["boot_id"], "seq": payload["seq"], "uptime_ms": payload["uptime_ms"],
        "timestamp_ms": payload["timestamp_ms"], "time_synced": payload["time_synced"],
        "imu": [{"id": imu["id"], "valid": imu["valid"], **{field: imu[field] for field in IMU_FIELDS}}
                for imu in payload["imu"]],
        "soil_raw": {field: payload["soil"][field] for field in SOIL_RAW},
    }


def status(
    test_db: Database,
    *,
    platform_db: Database | None = None,
    freshness_seconds: int = 30,
    limit: int = 20,
):
    if getattr(test_db, "store_role", "platform") != "real_test":
        raise RuntimeError("real_test.status requires a dedicated RealTestDatabase store")
    if platform_db is not None and same_sqlite_target(test_db, platform_db):
        raise RuntimeError("REAL-TEST store must be separate from platform.sqlite3")
    args = (SITE_ID, DEVICE_ID, TOPIC)
    with test_db.connection() as connection:
        recent = connection.execute(f"SELECT * FROM telemetry WHERE {WHERE} ORDER BY rowid DESC LIMIT ?", (*args, limit)).fetchall()
        total = connection.execute(f"SELECT count(*) FROM telemetry WHERE {WHERE}", args).fetchone()[0]
        test_boots = [{**dict(row), "store": "test_store"} for row in connection.execute(
            "SELECT boot_id, source, scope, count(*) AS samples, min(received_at) AS first_received_at,"
            " max(received_at) AS last_received_at FROM telemetry WHERE device_id=? GROUP BY boot_id, source, scope ORDER BY boot_id",
            (DEVICE_ID,))]
        test_alarms = connection.execute("SELECT count(*) FROM alarms WHERE device_id=?", (DEVICE_ID,)).fetchone()[0]
    platform_probe = probe_platform_db(platform_db)
    platform_boots = platform_probe["observed_boot_ids"]
    observed_boots = sorted(
        [*test_boots, *platform_boots],
        key=lambda item: (item["boot_id"], item["store"], item["source"], item["scope"]),
    )
    formal_alarms = test_alarms + platform_probe["counts"].get("alarms", 0)
    storage = (
        test_db.storage_descriptor()
        if isinstance(test_db, RealTestDatabase)
        else {
            "engine": "sqlite_wal",
            "store_id": STORE_ID,
            "isolated": True,
            "path_kind": "custom",
            "store_name": ":memory:" if test_db.path == ":memory:" else Path(test_db.path).name,
            "platform_db_shared": False,
        }
    )
    observed_at = datetime.now(timezone.utc)
    samples = [_sample(row, total - index) for index, row in enumerate(recent)]
    latest = samples[0] if samples else None
    age = None
    if latest:
        received = datetime.fromisoformat(latest["received_at"].replace("Z", "+00:00"))
        age = max(0.0, (observed_at - received).total_seconds())
    return {
        "site_id": SITE_ID, "device_id": DEVICE_ID, "topic": TOPIC, "source": "REAL", "scope": "TEST_ONLY",
        "evidence_note": "REAL is the connector label; it is not proof of calibrated or field-verified data",
        "storage": storage,
        "telemetry_count": total, "formal_alarm_count": formal_alarms,
        "observed_boot_ids": observed_boots,
        "observed_boot_ids_by_store": {"test_store": test_boots, "platform_db": platform_boots},
        "platform_db_probe": platform_probe,
        "latest": latest, "recent": samples,
        "observed_at": observed_at.isoformat(),
        "arrival_age_seconds": round(age, 1) if age is not None else None,
        "stale": age is None or age > freshness_seconds,
        "time_basis": {"received_at_clock": "platform_host", "device_time_synced": latest["time_synced"] if latest else None,
                       "note": "received_at comes from the platform host clock, not the Windows or device clock"},
        "imu_status": "UNCALIBRATED_AXIS_UNMAPPED",
        "soil_window": {"status": "INSUFFICIENT_WINDOW", "delta_vwc_verified": False,
                        "note": "Raw only; 1-3 packets cannot form a 120 s window and no ΔVWC is shown"},
    }
