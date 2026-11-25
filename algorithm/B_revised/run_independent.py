"""PyCharm 可直接运行的 B 独立工作入口；全部输出另存，不覆盖历史。"""
from __future__ import annotations

import sys

if sys.version_info < (3, 11):
    print("需要 Python 3.11+；当前是 " + sys.version.split()[0])
    print("请在 PyCharm 选择本项目 .venv/Scripts/python.exe，或其他 Python 3.11+。")
    raise SystemExit(2)

import argparse
import json
import os
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

B_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(B_ROOT))

from data_intake.check_handoff import inspect_handoff
from evaluation.metrics import classification_report, event_report, precision_recall_curve
from evaluation.normalization import fit_real_train, transform
from local_tools.common import dump, sha256, verify_manifest
from local_tools.scenarios import check_scenario, scenarios
from telemetry_v2_intake.demo_runtime import test_only_config
from telemetry_v2_intake.replay import export_replay


def evaluate_tool_examples():
    # 以下逻辑 REAL/Train 标签是软件夹具，整份文件的 scope 明确为 TEST_ONLY。
    rows = [{"run_id": "TEST_ONLY-TRAIN", "parent_run": None, "split": "train", "is_synthetic": False,
             "values": {"test_feature": x}, "valid": {"test_feature": x is not None}}
            for x in (0, 2, None)]
    rows.append({"run_id": "TEST_ONLY-TEST", "parent_run": None, "split": "test", "is_synthetic": False,
                 "values": {"test_feature": 900}, "valid": {"test_feature": True}})
    scaler = fit_real_train(rows, ordered_features=["test_feature"])
    report = classification_report(["N", "S", "S", None], ["N", "S", None, "N"], labels=["N", "S"])
    pr = precision_recall_curve([0, 1, 1], [.1, .9, None])
    ev = event_report([{"id": "TEST-E", "run_id": "TEST-R", "boot_id": 1, "time_ms": 1000}],
                      [{"id": "TEST-A", "run_id": "TEST-R", "boot_id": 1, "time_ms": 900}],
                      observation_intervals=[{"run_id": "TEST-R", "boot_id": 1, "start_ms": 0, "end_ms": 2000}],
                      early_window_ms=200, late_window_ms=0)
    return {"scope": "TEST_ONLY_SOFTWARE_FIXTURES_NOT_REAL_EVALUATION", "formal_training_ready": False,
            "normalizer": scaler, "normalized_examples": [transform(row, scaler) for row in rows],
            "classification": report, "precision_recall": pr, "event_metrics": ev}


def run(output_dir):
    output_dir = Path(output_dir)
    if output_dir.exists():
        raise FileExistsError(f"输出已存在，请选择新目录: {output_dir}")
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
    test = subprocess.run([sys.executable, "-B", "-m", "unittest", "discover", "-s", str(B_ROOT),
                           "-t", str(B_ROOT), "-p", "test_*.py", "-v"],
                          cwd=B_ROOT, env=env, capture_output=True, text=True, encoding="utf-8", timeout=120)
    if test.returncode:
        sys.stderr.write(test.stdout + test.stderr)
        raise RuntimeError("软件测试失败，未创建 PASS 产物")
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / "tests.txt").write_text(test.stdout + test.stderr, encoding="utf-8")
    dump(output_dir / "config.TEST_ONLY.json", test_only_config())
    reports = {}
    for name, records in scenarios().items():
        source = output_dir / (name + ".input.TEST_ONLY.jsonl")
        with source.open("x", encoding="utf-8", newline="\n") as stream:
            for record in records:
                stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
        target = output_dir / name
        export_replay(source, output_dir / "config.TEST_ONLY.json", target)
        outputs = [load_json_line(text) for text in (target / "results.jsonl").read_text(encoding="utf-8").splitlines()]
        reports[name] = check_scenario(name, outputs)
    dump(output_dir / "evaluation.TEST_ONLY.json", evaluate_tool_examples())
    dump(output_dir / "handoff_preflight.json", inspect_handoff(B_ROOT / "data_intake" / "A_RUN_HANDOFF_DRAFT.json"))
    summary = {"schema": "B.independent_work_summary.v1", "status": "INDEPENDENT_SOFTWARE_CHECKS_PASS",
               "scope": "TEST_ONLY", "formal_training_ready": False, "calibrated_runtime_ready": False,
               "python": sys.version, "python_executable": sys.executable, "scenarios": reports,
               "waiting_for": ["A_REAL_RAW_DATA_AND_CALIBRATION", "B_PARAMETERS_FROM_REAL_TRAIN",
                               "TEAM_REVIEW_REASON_MASK_AND_DEVICE_TOLERANCE", "C_MODEL_CONTRACT_AND_EVALUATION"],
               "output": str(output_dir.resolve())}
    dump(output_dir / "summary.json", summary)
    manifest = {"schema": "B.local_artifact_manifest.v1", "scope": "TEST_ONLY",
                "formal_training_ready": False, "files": {}}
    # 子目录的 manifest 也登记在总清单中，便于整包核对。
    for path in sorted(output_dir.rglob("*")):
        if path.is_file():
            manifest["files"][path.relative_to(output_dir).as_posix()] = {
                "bytes": path.stat().st_size, "sha256": sha256(path)}
    dump(output_dir / "manifest.json", manifest)
    verify_manifest(output_dir)
    return summary


def load_json_line(text):
    from local_tools.common import loads
    return loads(text)


def main(argv=None):
    parser = argparse.ArgumentParser(description="B 本地独立工具验证，不等待 A/C 数据")
    default = B_ROOT / "artifacts" / "local_runs" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8])
    parser.add_argument("--output", type=Path, default=default, help="新建输出目录，已有目录不覆盖")
    args = parser.parse_args(argv)
    try:
        result = run(args.output)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, AssertionError, subprocess.TimeoutExpired) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
