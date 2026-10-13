"""已校验输入的离线回放、候选特征导出与审计；不代替上游 Validator。"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from local_tools.common import dump, load, loads, sha256, verify_manifest
from telemetry_v2_intake import evaluate_telemetry_v2
from telemetry_v2_intake.runtime import FeatureRiskRuntime, fingerprint

FEATURE_COLUMNS = ("input_line", "device_id", "boot_id", "seq", "processing", "risk_execution",
                   "top_tilt_deg", "top_tilt_rate_dps", "top_vibration_rms",
                   "toe_tilt_deg", "toe_tilt_rate_dps", "toe_vibration_rms",
                   "soil_top_pct", "soil_middle_pct", "soil_toe_pct", "soil_avg_pct",
                   "soil_growth_pct_min", "sensor_score", "level")


def replay_records(records, config):
    runtime = FeatureRiskRuntime(config)
    outputs, durations = [], []
    for line, record in records:
        started = time.perf_counter_ns()
        if not isinstance(record, dict) or set(record) != {"payload", "context"}:
            raise ValueError(f"第 {line} 行必须恰好包含 payload、context")
        try:
            result = evaluate_telemetry_v2(record["payload"], context=record["context"], runtime=runtime)
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            result = {"risk_execution": "RISK_EXECUTION_BLOCKED", "feature_status": "BLOCKED",
                      "processing": "INPUT_REJECTED_NO_STATE_CHANGE", "blocked_reason": [str(exc)],
                      "risk": {"sensor_score": None, "level": None, "reason_mask": None}}
        elapsed = (time.perf_counter_ns() - started) / 1_000_000
        durations.append(elapsed)
        outputs.append({"input_line": line, "input_sha256": fingerprint(record), "result": result})
    if not outputs:
        raise ValueError("输入没有消息，不能生成空 PASS")
    counts = Counter(item["result"]["risk_execution"] for item in outputs)
    rejected = sum(item["result"]["processing"] == "INPUT_REJECTED_NO_STATE_CHANGE" for item in outputs)
    summary = {"schema": "B.replay_summary.v1", "scope": config["mode"], "formal_training_ready": False,
               "input_precondition": "UPSTREAM_VALIDATED_TELEMETRY_REQUIRED_NOT_VERIFIED_BY_REPLAY",
               "record_count": len(outputs), "rejected_count": rejected, "execution_counts": dict(counts),
               "config_hash": runtime.config["config_hash"], "feature_version": config["feature_version"],
               "calibration_version": config["calibration_version"],
               "latency_ms": {"mean": sum(durations) / len(durations), "max": max(durations)},
               "latency_scope": "THIS_HOST_OFFLINE_REFERENCE_ONLY_NOT_DEVICE_20HZ_CERTIFICATION"}
    return outputs, summary


def _flat(item):
    result = item["result"]
    row = {"input_line": item["input_line"], **result.get("identity", {}),
           "processing": result["processing"], "risk_execution": result["risk_execution"]}
    features = result.get("features", {})
    for pos in ("top", "toe"):
        for name in ("tilt_deg", "tilt_rate_dps", "vibration_rms"):
            row[f"{pos}_{name}"] = features.get("imu", {}).get(pos, {}).get(name)
    for name in ("top_pct", "middle_pct", "toe_pct", "avg_pct", "growth_pct_min"):
        row[f"soil_{name}"] = features.get("soil", {}).get(name)
    row.update(result["risk"])
    return [row.get(column) for column in FEATURE_COLUMNS]


def export_replay(input_path, config_path, output_dir):
    input_path, config_path, output_dir = map(Path, (input_path, config_path, output_dir))
    config = load(config_path)
    records = [(line, loads(text)) for line, text in enumerate(
        input_path.read_text(encoding="utf-8-sig").splitlines(), 1) if text.strip()]
    outputs, summary = replay_records(records, config)
    output_dir.mkdir(parents=True, exist_ok=False)
    # 保存确切原始输入和配置；不重写 Telemetry/null/source。
    shutil.copyfile(input_path, output_dir / "input.jsonl")
    shutil.copyfile(config_path, output_dir / "config.json")
    with (output_dir / "results.jsonl").open("x", encoding="utf-8", newline="\n") as stream:
        for item in outputs:
            stream.write(json.dumps(item, ensure_ascii=False, allow_nan=False) + "\n")
    with (output_dir / "candidate_features.csv").open("x", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(FEATURE_COLUMNS)
        writer.writerows(_flat(item) for item in outputs)
    summary.update(input_sha256=sha256(input_path), config_file_sha256=sha256(config_path))
    b_root = Path(__file__).resolve().parent.parent
    summary["producer_sha256"] = {
        name: sha256(b_root / name) for name in (
            "telemetry_v2_intake/replay.py", "telemetry_v2_intake/runtime.py",
            "telemetry_v2_intake/config.py", "telemetry_v2_intake/entry.py",
            "candidate_features/reference.py", "candidate_features/risk_math.py",
            "candidate_features/causal_window.py", "local_tools/common.py")}
    dump(output_dir / "summary.json", summary)
    dump(output_dir / "feature_table_contract.json", {
        "schema": "B.candidate_feature_audit_table.v1", "formal_model_features": False,
        "columns": list(FEATURE_COLUMNS), "missing_representation": "EMPTY_CELL_NOT_ZERO",
        "notes": ["身份/时间/输出风险列仅供审计，不能整表作为模型 X。",
                  "本表不定义标签、正式顺序/shape、split 或 Training Contract。"]})
    manifest = {"schema": "B.local_artifact_manifest.v1", "scope": config["mode"],
                "formal_training_ready": False, "files": {}}
    for path in sorted(output_dir.iterdir()):
        manifest["files"][path.name] = {"bytes": path.stat().st_size, "sha256": sha256(path)}
    dump(output_dir / "manifest.json", manifest)
    verify_manifest(output_dir)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description="离线回放已校验 v2 + 原始批次；不修改源文件/覆盖输出")
    parser.add_argument("--input", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verify", type=Path, help="只验证已有产物哈希清单")
    args = parser.parse_args(argv)
    try:
        if args.verify:
            if any((args.input, args.config, args.output)):
                parser.error("--verify 不与回放参数混用")
            manifest = verify_manifest(args.verify)
            print(json.dumps({"status": "ARTIFACT_HASHES_VERIFIED_ONLY", "scope": manifest["scope"]}))
            return 0
        if not all((args.input, args.config, args.output)):
            parser.error("回放需 --input --config --output")
        summary = export_replay(args.input, args.config, args.output)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 2 if summary["rejected_count"] else 0
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
