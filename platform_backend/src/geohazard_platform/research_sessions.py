"""Internal five-channel analysis DTO, dedicated research registry and replay CLI.

No telemetry-v2 projection, production database, inference window or alarm writes.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import statistics
import sys
import uuid

from .sd_replay import (
    ADAPTER_VERSION, SENSORS, ParsedSDSession, ReplayValidationError, SDRow, parse_sd_session,
)


SESSION_TYPES = ("rain_50", "rain_70", "rain_100", "post_rain_static")
ANALYSIS_FORMAT_VERSION = "research-raw-session-v1"
KNOWN_SESSION_TYPES = {
    "NODE01-5f604a129b915316-N0000001.CSV": "rain_50",
    "NODE01-d5a1317c1f27fded-N0000002.CSV": "rain_70",
    "NODE01-f9029c8eef460b40-N0000004.CSV": "rain_100",
    "NODE01-2e379f02688fd631-N0000005.CSV": "post_rain_static",
}
AIN2_REVIEW_EXPERIMENTS = {
    "NODE01-f9029c8eef460b40-N0000004.CSV",
    "NODE01-2e379f02688fd631-N0000005.CSV",
}


@dataclass(frozen=True)
class AnalysisObservation:
    raw: SDRow
    relative_time_us: int | None
    quality_flags: tuple[str, ...]

    @property
    def usable(self) -> bool:
        return not self.quality_flags


@dataclass(frozen=True)
class ChannelSeries:
    sensor_id: str
    kind: str
    channel: int
    units: tuple[str, ...]
    quality_flags: tuple[str, ...]
    observations: tuple[AnalysisObservation, ...]

    def statistics(self) -> dict:
        """Median intervals use adjacent usable rows; never bridge an error/gap row.

        Duration is first-to-last usable sample span, not continuous coverage.
        No samples/intervals are represented by null, including an empty channel.
        """
        usable = [sample for sample in self.observations if sample.usable]
        intervals = [
            current.raw.acquired_uptime_us - previous.raw.acquired_uptime_us
            for previous, current in zip(self.observations, self.observations[1:])
            if previous.usable and current.usable
        ]
        valid_count = sum(sample.raw.validity == "Valid" for sample in self.observations)
        return {
            "sensor_id": self.sensor_id, "kind": self.kind, "channel": self.channel,
            "units": self.units, "quality_flags": self.quality_flags,
            "count": len(self.observations), "valid_count": valid_count,
            "invalid_count": len(self.observations) - valid_count, "usable_count": len(usable),
            "missing_value_count": sum(sample.raw.missing_value for sample in self.observations),
            "first_relative_time_us": usable[0].relative_time_us if usable else None,
            "last_relative_time_us": usable[-1].relative_time_us if usable else None,
            "duration_s": ((usable[-1].relative_time_us - usable[0].relative_time_us) / 1e6
                           if usable else None),
            "median_interval_us": statistics.median(intervals) if intervals else None,
        }


@dataclass(frozen=True)
class AnalysisSession:
    metadata: dict
    channels: tuple[ChannelSeries, ...]

    def summary(self) -> dict:
        return {"metadata": self.metadata,
                "channels": {series.sensor_id: series.statistics() for series in self.channels}}


def _validate_session_type(experiment_id: str, session_type: str) -> None:
    if session_type not in SESSION_TYPES:
        raise ValueError(f"unknown session type: {session_type}")
    expected = KNOWN_SESSION_TYPES.get(experiment_id)
    if expected is not None and session_type != expected:
        raise ValueError(f"{experiment_id} requires session type {expected}")


def to_analysis_session(parsed: ParsedSDSession, session_type: str, *, replay_id: str) -> AnalysisSession:
    """Convert a validated capture; a persisted registry supplies the replay identity.

    The physical time axis is acquired_uptime_us relative to END.start_us.
    Attempt times stay on failed rows without inventing acquisition timestamps.
    """
    _validate_session_type(parsed.experiment_id, session_type)
    if not replay_id:
        raise ValueError("replay_id must be supplied by the research registry")
    if not parsed.integrity.passed:
        raise ValueError("cannot convert a session with failed integrity")
    session_flags = ["UNCALIBRATED", "FIRMWARE_IDENTITY_DECLARED_ONLY"]
    if parsed.experiment_id in AIN2_REVIEW_EXPERIMENTS:
        session_flags.append("AIN2_JITTER_REVIEW")
    if session_type == "post_rain_static":
        session_flags.append("POST_RAIN_NOT_DRY_BASELINE")
    sensor_errors_present = any(row.validity != "Valid" or row.error != 0 for row in parsed.rows)
    if sensor_errors_present:
        session_flags.append("SENSOR_ERRORS_PRESENT")
    grouped: dict[str, list[AnalysisObservation]] = {sensor: [] for sensor in SENSORS.values()}
    # High-water marks are per sensor and per capture, never shared with another IMU/session.
    latest: dict[str, int] = {}
    for row in parsed.rows:
        flags = []
        if row.validity != "Valid":
            flags.append("SENSOR_INVALID")
        if row.error != 0:
            flags.append("SENSOR_ERROR_CODE")
        if row.missing_value:
            flags.append("MISSING_VALUE")
        acquired = row.acquired_uptime_us
        if acquired is None:
            flags.append("MISSING_ACQUIRED_TIME")
        else:
            if acquired < row.attempted_uptime_us:
                flags.append("ACQUIRED_BEFORE_ATTEMPT")
            if acquired < parsed.start_uptime_us:
                flags.append("BEFORE_CAPTURE_START")
            if row.sensor_id in latest and acquired <= latest[row.sensor_id]:
                flags.append("DUPLICATE_SAMPLE_TIME" if acquired == latest[row.sensor_id]
                             else "TIME_BACKWARDS")
            latest[row.sensor_id] = max(latest.get(row.sensor_id, acquired), acquired)
        grouped[row.sensor_id].append(AnalysisObservation(
            raw=row, relative_time_us=acquired - parsed.start_uptime_us if acquired is not None else None,
            quality_flags=tuple(flags),
        ))
    channels = tuple(ChannelSeries(
        sensor_id=sensor, kind=kind, channel=channel,
        units=("m/s^2", "deg/s") if kind == "imu" else ("ADC raw code",),
        quality_flags=(("AIN2_JITTER_REVIEW",)
                       if sensor == "soil_toe" and parsed.experiment_id in AIN2_REVIEW_EXPERIMENTS else ()),
        observations=tuple(grouped[sensor]),
    ) for (kind, channel), sensor in SENSORS.items())
    metadata = {
        "experiment_id": parsed.experiment_id, "session_type": session_type,
        "replay_id": replay_id, "capture_or_replay_id": replay_id,
        "generated_replay_identity": True, "adapter_version": ADAPTER_VERSION,
        "analysis_format_version": ANALYSIS_FORMAT_VERSION,
        "device_id": parsed.device_id, "site_id": None, "boot_id": None,
        "rule_version": None, "reference_version": None,
        "source": "REAL", "scope": "TEST_ONLY", "transport": "sd_replay",
        "fusion_eligible": False, "risk_eligible": False,
        "firmware_sha256": parsed.firmware_sha256,
        "firmware_identity_status": "DECLARED_NOT_INDEPENDENTLY_VERIFIED",
        "source_directory": str(parsed.directory), "csv_name": parsed.csv_name,
        "integrity": parsed.integrity.to_dict(),
        "valid_counts": parsed.integrity.valid_counts, "invalid_counts": parsed.integrity.invalid_counts,
        "quality_flags": session_flags,
        "sensor_errors_present": sensor_errors_present,
        "calibration_status": "NOT_READY", "landslide_ground_truth": "UNVERIFIED",
        "time_basis": "acquired_uptime_us_relative_to_capture_start",
        "time_origin_uptime_us": parsed.start_uptime_us,
        "capture_stop_uptime_us": parsed.stop_uptime_us,
        "utc_available": any(row.time_synced and row.timestamp_ms is not None for row in parsed.rows),
    }
    return AnalysisSession(metadata=metadata, channels=channels)


class ReplayIdentityConflict(ValueError):
    pass


def _registry_connection(path: Path, source: Path) -> sqlite3.Connection:
    path = path.expanduser().resolve()
    if path == source or source in path.parents:
        raise ValueError("research registry must be outside the read-only capture directory")
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    tables = {row[0] for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    if tables - {"research_sd_sessions", "research_sd_attempts"}:
        connection.close()
        raise ValueError("use a dedicated research registry, not an operational or unrelated database")
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS research_sd_sessions (
            experiment_id TEXT NOT NULL, adapter_version TEXT NOT NULL,
            replay_id TEXT NOT NULL UNIQUE, fingerprints_json TEXT NOT NULL,
            metadata_json TEXT NOT NULL, registered_at TEXT NOT NULL,
            PRIMARY KEY (experiment_id, adapter_version)
        );
        CREATE TABLE IF NOT EXISTS research_sd_attempts (
            id INTEGER PRIMARY KEY, attempted_at TEXT NOT NULL,
            source_directory TEXT NOT NULL, csv_name TEXT, experiment_id TEXT,
            status TEXT NOT NULL, details_json TEXT NOT NULL
        );
    """)
    return connection


