"""Read verified public observations without inventing project inputs or labels.

Only NumPy and the standard library are required. MATLAB input is parsed as
bounded numeric v5 matrices, never as executable objects or pickles.
"""

import csv
from datetime import datetime
import math
from pathlib import Path
import re
import struct
import zlib

import numpy as np

from .data import SensorSeries


LISA_DOI = "10.7910/DVN/0H4AVF"
SMARTSTONE_DOI = "10.5281/zenodo.4316597"
_TDR_FILES = (
    ("TDR_centre_slope_measurements.csv", "vwc_centre_slope"),
    ("TDR_downslope_measurements.csv", "vwc_downslope"),
    ("TDR_upslope_measurements.csv", "vwc_upslope"),
)
_NUMBER = re.compile(r"[+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+)(?:[eE][+-]?\d+)?")


def _native_number(text):
    text = text.strip()
    if not _NUMBER.fullmatch(text):
        raise ValueError("not a single source-native numeric value")
    value = float(text.replace(",", "."))
    if not math.isfinite(value):
        raise ValueError("non-finite source observation")
    return value


def _csv_rows(path, *, encoding="utf-8-sig"):
    with path.open(encoding=encoding, newline="") as stream:
        yield from enumerate(csv.reader(stream, delimiter=";"), 1)


def _date_key(text):
    try:
        return datetime.strptime(text.split()[0], "%d/%m/%Y").date().isoformat()
    except (ValueError, IndexError):
        # Unknown dates are conservatively kept together, never made independent.
        return "unknown-date"


def _lisa_groups(experiments):
    parents = {item["date"]: item["date"] for item in experiments.values()}

    def find(key):
        while parents[key] != key:
            parents[key] = parents[parents[key]]
            key = parents[key]
        return key

    # Notes explicitly identify 18--22 as successive rainfall tests on one
    # physical slope, spanning two days. Date grouping alone would leak it.
    related = [experiments[str(i)]["date"] for i in range(18, 23) if str(i) in experiments]
    for date in related[1:]:
        a, b = find(related[0]), find(date)
        parents[max(a, b)] = min(a, b)
    members = {}
    for date in sorted(parents):
        members.setdefault(find(date), []).append(date)
    return {key: "LISA:dates:" + "+".join(members[find(item["date"])])
            for key, item in experiments.items()}


def _clean_observations(records):
    """Stable source-time ordering; first source row wins an exact duplicate."""
    kept, seen, duplicate_rows = [], set(), []
    for record in sorted(records, key=lambda item: item[0]):
        if record[0] in seen:
            duplicate_rows.append(record[2])
        else:
            seen.add(record[0])
            kept.append(record)
    return kept, duplicate_rows


