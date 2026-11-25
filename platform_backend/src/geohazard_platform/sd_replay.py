"""Read-only NODE01 SD long-table parsing, independent of telemetry v2 intake."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
import zlib


ADAPTER_VERSION = "node01-sd-longtable-v1"
COLUMNS = (
    "kind", "channel", "acquisition_index", "attempted_uptime_us",
    "acquired_uptime_us", "timestamp_ms", "time_synced", "validity", "error",
    "ax_raw", "ay_raw", "az_raw", "gx_raw", "gy_raw", "gz_raw",
    "ax_mps2", "ay_mps2", "az_mps2", "gx_dps", "gy_dps", "gz_dps", "soil_raw",
)
SENSORS = {
    ("imu", 0): "imu_top", ("imu", 1): "imu_toe",
    ("soil", 0): "soil_top", ("soil", 1): "soil_middle", ("soil", 2): "soil_toe",
}


@dataclass(frozen=True)
class IntegrityReport:
    csv_bytes: int
    csv_crc32: str
    data_rows: int
    declared_bytes: int
    declared_crc32: str
    declared_rows: int
    acquisition_index_contiguous: bool
    file_sha256: dict[str, str]
    valid_counts: dict[str, int]
    invalid_counts: dict[str, int]
    issues: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.issues

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "issues": list(self.issues), "passed": self.passed}


class ReplayValidationError(ValueError):
    """Structured refusal; registration persists these issues in its audit table."""

    def __init__(self, issues: list[str], integrity: IntegrityReport | None = None):
        self.issues = tuple(issues)
        self.integrity = integrity
        super().__init__("; ".join(issues))


@dataclass(frozen=True)
class SDRow:
    source_line: int
    kind: str
    channel: int
    acquisition_index: int
    attempted_uptime_us: int
    acquired_uptime_us: int | None
    timestamp_ms: int | None
    time_synced: bool
    validity: str
    error: int
    imu_raw: tuple[int | None, ...]
    acceleration_mps2: tuple[float | None, ...]
    angular_velocity_dps: tuple[float | None, ...]
    soil_raw: int | None

    @property
    def sensor_id(self) -> str:
        return SENSORS[(self.kind, self.channel)]

    @property
    def missing_value(self) -> bool:
        if self.kind == "soil":
            return self.soil_raw is None
        return any(v is None for v in self.acceleration_mps2 + self.angular_velocity_dps)


@dataclass(frozen=True)
class ParsedSDSession:
    directory: Path
    csv_name: str
    experiment_id: str
    firmware_sha256: str
    device_id: str | None
    start_uptime_us: int
    stop_uptime_us: int
    rows: tuple[SDRow, ...]
    integrity: IntegrityReport


def _integer(value: Any, field: str, *, nullable: bool = False) -> int | None:
    if nullable and value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError(f"{field}: expected integer")
    if isinstance(value, str) and (not value or not value.lstrip("-").isdigit()):
        raise ValueError(f"{field}: expected integer")
    return int(value)


def _unsigned(value: Any, field: str, *, nullable: bool = False) -> int | None:
    result = _integer(value, field, nullable=nullable)
    if result is not None and result < 0:
        raise ValueError(f"{field}: expected nonnegative integer")
    return result


def _number(value: str, field: str) -> float | None:
    if value == "":
        return None
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field}: non-finite measurement")
    return result


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sidecar(data: bytes, record_type: str) -> dict[str, Any]:
    record = json.loads(data)
    if not isinstance(record, dict) or record.get("record_type") != record_type:
        raise ValueError(f"expected {record_type} sidecar")
    return record


def _parse_row(values: list[str], line: int) -> SDRow:
    if len(values) != len(COLUMNS):
        raise ValueError(f"expected {len(COLUMNS)} columns, got {len(values)}")
    row = dict(zip(COLUMNS, values))
    channel = _unsigned(row["channel"], "channel")
    if (row["kind"], channel) not in SENSORS:
        raise ValueError(f"unknown sensor {row['kind']}/{channel}")
    if row["time_synced"] not in ("true", "false"):
        raise ValueError("time_synced: expected true/false")
    timestamp = _unsigned(row["timestamp_ms"], "timestamp_ms", nullable=True)
    if row["time_synced"] == "true" and timestamp is None:
        raise ValueError("time_synced=true requires timestamp_ms")
    if not row["validity"]:
        raise ValueError("missing validity")
    return SDRow(
        source_line=line, kind=row["kind"], channel=channel,
        acquisition_index=_unsigned(row["acquisition_index"], "acquisition_index"),
        attempted_uptime_us=_unsigned(row["attempted_uptime_us"], "attempted_uptime_us"),
        acquired_uptime_us=_unsigned(row["acquired_uptime_us"], "acquired_uptime_us", nullable=True),
        timestamp_ms=timestamp, time_synced=row["time_synced"] == "true",
        validity=row["validity"], error=_integer(row["error"], "error"),
        imu_raw=tuple(_integer(row[key], key, nullable=True) for key in COLUMNS[9:15]),
        acceleration_mps2=tuple(_number(row[key], key) for key in COLUMNS[15:18]),
        angular_velocity_dps=tuple(_number(row[key], key) for key in COLUMNS[18:21]),
        soil_raw=_integer(row["soil_raw"], "soil_raw", nullable=True),
    )


def parse_sd_session(directory: str | Path, csv_name: str | None = None) -> ParsedSDSession:
    """Validate one complete triplet before returning any observations.

    File hashes cover original bytes, including comments/newlines. The index is
    checked globally from zero, including error rows. Sensor errors are retained
    and counted; they are distinct from storage/identity integrity failures.
    """
    directory = Path(directory).expanduser().resolve()
    try:
        if csv_name is None:
            candidates = sorted(directory.glob("*.CSV"))
            if len(candidates) != 1:
                raise ValueError("session directory must contain one CSV; select --csv explicitly")
            csv_path = candidates[0]
        else:
            if Path(csv_name).name != csv_name or not csv_name.endswith(".CSV"):
                raise ValueError("csv_name must be a .CSV basename")
            csv_path = directory / csv_name
        data = csv_path.read_bytes()
        begin_data = csv_path.with_suffix(".BEG").read_bytes()
        end_data = csv_path.with_suffix(".END").read_bytes()
        begin = _sidecar(begin_data, "START_INTENT")
        end = _sidecar(end_data, "END")
        experiment_id = begin.get("experiment_id")
        if not isinstance(experiment_id, str) or not experiment_id or end.get("experiment_id") != experiment_id:
            raise ValueError("BEG/END experiment_id mismatch or missing identity")
        if not isinstance(begin.get("csv"), str) or begin["csv"] != end.get("csv"):
            raise ValueError("BEG/END logical CSV mismatch")
        if not experiment_id.endswith("-" + begin["csv"].rsplit("/", 1)[-1]):
            raise ValueError("experiment_id does not identify the logical CSV")
        firmware = begin.get("elf_sha256")
        if (not isinstance(firmware, str) or len(firmware) != 64
                or any(c not in "0123456789abcdef" for c in firmware)
                or end.get("elf_sha256") != firmware):
            raise ValueError("BEG/END firmware SHA-256 mismatch or malformed declaration")
        declared_bytes = _unsigned(end.get("csv_bytes"), "END.csv_bytes")
        declared_rows = _unsigned(end.get("verified_rows"), "END.verified_rows")
        declared_crc = end.get("csv_crc32")
        if (not isinstance(declared_crc, str) or len(declared_crc) != 8
                or any(c not in "0123456789abcdefABCDEF" for c in declared_crc)):
            raise ValueError("END.csv_crc32: expected 8 hex digits")
        declared_crc = declared_crc.lower()
        start = _unsigned(end.get("start_us"), "END.start_us")
        stop = _unsigned(end.get("stop_us"), "END.stop_us")
        if stop < start:
            raise ValueError("END.stop_us precedes start_us")

        stream = io.StringIO(data.decode("utf-8"), newline="")
        headers: dict[str, str] = {}
        comment_lines = 0
        while True:
            position = stream.tell()
            line = stream.readline()
            if not line.startswith("#"):
                stream.seek(position)
                break
            comment_lines += 1
            for part in line[1:].strip().split(";"):
                if "=" in part:
                    key, value = part.strip().split("=", 1)
                    if key in headers and headers[key] != value:
                        raise ValueError(f"conflicting CSV header {key}")
                    headers[key] = value
        if headers.get("app_elf_sha256") != firmware:
            raise ValueError("CSV/BEG firmware SHA-256 mismatch or missing CSV declaration")
        if "experiment_id" in headers and headers["experiment_id"] != experiment_id:
            raise ValueError("CSV/BEG experiment_id mismatch")
        reader = csv.reader(stream, strict=True)
        if tuple(next(reader, ())) != COLUMNS:
            raise ValueError("CSV header does not match the 22-column SD schema")
        rows: list[SDRow] = []
        valid = dict.fromkeys(SENSORS.values(), 0)
        invalid = dict.fromkeys(SENSORS.values(), 0)
        issues = []
        contiguous = True
        for values in reader:
            source_line = comment_lines + reader.line_num
            try:
                row = _parse_row(values, source_line)
            except ValueError as exc:
                raise ValueError(f"CSV line {source_line}: {exc}") from exc
            if row.acquisition_index != len(rows) and contiguous:
                contiguous = False
                issues.append(f"acquisition_index discontinuity at line {source_line}: "
                              f"expected {len(rows)}, got {row.acquisition_index}")
            rows.append(row)
            counts = valid if row.validity == "Valid" else invalid
            counts[row.sensor_id] += 1

        actual_crc = f"{zlib.crc32(data) & 0xffffffff:08x}"
        for name, actual, declared in (
            ("csv_bytes", len(data), declared_bytes),
            ("csv_crc32", actual_crc, declared_crc),
            ("verified_rows", len(rows), declared_rows),
        ):
            if actual != declared:
                issues.append(f"END.{name}: declared {declared}, observed {actual}")
        for key in ("accepted",):
            if key in end and _unsigned(end[key], f"END.{key}") != len(rows):
                issues.append(f"END.{key} differs from observed row count")
        soil_counts = end.get("soil_valid")
        if not isinstance(soil_counts, list) or len(soil_counts) != 3:
            raise ValueError("END.soil_valid: expected three channel counts")
        expected_valid = [end.get("top_valid"), end.get("toe_valid"), *soil_counts]
        for sensor, count in zip(SENSORS.values(), expected_valid):
            if _unsigned(count, f"END.{sensor}.valid") != valid[sensor]:
                issues.append(f"END valid count mismatch for {sensor}: observed {valid[sensor]}")
        if not rows:
            issues.append("CSV contains no observations")
        report = IntegrityReport(
            csv_bytes=len(data), csv_crc32=actual_crc, data_rows=len(rows),
            declared_bytes=declared_bytes, declared_crc32=declared_crc, declared_rows=declared_rows,
            acquisition_index_contiguous=contiguous,
            file_sha256={"csv": _sha256(data), "beg": _sha256(begin_data), "end": _sha256(end_data)},
            valid_counts=valid, invalid_counts=invalid, issues=tuple(issues),
        )
        if issues:
            raise ReplayValidationError(issues, report)
        return ParsedSDSession(
            directory=directory, csv_name=csv_path.name, experiment_id=experiment_id,
            firmware_sha256=firmware, device_id=headers.get("device"),
            start_uptime_us=start, stop_uptime_us=stop, rows=tuple(rows), integrity=report,
        )
    except ReplayValidationError:
        raise
    except (OSError, ValueError, csv.Error, UnicodeError) as exc:
        raise ReplayValidationError([str(exc)]) from exc
