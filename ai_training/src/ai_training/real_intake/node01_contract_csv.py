"""Deterministic NODE01 long-table to A→B CSV conversion (standard library only)."""
from __future__ import annotations

import argparse
from bisect import bisect_left
from collections import Counter
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import re
import shutil
import sys
import tempfile
import zlib

VERSION = "node01-contract-csv-v1"
COLUMNS = tuple(("kind,channel,acquisition_index,attempted_uptime_us,acquired_uptime_us,"
                 "timestamp_ms,time_synced,validity,error,ax_raw,ay_raw,az_raw,gx_raw,gy_raw,gz_raw,"
                 "ax_mps2,ay_mps2,az_mps2,gx_dps,gy_dps,gz_dps,soil_raw").split(","))
HEADER = tuple(("run_id,timestamp_ms,top_ax,top_ay,top_az,top_gx,top_gy,top_gz,"
                "toe_ax,toe_ay,toe_az,toe_gx,toe_gy,toe_gz,soil_top_raw,soil_middle_raw,"
                "soil_toe_raw,flow_lpm,rain_level,label").split(","))
IMU_FIELDS = COLUMNS[15:21]
SOIL_FIELDS = HEADER[14:17]
TIME_BASIS = "DEVICE_UPTIME_US_UNSYNCED"
TIMING = ("row_index", "top_acquisition_index", "top_acquired_uptime_us",
          "toe_acquisition_index", "toe_acquired_uptime_us", "toe_minus_top_us",
          *(f"soil_ch{c}_{field}" for c in range(3)
            for field in ("acquisition_index", "acquired_uptime_us")),
          "anchor_uptime_us", "time_basis",
          *(f"soil_ch{c}_to_anchor_us" for c in range(3)))
VALIDITY = ("acquisition_index", "kind", "channel", "attempted_uptime_us", "validity", "error", "row_index")


class ConversionError(ValueError):
    """Input or output refusal, exposed as JSON by the CLI."""


def require(condition, reason):
    if not condition:
        raise ConversionError(reason)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def integer(value, field, *, signed=False):
    require(not isinstance(value, bool) and isinstance(value, (str, int))
            and re.fullmatch(r"-?\d+" if signed else r"\d+", str(value), flags=re.ASCII),
            f"INVALID_INTEGER: {field}={value!r}")
    return int(value)


def time_of(row):
    return int(row["acquired_uptime_us"] or row["attempted_uptime_us"])


def _sidecar(path, explicit, suffix):
    if explicit is not None:
        return Path(explicit).resolve()
    matches = sorted(path.parent.glob(path.stem + "*" + suffix))
    require(len(matches) == 1, f"SIDECAR_NOT_UNIQUE: {suffix}: {len(matches)} candidates")
    return matches[0].resolve()