def load_lisa(root: Path) -> list[SensorSeries]:
    """Load original headerless semicolon CSVs; predict the next observation.

    TDR time units are not established by the supplied user guide. Original
    relative numbers are retained; they must not be treated as seconds. Each
    sensor position remains a separate sequence, never an invented synchronous
    three-channel sample. First-fracture text is evidence metadata, not a label.
    """
    root = Path(root)
    experiments = {}
    for row_index, row in _csv_rows(root / "Experiments.csv"):
        if not row:
            continue
        if len(row) != 9 or not row[0].isdigit() or row[0] in experiments:
            raise ValueError(f"Experiments.csv record {row_index}: malformed/duplicate experiment")
        experiments[row[0]] = {
            "date": _date_key(row[1]), "date_raw": row[1],
            "rainfall_description": row[4], "starting_time_raw": row[5],
            "ending_time_raw": row[6], "first_visible_fracture_raw": row[8],
        }
    if not experiments:
        raise ValueError("LISA experiment registry is empty")
    notes = {}
    note_path = root / "Tab_Note.csv"
    if note_path.is_file():
        for _, row in _csv_rows(note_path, encoding="cp1252"):
            if len(row) == 3:
                notes.setdefault(row[1], []).append(row[2])
    groups = _lisa_groups(experiments)
    missing = [name for name, _ in _TDR_FILES if not (root / name).is_file()]
    output = []
    for filename, channel in _TDR_FILES:
        path = root / filename
        if not path.is_file():
            continue
        rows_by_run, counts, unit_ambiguities = {}, {}, {}
        table_exclusions = {"malformed_record": 0, "unknown_experiment": 0}
        for record_index, row in _csv_rows(path):
            if not row:
                continue
            if len(row) != 4:
                table_exclusions["malformed_record"] += 1
                continue
            run = row[1]
            if run not in experiments:
                table_exclusions["unknown_experiment"] += 1
                continue
            stat = counts.setdefault(run, {"source_records": 0, "invalid_time": 0, "invalid_value": 0,
                                           "invalid_value_range": 0})
            stat["source_records"] += 1
            try:
                stamp = _native_number(row[2])
            except ValueError:
                stat["invalid_time"] += 1
                continue
            try:
                value = _native_number(row[3])
            except ValueError:
                stat["invalid_value"] += 1
                continue
            # The source guide defines VWC as a volume fraction. An impossible
            # fraction may indicate mixed units; quarantine this entire sensor
            # sequence rather than guessing a percentage conversion or clipping.
            if not 0 <= value <= 1:
                stat["invalid_value_range"] += 1
                unit_ambiguities.setdefault(run, []).append({
                    "source_record_index": record_index, "measurement_id": row[0],
                    "source_time": stamp, "source_value": value,
                })
                continue
            rows_by_run.setdefault(run, []).append((stamp, (value,), record_index))
        quarantined = []
        for run in sorted(unit_ambiguities, key=int):
            rows_by_run.pop(run, None)
            quarantined.append({
                "experiment_id": run, "channel_name": channel,
                "reason": "unit_ambiguity: VWC fraction outside physical [0,1]",
                "source_records": counts[run]["source_records"],
                "invalid_value_range": counts[run]["invalid_value_range"],
                "out_of_range_records": unit_ambiguities[run],
            })
        table_exclusions["invalid_value_range"] = sum(item["invalid_value_range"] for item in quarantined)
        table_exclusions["unit_ambiguity_records"] = sum(item["source_records"] for item in quarantined)
        for run in sorted(rows_by_run, key=int):
            records, duplicates = _clean_observations(rows_by_run[run])
            stat = counts[run]
            provenance = {
                "doi": LISA_DOI, "url": "https://doi.org/" + LISA_DOI,
                "license": "CC-BY-4.0", "source_type": "REAL",
                "dataset_role": "PUBLIC_EXTERNAL_RESEARCH", "source_file": filename,
                "experiment_id": run, "experiment_date": experiments[run]["date"],
                "measurement": "volumetric_water_content", "source_time_unit_confirmed": False,
                "target": "next_observation", "label_status": "NOT_PROVIDED",
                "event_metadata": dict(experiments[run], notes=notes.get(run, [])),
                "grouping_policy": "same experiment date; merge documented related experiments 18-22",
                "grouping_limit": "other cross-date physical lineage is not guaranteed independent",
                "ordering_policy": "stable source-time sort; keep first duplicate observation",
                "exclusions": {"invalid_time": stat["invalid_time"], "invalid_value": stat["invalid_value"],
                               "invalid_value_range": stat["invalid_value_range"], "duplicate_time": len(duplicates)},
                "table_exclusions": table_exclusions.copy(), "source_records": stat["source_records"],
                "retained_records": len(records), "source_record_indices": [r[2] for r in records],
                "duplicate_record_indices": duplicates, "missing_source_tables": missing,
                "quarantined_sequences": quarantined,
            }
            output.append(SensorSeries(
                source_id="LISA", run_id="LISA:" + run, group_id=groups[run], modality="soil",
                values=np.asarray([r[1] for r in records]), times=np.asarray([r[0] for r in records]),
                channel_names=(channel,), units=("1",), time_unit="source_relative_time", provenance=provenance,
            ))
    if not output:
        raise ValueError("LISA contains no usable TDR observation sequences")
    return output


