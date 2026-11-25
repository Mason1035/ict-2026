"""只读审计 NODE01 工程采集 ZIP；不转换成正式训练 CSV，不生成标定阈值。"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import statistics
import sys
import zipfile
import zlib
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from local_tools.common import dump, loads, sha256


def inspect_capture(data, begin, end):
    issues, comments = [], []
    lines = data.decode("utf-8-sig").splitlines()
    comments = [line for line in lines if line.startswith("#")]
    if not comments or "NODE01_ENGINEERING_DIAGNOSTIC_V1" not in comments[0]:
        raise ValueError("不是已支持的 NODE01 工程诊断文件")
    reader = csv.DictReader(line for line in lines if not line.startswith("#"))
    required = {"kind", "channel", "acquisition_index", "acquired_uptime_us", "validity", "error", "soil_raw",
                "gx_dps", "gy_dps", "gz_dps"}
    if not required <= set(reader.fieldnames or []):
        raise ValueError("工程 CSV 缺少必需列")
    channels = defaultdict(lambda: {"rows": 0, "validity": Counter(), "times": [], "soil": [],
                                    "gyro": {k: [] for k in ("gx_dps", "gy_dps", "gz_dps")}})
    rows, previous_index = 0, None
    for row in reader:
        rows += 1
        try:
            index = int(row["acquisition_index"])
            if index != (0 if previous_index is None else previous_index + 1):
                issues.append(f"INDEX_DISCONTINUITY_ROW_{rows}")
            previous_index = index
            key = (row["kind"], int(row["channel"]))
            if key not in (("imu", 0), ("imu", 1), ("soil", 0), ("soil", 1), ("soil", 2)):
                raise ValueError("未知通道身份")
            state = channels[key]
            state["rows"] += 1
            state["validity"][row["validity"]] += 1
            if row["validity"] != "Valid":
                continue
            t = int(row["acquired_uptime_us"])
            if state["times"] and t <= state["times"][-1]:
                issues.append(f"CHANNEL_TIME_REVERSAL_ROW_{rows}")
            state["times"].append(t)
            if row["error"] != "0":
                issues.append(f"VALID_WITH_ERROR_ROW_{rows}")
            if key[0] == "soil":
                value = int(row["soil_raw"])
                if not -32768 <= value <= 32767:
                    raise ValueError("ADC 超出有符号码范围")
                state["soil"].append(value)
            else:
                for k in state["gyro"]:
                    value = float(row[k])
                    if not math.isfinite(value):
                        raise ValueError("非有限角速度")
                    state["gyro"][k].append(value)
        except (ValueError, KeyError, TypeError) as exc:
            issues.append(f"INVALID_ROW_{rows}: {exc}")
    if rows == 0:
        issues.append("EMPTY_CAPTURE")
    if begin.get("experiment_id") != end.get("experiment_id"):
        issues.append("EXPERIMENT_ID_MISMATCH")
    if begin.get("elf_sha256") != end.get("elf_sha256"):
        issues.append("FIRMWARE_ID_MISMATCH")
    for field in ("accepted", "verified_rows"):
        if end.get(field) != rows:
            issues.append(field.upper() + "_MISMATCH")
    if end.get("csv_bytes") != len(data):
        issues.append("BYTE_COUNT_MISMATCH")
    crc = f"{zlib.crc32(data) & 0xffffffff:08x}"
    if str(end.get("csv_crc32", "")).lower() != crc:
        issues.append("CRC32_MISMATCH")
    for field in ("csv_verified", "storage_clean"):
        if end.get(field) is not True:
            issues.append(field.upper() + "_NOT_CONFIRMED")
    for field in ("queue_drop", "internal_drop", "errors", "uncertain", "replay", "i2c_errors", "lock_timeouts", "sensor_errors"):
        if end.get(field) != 0:
            issues.append(field.upper() + "_NONZERO_OR_UNKNOWN")
    duration = end.get("actual_duration_us")
    if type(duration) is not int or duration <= 0 or end.get("stop_us", 0) - end.get("start_us", 0) != duration:
        issues.append("DURATION_INCONSISTENT")
        duration = None
    summaries = {}
    for kind, count in (("imu", 2), ("soil", 3)):
        for channel in range(count):
            key = (kind, channel)
            s = channels[key]
            expected = end.get("top_valid" if channel == 0 else "toe_valid") if kind == "imu" else (end.get("soil_valid") or [None]*3)[channel]
            if s["validity"]["Valid"] != expected:
                issues.append(f"{kind}_{channel}_VALID_COUNT_MISMATCH")
            if not s["rows"]:
                issues.append(f"{kind}_{channel}_MISSING")
            intervals = [b-a for a, b in zip(s["times"], s["times"][1:])]
            item = {"rows": s["rows"], "validity": dict(s["validity"]),
                    "valid_samples_per_capture_second": s["validity"]["Valid"] * 1e6 / duration if duration else None,
                    "median_interval_us": statistics.median(intervals) if intervals else None,
                    "max_interval_us": max(intervals) if intervals else None}
            if kind == "soil":
                values = s["soil"]
                diffs = [abs(b-a) for a, b in zip(values, values[1:])]
                item.update(raw_min=min(values) if values else None, raw_max=max(values) if values else None,
                            median_adjacent_absolute_difference_raw=statistics.median(diffs) if diffs else None)
            else:
                item["diagnostic_gyro_means_dps_NOT_CALIBRATION"] = {
                    k: statistics.fmean(v) if v else None for k, v in s["gyro"].items()}
            summaries[f"{kind}_{channel}"] = item
    return {"experiment_id": end.get("experiment_id"), "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data), "crc32": crc, "rows": rows,
            "duration_seconds": duration / 1e6 if duration else None,
            "engineering_integrity": "CHECKED" if not issues else "REVIEW_REQUIRED",
            "issues": issues, "channels": summaries,
            "calibration_status": end.get("calibration_status"), "formal_training_ready": False,
            "clock": "BOOT_LOCAL_MICROSECONDS_UTC_UNAVAILABLE", "header_evidence": comments}


def audit_archive(path):
    path = Path(path)
    result = {"schema": "B.engineering_archive_audit.v1", "archive_sha256": sha256(path),
              "scope": "REAL_SENSOR_ENGINEERING_DIAGNOSTIC_UNCALIBRATED", "formal_training_ready": False,
              "calibrated_runtime_ready": False, "captures": [], "members": []}
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(set(names)) != len(names):
            raise ValueError("ZIP 有重复路径，拒绝不明确配对")
        for entry in archive.infolist():
            if not entry.is_dir():
                result["members"].append({"name": entry.filename, "bytes": entry.file_size,
                    "sha256": hashlib.sha256(archive.read(entry)).hexdigest()})
        for name in sorted(n for n in names if n.upper().endswith(".CSV")):
            stem = name.rsplit(".", 1)[0]
            if stem + ".BEG" not in names or stem + ".END" not in names:
                result["captures"].append({"file": name, "engineering_integrity": "MISSING_BEG_END"})
                continue
            capture = inspect_capture(archive.read(name), loads(archive.read(stem + ".BEG").decode("utf-8-sig")),
                                      loads(archive.read(stem + ".END").decode("utf-8-sig")))
            capture["file"] = name
            parent = name.rsplit("/", 1)[0] + "/" if "/" in name else ""
            capture["missing_companions"] = [p for p in ("device.txt", "events.jsonl") if parent+p not in names]
            result["captures"].append(capture)
    result["next_step"] = "CALIBRATION_GATE_REVIEW_REQUIRED_NOT_THRESHOLD_FITTING"
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = audit_archive(args.archive)
    dump(args.output, report)
    print(json.dumps({"captures": len(report["captures"]), "formal_training_ready": False,
                      "output": str(args.output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