def _load(csv_path, beg, end, session):
    paths = {"csv": csv_path, "beg": _sidecar(csv_path, beg, ".BEG"),
             "end": _sidecar(csv_path, end, ".END")}
    session_path = Path(session).resolve() if session is not None else csv_path.parent / "session.json"
    if session is not None or session_path.exists():
        paths["session"] = session_path
    blobs = {k: p.read_bytes() for k, p in paths.items()}
    begin, terminal = (json.loads(blobs[k]) for k in ("beg", "end"))
    require(isinstance(begin, dict) and begin.get("record_type") == "START_INTENT", "INVALID_BEG")
    require(isinstance(terminal, dict) and terminal.get("record_type") == "END", "INVALID_END")
    identity = begin.get("experiment_id")
    require(isinstance(identity, str) and identity and identity == terminal.get("experiment_id"),
            "EXPERIMENT_ID_MISMATCH")
    require(identity.endswith("-" + csv_path.name), "EXPERIMENT_ID_CSV_MISMATCH")
    require(begin.get("csv") == terminal.get("csv")
            and isinstance(begin.get("csv"), str)
            and begin["csv"].rsplit("/", 1)[-1] == csv_path.name, "LOGICAL_CSV_MISMATCH")
    firmware = begin.get("elf_sha256")
    require(isinstance(firmware, str) and re.fullmatch(r"[0-9a-fA-F]{64}", firmware)
            and firmware == terminal.get("elf_sha256"), "ELF_SHA256_MISMATCH")
    data = blobs["csv"]
    require(len(data) == integer(terminal.get("csv_bytes"), "csv_bytes"), "CSV_BYTES_MISMATCH")
    require(f"{zlib.crc32(data):08x}" == str(terminal.get("csv_crc32")).lower(), "CSV_CRC32_MISMATCH")
    stream = io.StringIO(data.decode("utf-8"), newline="")
    metadata = {}
    while True:
        pos = stream.tell()
        line = stream.readline()
        if not line.startswith("#"):
            stream.seek(pos)
            break
        for part in line[1:].strip().split(";"):
            if "=" in part:
                key, value = part.strip().split("=", 1)
                require(key not in metadata or metadata[key] == value, f"CONFLICTING_HEADER: {key}")
                metadata[key] = value
    require(metadata.get("app_elf_sha256") == firmware, "CSV_ELF_SHA256_MISMATCH")
    require(metadata.get("experiment_id", identity) == identity, "CSV_EXPERIMENT_ID_MISMATCH")
    reader = csv.reader(stream, strict=True)
    require(tuple(next(reader, ())) == COLUMNS, "HEADER_MISMATCH")
    rows = []
    counts = Counter()
    for values in reader:
        require(len(values) == 22, f"COLUMN_COUNT: observation {len(rows)}")
        row = dict(zip(COLUMNS, values))
        require(integer(row["acquisition_index"], "acquisition_index") == len(rows), "ACQUISITION_INDEX_DISCONTINUITY")
        channel = integer(row["channel"], "channel")
        require((row["kind"] == "imu" and channel in (0, 1))
                or (row["kind"] == "soil" and channel in (0, 1, 2)), "UNKNOWN_SENSOR")
        integer(row["attempted_uptime_us"], "attempted_uptime_us")
        integer(row["error"], "error", signed=True)
        require(row["time_synced"] in ("true", "false"), "INVALID_TIME_SYNCED")
        require(bool(row["validity"]), "MISSING_VALIDITY")
        if row["acquired_uptime_us"]:
            integer(row["acquired_uptime_us"], "acquired_uptime_us")
        if row["timestamp_ms"]:
            integer(row["timestamp_ms"], "timestamp_ms")
        if row["validity"] == "Valid":
            require(bool(row["acquired_uptime_us"]), "VALID_ROW_MISSING_ACQUIRED_TIME")
            if row["kind"] == "imu":
                for field in IMU_FIELDS:
                    require(bool(row[field]) and math.isfinite(float(row[field])), f"INVALID_MEASUREMENT: {field}")
            else:
                integer(row["soil_raw"], "soil_raw", signed=True)
            counts[(row["kind"], channel)] += 1
        rows.append(row)
    require(bool(rows), "NO_DATA_ROWS")
    require(len(rows) == integer(terminal.get("accepted"), "accepted"), "ACCEPTED_COUNT_MISMATCH")
    if "verified_rows" in terminal:
        require(len(rows) == integer(terminal["verified_rows"], "verified_rows"), "VERIFIED_ROWS_MISMATCH")
    soils = terminal.get("soil_valid")
    require(isinstance(soils, list) and len(soils) == 3, "INVALID_SOIL_COUNTS")
    for sensor, declared in zip((("imu", 0), ("imu", 1), ("soil", 0), ("soil", 1), ("soil", 2)),
                                (terminal.get("top_valid"), terminal.get("toe_valid"), *soils)):
        require(counts[sensor] == integer(declared, str(sensor)), f"VALID_COUNT_MISMATCH: {sensor}")
    host = None
    if "session" in blobs:
        session_data = json.loads(blobs["session"])
        experiments = [e for e in session_data.get("experiments", []) if e.get("experiment_id") == identity]
        require(len(experiments) == 1, "SESSION_EXPERIMENT_ID_NOT_UNIQUE")
        e = experiments[0]
        host = {"begin_observation": e.get("begin_observation"),
                "terminal_observation": e.get("terminal_observation"),
                "device_time_sync": e.get("device_time_sync"),
                "firmware_identity": session_data.get("firmware_identity")}
    sources = {k: {"path": str(paths[k]), "sha256": sha(b), "bytes": len(b)} for k, b in blobs.items()}
    return rows, metadata, begin, terminal, host, sources