_MAX_MAT_BYTES = 32 * 1024 * 1024
_MAX_INFLATED_BYTES = 64 * 1024 * 1024
_MAT_DTYPES = {1: "i1", 2: "u1", 3: "i2", 4: "u2", 5: "i4", 6: "u4",
               7: "f4", 9: "f8", 12: "i8", 13: "u8"}
_MAT_CLASSES = {6: 9, 7: 7, 8: 1, 9: 2, 10: 3, 11: 4, 12: 5, 13: 6, 14: 12, 15: 13}


def _element(data, offset, endian):
    if offset + 8 > len(data):
        raise ValueError("truncated MATLAB element tag")
    small_kind, small_size = struct.unpack_from(endian + "HH", data, offset)
    if small_kind and 1 <= small_size <= 4:
        return small_kind, data[offset + 4:offset + 4 + small_size], offset + 8
    kind, size = struct.unpack_from(endian + "II", data, offset)
    end = offset + 8 + size
    if end > len(data):
        raise ValueError("truncated MATLAB element payload")
    # miCOMPRESSED is stored without eight-byte padding by the source files.
    next_offset = end if kind == 15 else offset + 8 + ((size + 7) // 8) * 8
    if next_offset > len(data):
        raise ValueError("truncated MATLAB element padding")
    return kind, data[offset + 8:end], next_offset


def _numeric_matrix(payload, endian):
    kind, flags, offset = _element(payload, 0, endian)
    if kind != 6 or len(flags) != 8:
        raise ValueError("invalid MATLAB array flags")
    flag = struct.unpack_from(endian + "I", flags)[0]
    array_class = flag & 255
    if array_class not in _MAT_CLASSES or flag & (0x800 | 0x200):
        raise ValueError("only real dense numeric MATLAB arrays are supported")
    kind, dims, offset = _element(payload, offset, endian)
    if kind != 5 or not dims or len(dims) % 4:
        raise ValueError("invalid MATLAB numeric dimensions")
    shape = struct.unpack(endian + "i" * (len(dims) // 4), dims)
    if len(shape) < 2 or len(shape) > 8 or any(d < 0 for d in shape) or math.prod(shape) > 8_000_000:
        raise ValueError("unsupported MATLAB numeric array shape")
    kind, name, offset = _element(payload, offset, endian)
    if kind not in (1, 16):
        raise ValueError("invalid MATLAB array name")
    try:
        name = name.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("invalid MATLAB array name encoding") from exc
    if not name or "\x00" in name:
        raise ValueError("invalid MATLAB array name")
    kind, values, offset = _element(payload, offset, endian)
    if kind != _MAT_CLASSES[array_class]:
        raise ValueError("MATLAB storage type differs from numeric array class")
    dtype = np.dtype(endian + _MAT_DTYPES[kind])
    if len(values) != math.prod(shape) * dtype.itemsize or offset != len(payload):
        raise ValueError("MATLAB numeric array length mismatch")
    return name, np.frombuffer(values, dtype=dtype).reshape(shape, order="F").copy()


def _read_mat_numeric(path):
    path = Path(path)
    if path.stat().st_size > _MAX_MAT_BYTES:
        raise ValueError("MATLAB file exceeds the numeric reader size limit")
    data = path.read_bytes()
    if len(data) < 128 or data[126:128] not in (b"IM", b"MI"):
        raise ValueError("expected a MATLAB v5 file")
    endian = "<" if data[126:128] == b"IM" else ">"
    if struct.unpack(endian + "H", data[124:126])[0] != 0x100:
        raise ValueError("unsupported MATLAB file version")
    arrays = {}

    def read_elements(buffer, depth=0):
        if depth > 3:
            raise ValueError("MATLAB compressed nesting exceeds reader limit")
        offset = 0
        while offset < len(buffer):
            kind, payload, offset = _element(buffer, offset, endian)
            if kind == 15:
                inflater = zlib.decompressobj()
                try:
                    expanded = inflater.decompress(payload, _MAX_INFLATED_BYTES + 1)
                except zlib.error as exc:
                    raise ValueError("invalid MATLAB compressed stream") from exc
                if (len(expanded) > _MAX_INFLATED_BYTES or not inflater.eof
                        or inflater.unconsumed_tail or inflater.unused_data):
                    raise ValueError("MATLAB compressed stream exceeds bounds or is truncated")
                read_elements(expanded, depth + 1)
            elif kind == 14:
                name, array = _numeric_matrix(payload, endian)
                if name in arrays:
                    raise ValueError("duplicate MATLAB numeric array name")
                arrays[name] = array
            else:
                raise ValueError("only numeric MATLAB matrix/compressed elements are supported")

    read_elements(data[128:])
    return arrays


def load_smartstone(root: Path) -> list[SensorSeries]:
    """Read four unsynchronized stones from a single physical experiment.

    Numeric acc/gyr values and timecodes are retained without converting their
    unverified file-native units, assigning top/toe positions, or inferring labels.
    """
    root = Path(root)
    paths = sorted(p for p in root.glob("ProbeData_*.mat")
                   if re.fullmatch(r"ProbeData_[1-9]\d*\.mat", p.name))
    if not paths:
        raise FileNotFoundError("no Smartstone ProbeData_*.mat observations found")
    output = []
    for path in paths:
        arrays = _read_mat_numeric(path)
        if not {"acc", "gyr", "time"} <= arrays.keys():
            raise ValueError(f"{path.name}: missing acc/gyr/time numeric arrays")
        acc, gyr, time = (arrays[key] for key in ("acc", "gyr", "time"))
        if (acc.ndim != 2 or acc.shape[1] != 3 or gyr.shape != acc.shape
                or time.ndim != 2 or 1 not in time.shape or time.size != len(acc)):
            raise ValueError(f"{path.name}: acc/gyr/time shape mismatch")
        values, stamps = np.column_stack((acc, gyr)), time.ravel()
        records, invalid_times, invalid_values = [], [], []
        for index, (stamp, row) in enumerate(zip(stamps, values), 1):
            if not np.isfinite(stamp):
                invalid_times.append(index)
            elif not np.isfinite(row).all():
                invalid_values.append(index)
            else:
                records.append((float(stamp), tuple(row), index))
        records, duplicates = _clean_observations(records)
        if not records:
            raise ValueError(f"{path.name}: no finite motion observations")
        output.append(SensorSeries(
            source_id="SMARTSTONE", run_id="SMARTSTONE:" + path.stem,
            group_id="SMARTSTONE:4316597:single_experiment", modality="motion",
            values=np.asarray([r[1] for r in records]), times=np.asarray([r[0] for r in records]),
            channel_names=("acc_x", "acc_y", "acc_z", "gyr_x", "gyr_y", "gyr_z"),
            units=("source_native_acc",) * 3 + ("source_native_gyr",) * 3,
            time_unit="source_native_timecode",
            provenance={
                "doi": SMARTSTONE_DOI, "url": "https://doi.org/" + SMARTSTONE_DOI,
                "license": "CC-BY-4.0", "source_type": "REAL", "dataset_role": "PUBLIC_EXTERNAL_RESEARCH",
                "source_file": path.name, "stone_id": path.stem.split("_")[-1],
                "target": "next_observation", "label_status": "NOT_PROVIDED",
                "native_units_confirmed": False, "timecode_is_utc": False, "cross_probe_sync_confirmed": False,
                "grouping_policy": "all stones share one physical landslide experiment",
                "ordering_policy": "stable source-time sort; keep first duplicate observation",
                "source_records": len(values), "retained_records": len(records),
                "exclusions": {"invalid_time": len(invalid_times), "invalid_value": len(invalid_values),
                               "duplicate_time": len(duplicates)},
                "source_record_indices": [r[2] for r in records], "duplicate_record_indices": duplicates,
            },
        ))
    return output
