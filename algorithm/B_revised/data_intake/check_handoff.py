"""A→B 交接材料预检；仅核对引用/哈希/CSV，不核验物理真实性。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data_intake.check_experiment_csv import inspect_csv
from local_tools.common import dump, inside, load, sha256

SIDECARS = ("timing", "validity", "sensor_calibration", "experiment_log", "label_evidence")


def inspect_handoff(manifest_path):
    manifest_path = Path(manifest_path)
    report = {"schema": "B.handoff_preflight.v1", "status": "WAITING_FOR_A",
              "formal_training_ready": False, "real_data_verified": False,
              "manifest_sha256": sha256(manifest_path), "missing": [], "issues": [], "files": {},
              "notes": ["本 manifest 是 B 交接提案，不改团队 20 列 CSV 或 Telemetry。",
                        "材料存在和哈希相符不等于采样、标签、标定或独立 Test 已核验。"]}
    doc = load(manifest_path)
    if not isinstance(doc, dict) or doc.get("schema") != "B.run_handoff.draft.v1":
        report["issues"].append("HANDOFF_SCHEMA_MISMATCH")
        report["status"] = "INVALID_HANDOFF"
        return report
    if doc.get("source") not in ("REAL", "TEST_ONLY"):
        report["missing"].append("source")
    report["source"] = doc.get("source")
    for key in ("run_id", "frame_id", "firmware_version", "calibration_version"):
        if not isinstance(doc.get(key), str) or not doc[key].strip():
            report["missing"].append(key)
    identity = doc.get("identity")
    if not isinstance(identity, dict):
        report["missing"].append("identity")
    else:
        for key in ("site_id", "device_id"):
            if not isinstance(identity.get(key), str) or not identity[key].strip():
                report["missing"].append(f"identity.{key}")
        if type(identity.get("boot_id")) is not int or identity["boot_id"] < 0:
            report["missing"].append("identity.boot_id")
    odr = doc.get("odr_hz")
    if not isinstance(odr, dict) or any(type(odr.get(k)) not in (int, float) or
                                       not 0 < odr[k] < float("inf") for k in ("imu", "soil")):
        report["missing"].append("odr_hz")
    sensors = doc.get("sensor_ids")
    for group, positions in (("imu", ("top", "toe")), ("soil", ("top", "middle", "toe"))):
        group_ids = sensors.get(group, {}) if isinstance(sensors, dict) else {}
        if not isinstance(group_ids, dict):
            group_ids = {}
        for pos in positions:
            if not isinstance(group_ids.get(pos), str) or not group_ids[pos].strip():
                report["missing"].append(f"sensor_ids.{group}.{pos}")
    root = manifest_path.parent
    references = {"csv": doc.get("csv")}
    sides = doc.get("sidecars")
    references.update({name: sides.get(name) if isinstance(sides, dict) else None for name in SIDECARS})
    used_paths = set()
    for name, reference in references.items():
        if not isinstance(reference, dict) or not reference.get("path") or not reference.get("sha256"):
            report["missing"].append(name)
            continue
        try:
            path = inside(root, reference["path"])
            if path in used_paths:
                raise ValueError("同一文件不能冒充多种独立交接材料")
            used_paths.add(path)
            if not path.is_file():
                report["missing"].append(name + ".file")
                continue
            expected = reference["sha256"]
            if not isinstance(expected, str) or len(expected) != 64:
                raise ValueError("需要 64 字符 SHA-256")
            actual = sha256(path)
            if expected.lower() != actual:
                raise ValueError("文件 SHA-256 不一致")
            report["files"][name] = {"path": reference["path"], "sha256": actual,
                                      "bytes": path.stat().st_size}
            if path.stat().st_size == 0:
                raise ValueError("交接文件为空")
            if name == "csv":
                csv_report = inspect_csv(path)
                report["csv_report"] = csv_report
                if csv_report["status"] != "CSV_CHECKED":
                    report["issues"].append("CSV_REVIEW_REQUIRED")
                if set(csv_report["runs"]) != {doc.get("run_id")}:
                    report["issues"].append("CSV_RUN_ID_MISMATCH")
        except (ValueError, OSError, TypeError) as exc:
            report["issues"].append(f"{name}: {exc}")
    report["status"] = ("INVALID_HANDOFF" if report["issues"] else "WAITING_FOR_A" if report["missing"]
                        else "MATERIALS_PRESENT_REVIEW_REQUIRED")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="A→B 交接提案预检，永不自动批准真实训练")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, help="新建 JSON 报告，拒绝覆盖")
    args = parser.parse_args(argv)
    try:
        report = inspect_handoff(args.manifest)
        if args.output:
            dump(args.output, report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["status"] == "MATERIALS_PRESENT_REVIEW_REQUIRED" else 2
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