class _Available:
    """Successor set with path compression; reversed set provides predecessors."""
    def __init__(self, size):
        self.parents = list(range(size + 1))

    def find(self, index):
        root = index
        while self.parents[root] != root:
            root = self.parents[root]
        while self.parents[index] != index:
            following = self.parents[index]
            self.parents[index] = root
            index = following
        return root

    def remove(self, index):
        self.parents[index] = self.find(index + 1)


def _align(rows, tolerance):
    top = sorted((r for r in rows if r["kind"] == "imu" and r["channel"] == "0"),
                 key=lambda r: (time_of(r), int(r["acquisition_index"])))
    toe = sorted((r for r in rows if r["kind"] == "imu" and r["channel"] == "1"),
                 key=lambda r: (time_of(r), int(r["acquisition_index"])))
    times = [time_of(r) for r in toe]
    size = len(toe)
    after, before = _Available(size), _Available(size)
    used = set()
    aligned = []
    for t in top:
        moment = time_of(t)
        split = bisect_left(times, moment)
        right = after.find(split)
        left = size - 1 - before.find(size - split)
        if left >= 0:
            # Several TOE observations may share a time; prefer the first index.
            left = after.find(bisect_left(times, times[left]))
        candidates = [i for i in (left, right) if 0 <= i < size]
        match = min(candidates, key=lambda i: (abs(times[i] - moment), times[i], int(toe[i]["acquisition_index"]))) if candidates else None
        if match is not None and abs(times[match] - moment) <= tolerance:
            used.add(match)
            after.remove(match)
            before.remove(size - 1 - match)
            aligned.append((moment, t, toe[match]))
        else:
            aligned.append((moment, t, None))
    aligned.extend((times[i], None, t) for i, t in enumerate(toe) if i not in used)
    aligned.sort(key=lambda item: (item[0], int((item[1] or item[2])["acquisition_index"])))
    return aligned


def _output_location(output):
    require(not output.is_symlink(), "OUTPUT_SYMLINK")
    output = output.resolve()
    require(not output.exists() or (output.is_dir() and not any(output.iterdir())), "OUTPUT_NOT_EMPTY")
    # Enforce this checkout's policy. Other directories (including pytest's
    # temporary root) may themselves have unrelated .git markers.
    for parent in Path(__file__).resolve().parents:
        if (parent / ".git").exists():
            if output.is_relative_to(parent):
                require(output.is_relative_to(parent / "work"), "OUTPUT_MUST_BE_OUTSIDE_REPO_OR_IGNORED_WORK")
                # This checkout excludes the entire work directory. A plain
                # directory rule with no later negations is sufficient evidence;
                # refuse more complex configurations rather than requiring Git
                # or attempting to implement its complete ignore language.
                rules = (parent / ".gitignore").read_text(encoding="utf-8").splitlines()
                ignored = False
                for rule in rules:
                    rule = rule.strip()
                    if rule in ("work/", "/work/"):
                        ignored = True
                    elif rule.startswith("!"):
                        ignored = False
                require(ignored, "OUTPUT_WORK_NOT_GITIGNORED")
            break
    return output