def _audit(connection: sqlite3.Connection, source: Path, csv_name: str | None,
           experiment_id: str | None, status: str, details: dict) -> None:
    connection.execute("""INSERT INTO research_sd_attempts
        (attempted_at,source_directory,csv_name,experiment_id,status,details_json)
        VALUES(?,?,?,?,?,?)""", (
        datetime.now(timezone.utc).isoformat(), str(source), csv_name, experiment_id,
        status, json.dumps(details, ensure_ascii=False, sort_keys=True),
    ))


def register_session(directory: str | Path, session_type: str, registry_path: str | Path,
                     *, csv_name: str | None = None) -> AnalysisSession:
    """Persist only metadata/fingerprints, then expose independent channel series.

    Identical reimports reuse the durable UUID. Full experiment ID + adapter
    version is the key; same-identity changed triplets/labels are refused and
    audited without replacing the previous registration. No raw file is copied.
    """
    if session_type not in SESSION_TYPES:
        raise ValueError(f"unknown session type: {session_type}")
    source = Path(directory).expanduser().resolve()
    connection = _registry_connection(Path(registry_path), source)
    try:
        try:
            parsed = parse_sd_session(source, csv_name)
        except ReplayValidationError as exc:
            _audit(connection, source, csv_name, None, "REJECTED_INTEGRITY", {
                "issues": exc.issues,
                "integrity": exc.integrity.to_dict() if exc.integrity else None,
            })
            connection.commit()
            raise
        try:
            _validate_session_type(parsed.experiment_id, session_type)
        except ValueError as exc:
            _audit(connection, source, parsed.csv_name, parsed.experiment_id,
                   "REJECTED_METADATA", {"issues": [str(exc)]})
            connection.commit()
            raise
        # Serialize competing registrations before checking the persistent identity.
        connection.execute("BEGIN IMMEDIATE")
        previous = connection.execute("""SELECT * FROM research_sd_sessions
            WHERE experiment_id=? AND adapter_version=?""", (parsed.experiment_id, ADAPTER_VERSION)).fetchone()
        fingerprints = json.dumps(parsed.integrity.file_sha256, sort_keys=True)
        if previous and (previous["fingerprints_json"] != fingerprints
                         or json.loads(previous["metadata_json"])["session_type"] != session_type):
            details = {"issues": ["same experiment_id/adapter has different bytes or session type"],
                       "observed_file_sha256": parsed.integrity.file_sha256,
                       "registered_file_sha256": json.loads(previous["fingerprints_json"])}
            _audit(connection, source, parsed.csv_name, parsed.experiment_id, "REJECTED_IDENTITY", details)
            connection.commit()
            raise ReplayIdentityConflict(details["issues"][0])
        replay_id = previous["replay_id"] if previous else "sd-replay-" + str(uuid.uuid4())
        analysis = to_analysis_session(parsed, session_type, replay_id=replay_id)
        if previous:
            # Preserve the original registered provenance when importing a byte-identical copy.
            analysis = AnalysisSession(metadata=json.loads(previous["metadata_json"]), channels=analysis.channels)
        else:
            connection.execute("INSERT INTO research_sd_sessions VALUES(?,?,?,?,?,?)", (
                parsed.experiment_id, ADAPTER_VERSION, replay_id, fingerprints,
                json.dumps(analysis.metadata, ensure_ascii=False, sort_keys=True),
                datetime.now(timezone.utc).isoformat(),
            ))
        _audit(connection, source, parsed.csv_name, parsed.experiment_id,
               "DUPLICATE" if previous else "REGISTERED", {"replay_id": replay_id})
        connection.commit()
        return analysis
    finally:
        connection.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Register a read-only SD capture and print five-channel statistics")
    parser.add_argument("directory", type=Path)
    parser.add_argument("--type", dest="session_type", required=True, choices=SESSION_TYPES)
    parser.add_argument("--registry", type=Path, required=True, help="dedicated research SQLite file outside raw data")
    parser.add_argument("--csv", dest="csv_name", help="CSV basename when a directory contains multiple captures")
    args = parser.parse_args(argv)
    try:
        session = register_session(args.directory, args.session_type, args.registry, csv_name=args.csv_name)
    except (ValueError, OSError, sqlite3.Error) as exc:
        payload = {"status": "rejected", "error": str(exc)}
        if isinstance(exc, ReplayValidationError):
            payload["issues"] = exc.issues
            payload["integrity"] = exc.integrity.to_dict() if exc.integrity else None
        print(json.dumps(payload, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(session.summary(), ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
