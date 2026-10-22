"""Small transactional SQLite store for the local platform.

A single protected connection also makes ``:memory:`` useful in tests. Network
callbacks and FastAPI worker threads share the same serialized transaction gate.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import os
import sqlite3
from threading import RLock
from typing import Iterator
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class Database:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self._lock = RLock()
        self._connection: sqlite3.Connection | None = None

    def initialize(self) -> None:
        with self._lock:
            if self._connection is not None:
                return
            if self.path != ":memory:":
                Path(self.path).parent.mkdir(parents=True, exist_ok=True)
                # Pre-create with restricted permissions before SQLite writes secrets.
                fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
                os.close(fd)
                os.chmod(self.path, 0o600)
            connection = sqlite3.connect(self.path, check_same_thread=False, timeout=15)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS inference_results (
                    id TEXT PRIMARY KEY, site_id TEXT NOT NULL, device_id TEXT NOT NULL,
                    source TEXT NOT NULL, scope TEXT NOT NULL, model TEXT NOT NULL,
                    window_start_at TEXT NOT NULL, window_end_at TEXT NOT NULL,
                    predicted_delta TEXT NOT NULL, latency_ms REAL NOT NULL, created_at TEXT NOT NULL,
                    fusion_eligible INTEGER NOT NULL DEFAULT 0 CHECK(fusion_eligible=0),
                    calibration TEXT NOT NULL DEFAULT 'uncalibrated_research'
                        CHECK(calibration='uncalibrated_research'), reason TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS inference_device_time ON inference_results
                    (site_id,device_id,created_at DESC,id DESC);
                CREATE TABLE IF NOT EXISTS tinyquake_results (
                    id TEXT PRIMARY KEY, site_id TEXT NOT NULL, device_id TEXT NOT NULL,
                    sensor_id TEXT NOT NULL, boot_id INTEGER NOT NULL, seq INTEGER NOT NULL,
                    source TEXT NOT NULL, input_source TEXT NOT NULL, received_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL, connector_id TEXT,
                    UNIQUE(site_id,device_id,sensor_id,boot_id,seq)
                );
                CREATE INDEX IF NOT EXISTS tinyquake_stream_time ON tinyquake_results
                    (site_id,device_id,sensor_id,source,received_at DESC,id DESC);
                CREATE TABLE IF NOT EXISTS telemetry (
                    id TEXT PRIMARY KEY, site_id TEXT NOT NULL, device_id TEXT NOT NULL,
                    boot_id INTEGER NOT NULL, seq INTEGER NOT NULL,
                    source TEXT NOT NULL, scope TEXT NOT NULL, transport TEXT NOT NULL,
                    connector_id TEXT, topic TEXT, payload_json TEXT NOT NULL, context_json TEXT NOT NULL DEFAULT '{}',
                    source_time INTEGER, uptime_ms INTEGER NOT NULL, received_at TEXT NOT NULL,
                    is_current INTEGER NOT NULL DEFAULT 0, is_backfill INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(device_id, boot_id, seq)
                );
                CREATE INDEX IF NOT EXISTS telemetry_site_time ON telemetry(site_id, received_at DESC);
                CREATE INDEX IF NOT EXISTS telemetry_device_order ON telemetry(device_id, boot_id, seq DESC);
                CREATE UNIQUE INDEX IF NOT EXISTS telemetry_one_current ON telemetry(device_id) WHERE is_current=1;
                CREATE TABLE IF NOT EXISTS intake_receipts (
                    id TEXT PRIMARY KEY, telemetry_id TEXT NOT NULL REFERENCES telemetry(id) ON DELETE CASCADE,
                    status TEXT NOT NULL, source TEXT NOT NULL, scope TEXT NOT NULL,
                    transport TEXT NOT NULL, connector_id TEXT, topic TEXT,
                    context_json TEXT NOT NULL, received_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS boot_sessions (
                    ordinal INTEGER PRIMARY KEY AUTOINCREMENT, device_id TEXT NOT NULL,
                    boot_id INTEGER NOT NULL, first_seen TEXT NOT NULL,
                    UNIQUE(device_id, boot_id)
                );
                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY, kind TEXT NOT NULL, message TEXT NOT NULL,
                    site_id TEXT, device_id TEXT, source TEXT NOT NULL,
                    details_json TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS alarms (
                    id TEXT PRIMARY KEY, site_id TEXT NOT NULL, device_id TEXT,
                    source TEXT NOT NULL, level TEXT NOT NULL, score REAL,
                    reason TEXT NOT NULL, source_message_id TEXT,
                    acknowledged INTEGER NOT NULL DEFAULT 0,
                    acknowledged_at TEXT, created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS alarm_site_time ON alarms(site_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS quarantine (
                    id TEXT PRIMARY KEY, source TEXT NOT NULL, scope TEXT NOT NULL,
                    transport TEXT NOT NULL, connector_id TEXT, topic TEXT,
                    raw_payload TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS connectors (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL,
                    config_json TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 0,
                    source TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS connector_secrets (
                    connector_id TEXT PRIMARY KEY REFERENCES connectors(id) ON DELETE CASCADE,
                    password TEXT
                );
            """)
            columns = {row[1] for row in connection.execute("PRAGMA table_info(telemetry)")}
            if "context_json" not in columns:
                connection.execute("ALTER TABLE telemetry ADD COLUMN context_json TEXT NOT NULL DEFAULT '{}' ")
            connection.commit()
            self._connection = connection

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            if self._connection is None:
                self.initialize()
            assert self._connection is not None
            connection = self._connection
            # SQLite's writer reservation protects read/modify/write sequences
            # across Database instances and processes, beyond the Python lock.
            nested = connection.in_transaction
            savepoint = "nested_" + uuid4().hex if nested else None
            if savepoint:
                connection.execute(f"SAVEPOINT {savepoint}")
            else:
                connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
                if savepoint:
                    connection.execute(f"RELEASE SAVEPOINT {savepoint}")
                else:
                    connection.commit()
            except BaseException:
                if savepoint:
                    connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                    connection.execute(f"RELEASE SAVEPOINT {savepoint}")
                else:
                    # Commit itself can fail (disk/full, deferred constraints).
                    # Never leave that request's changes for a later commit.
                    connection.rollback()
                raise

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None