def _write_csv(path, header, rows):
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=header, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def convert(csv_path, output_dir, *, beg=None, end=None, session=None, run_id=None,
            pair_tolerance_us=5000, blank_ain2=False):
    """Validate all sources, then publish five files atomically. Never overwrite files.

    Ties prefer earlier TOE time, then acquisition index. TOP anchors are visited
    in time/index order. All row_index values are zero based.
    """
    try:
        require(isinstance(pair_tolerance_us, int) and pair_tolerance_us >= 0, "INVALID_PAIR_TOLERANCE")
        output = _output_location(Path(output_dir).expanduser())
        source = Path(csv_path).expanduser().resolve()
        require(not output.is_relative_to(source.parent), "OUTPUT_INSIDE_SOURCE_DIRECTORY")
        rows, metadata, begin, terminal, host, sources = _load(source, beg, end, session)
        run_id = begin["experiment_id"] if run_id is None else run_id
        require(isinstance(run_id, str) and bool(run_id.strip()) and run_id not in (".", "..")
                and not any(c in run_id for c in '/\\\x00\r\n'), "UNSAFE_OR_EMPTY_RUN_ID")
        aligned = _align(rows, pair_tolerance_us)
        require(bool(aligned), "NO_IMU_ANCHORS")
        contract, timing, affected = [], [], {}
        for index, (moment, top, toe) in enumerate(aligned):
            out = dict.fromkeys(HEADER, "")
            out["run_id"] = run_id
            time_row = dict.fromkeys(TIMING, "")
            time_row.update(row_index=index, anchor_uptime_us=moment, time_basis=TIME_BASIS)
            for position, record in (("top", top), ("toe", toe)):
                if record is None:
                    continue
                affected[record["acquisition_index"]] = index
                time_row[position + "_acquisition_index"] = record["acquisition_index"]
                time_row[position + "_acquired_uptime_us"] = record["acquired_uptime_us"]
                if record["validity"] == "Valid":
                    for axis, field in zip(("ax", "ay", "az", "gx", "gy", "gz"), IMU_FIELDS):
                        out[position + "_" + axis] = record[field]
            if top is not None and toe is not None:
                time_row["toe_minus_top_us"] = time_of(toe) - time_of(top)
            contract.append(out)
            timing.append(time_row)
        anchor_times = [a[0] for a in aligned]
        for record in rows:
            if record["kind"] != "soil":
                continue
            index = bisect_left(anchor_times, time_of(record))
            require(index < len(aligned), f"SOIL_AFTER_LAST_ANCHOR: acquisition_index={record['acquisition_index']}")
            channel = int(record["channel"])
            prefix = f"soil_ch{channel}_"
            require(timing[index][prefix + "acquisition_index"] == "", "SOIL_COLLISION_AT_FIRST_CAUSAL_ANCHOR")
            affected[record["acquisition_index"]] = index
            timing[index][prefix + "acquisition_index"] = record["acquisition_index"]
            timing[index][prefix + "acquired_uptime_us"] = record["acquired_uptime_us"]
            timing[index][prefix + "to_anchor_us"] = anchor_times[index] - time_of(record)
            if record["validity"] == "Valid" and not (blank_ain2 and channel == 2):
                contract[index][SOIL_FIELDS[channel]] = str(int(record["soil_raw"]))
        invalid = [{**{k: r[k] for k in VALIDITY if k != "row_index"},
                    "row_index": affected.get(r["acquisition_index"], "")}
                   for r in rows if r["validity"] != "Valid"]
        provenance = {"converter_version": VERSION, "sources": sources, "run_id": run_id,
                      "experiment_id": begin["experiment_id"], "elf_sha256": begin["elf_sha256"],
                      "begin": begin, "end": terminal, "csv_metadata": metadata, "session": host,
                      "source_data_rows": len(rows), "output_rows": len(contract),
                      "nonempty_cells": {k: sum(r[k] != "" for r in contract) for k in HEADER},
                      "source": "REAL_SENSOR_EXPERIMENT_UNCALIBRATED", "calibration_status": "NOT_READY",
                      "AIN2_DIAGNOSTIC_ONLY": True, "blank_ain2": blank_ain2,
                      "coordinate": "sensor_axes_unmapped", "timestamp_ms": "EMPTY_NO_TRUSTED_UTC",
                      "label": "EMPTY_NOT_ASSIGNED",
                      "mapping": {"imu": dict(zip(IMU_FIELDS, ("ax", "ay", "az", "gx", "gy", "gz"))),
                                  "imu_channels": {"0": "top", "1": "toe"},
                                  "soil_channels": dict(enumerate(SOIL_FIELDS)),
                                  "soil": "once at first anchor >= acquired (attempted for invalid); no hold/interpolation",
                                  "soil_offset": "soil_chN_to_anchor_us = anchor - observation time",
                                  "imu_pairing": "TOP time/index order; nearest unused TOE; ties earlier time then index; unmatched TOE own row",
                                  "pair_tolerance_us": pair_tolerance_us, "row_index": "zero based",
                                  "invalid_time": "acquired if available, otherwise attempted; toe_minus_top_us uses these times",
                                  "units": {"acceleration": "m/s²", "angular_velocity": "°/s", "soil": "ADC integer code"}}}
        output.parent.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix=".node01-", dir=output.parent))
        try:
            csv_name = run_id + ".contract.csv"
            _write_csv(stage / csv_name, HEADER, contract)
            _write_csv(stage / "timing.csv", TIMING, timing)
            _write_csv(stage / "validity.csv", VALIDITY, invalid)
            _write_json(stage / "provenance.json", provenance)
            reference = lambda name: {"path": name, "sha256": sha((stage / name).read_bytes())}
            empty = lambda: {"path": None, "sha256": None}
            handoff = {"schema": "B.run_handoff.draft.v1", "source": "REAL", "run_id": run_id,
                       "identity": {"site_id": None, "device_id": metadata.get("device"),
                                    "boot_id": None if metadata.get("boot_id") == "unavailable" else metadata.get("boot_id")},
                       "firmware_version": metadata.get("firmware"), "frame_id": None, "calibration_version": None,
                       "odr_hz": {"imu": 100, "soil": 2},
                       "sensor_ids": {"imu": {"top": None, "toe": None},
                                      "soil": {"top": None, "middle": None, "toe": None}},
                       "csv": reference(csv_name),
                       "sidecars": {"timing": reference("timing.csv"), "validity": reference("validity.csv"),
                                    "sensor_calibration": empty(), "experiment_log": empty(), "label_evidence": empty()}}
            _write_json(stage / "handoff.json", handoff)
            for info in sources.values():
                require(sha(Path(info["path"]).read_bytes()) == info["sha256"], "SOURCE_CHANGED_DURING_CONVERSION")
            require(not output.is_symlink(), "OUTPUT_SYMLINK")
            stage.rename(output)
        finally:
            if stage.exists():
                shutil.rmtree(stage)
        return provenance
    except ConversionError:
        raise
    except (OSError, ValueError, TypeError, KeyError, AttributeError, csv.Error, UnicodeError) as exc:
        raise ConversionError(str(exc)) from exc


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--beg", type=Path)
    parser.add_argument("--end", type=Path)
    parser.add_argument("--session", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--pair-tolerance-us", type=int, default=5000)
    parser.add_argument("--blank-ain2", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = convert(args.csv_path, args.output_dir, beg=args.beg, end=args.end, session=args.session,
                         run_id=args.run_id, pair_tolerance_us=args.pair_tolerance_us, blank_ain2=args.blank_ain2)
    except ConversionError as exc:
        print(json.dumps({"status": "REFUSED", "reason": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps({"status": "CONVERTED", "run_id": result["run_id"], "output_rows": result["output_rows"]}))
    return 0
