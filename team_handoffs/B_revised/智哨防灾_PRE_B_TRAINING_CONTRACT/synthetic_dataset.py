"""Build a TEST_ONLY, group-split fixture for reproducing B's demo rules.

This script does not fit a model and its labels are not disaster ground truth.
It uses only Python's standard library and the sibling B algorithm delivery.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_ALGORITHM_DIR = ROOT.parent / "队员B_算法开发交付"
OUTPUT_DIR = ROOT / "artifacts" / "pre_b_training_contract"
CONTRACT_PATH = ROOT / "training_contract.json"

# TEST_ONLY rule-distillation columns. Not B's formal project feature contract.
FEATURES = (
    "soil_moisture_delta_pp",
    "soil_moisture_slope_pp_per_min",
    "tilt_median_deviation_deg",
    "tilt_min_abs_deviation_deg",
)
EXPECTED_RISK = {"normal": 0, "attention": 1, "warning": 1}
SPLITS = ("train", "validation", "test")
DEFAULT_SEED = 20260925


def load_rule_evaluator(algorithm_dir: Path):
    algorithm_dir = algorithm_dir.resolve()
    module_path = algorithm_dir / "risk_algorithm.py"
    config_path = algorithm_dir / "demo_rules.json"
    if not module_path.is_file() or not config_path.is_file():
        raise FileNotFoundError(
            "找不到队员 B 的 risk_algorithm.py/demo_rules.json。"
            f"请将其放在 {algorithm_dir}，或运行时传入 --algorithm-dir。"
        )
    sys.path.insert(0, str(algorithm_dir))
    from risk_algorithm import RiskEvaluator  # noqa: PLC0415

    evaluator = RiskEvaluator(config_path)
    if evaluator.algorithm_version != "demo-rules-1.0.0":
        raise ValueError(
            "B 算法版本与 Training Contract 冻结版本不一致："
            f"{evaluator.algorithm_version!r}；请三方先确认并升级契约。"
        )
    digest = hashlib.sha256(module_path.read_bytes() + config_path.read_bytes()).hexdigest()
    return evaluator, digest


def _noise(rng: random.Random, width: float) -> float:
    return rng.uniform(-width, width)


def make_history(group_number: int, scenario: str, seed: int) -> list[dict]:
    """Create one deterministic six-record sample using the frozen generator."""
    rng = random.Random(seed * 1_000_003 + group_number * 97 + {"normal": 11, "attention": 23, "warning": 37}[scenario])
    battery_rng = random.Random((seed ^ 0x5EEDC0DE) + group_number * 193)
    baseline_moisture = rng.uniform(20.0, 55.0)
    baseline_tilt = rng.uniform(-0.8, 0.8)
    baseline_battery = [round(battery_rng.uniform(30.0, 99.0)) for _ in range(6)]
    start = datetime(2026, 9, 23, 12, tzinfo=timezone.utc) + timedelta(minutes=group_number)

    if scenario == "normal":
        moisture = [baseline_moisture + _noise(rng, 0.04) for _ in range(6)]
        tilt = [baseline_tilt + _noise(rng, 0.035) for _ in range(6)]
        # A small, isolated bump is intentionally not sustained.
        if group_number % 10 == 0:
            tilt[-1] = baseline_tilt + rng.choice((-1, 1)) * rng.uniform(1.1, 2.8)
    elif scenario == "attention":
        if group_number % 2 == 0:
            base = baseline_moisture + _noise(rng, 0.02)
            moisture = [base, base + 1.12 + rng.uniform(0.01, 0.04), base + 2.30 + rng.uniform(0.05, 0.10)]
            moisture += [baseline_moisture + _noise(rng, 0.025) for _ in range(3)]
            # Keep baseline reference fixed; overwrite the current 3 with trend.
            moisture[3:] = [base, base + 1.12 + rng.uniform(0.01, 0.04), base + 2.30 + rng.uniform(0.05, 0.10)]
            tilt = [baseline_tilt + _noise(rng, 0.035) for _ in range(6)]
        else:
            moisture = [baseline_moisture + _noise(rng, 0.04) for _ in range(6)]
            sign = rng.choice((-1, 1))
            tilt = [baseline_tilt + _noise(rng, 0.035) for _ in range(3)]
            tilt += [baseline_tilt + sign * amount for amount in (1.08, 1.16, 1.24)]
    elif scenario == "warning":
        if group_number % 2 == 0:
            moisture = [baseline_moisture + _noise(rng, 0.04) for _ in range(6)]
            sign = rng.choice((-1, 1))
            tilt = [baseline_tilt + _noise(rng, 0.035) for _ in range(3)]
            tilt += [baseline_tilt + sign * amount for amount in (3.12, 3.24, 3.36)]
        else:
            base = baseline_moisture + _noise(rng, 0.02)
            moisture = [baseline_moisture + _noise(rng, 0.04) for _ in range(3)]
            moisture += [base, base + 2.62 + rng.uniform(0.01, 0.04), base + 5.28 + rng.uniform(0.05, 0.10)]
            sign = rng.choice((-1, 1))
            tilt = [baseline_tilt + _noise(rng, 0.035) for _ in range(3)]
            tilt += [baseline_tilt + sign * amount for amount in (1.08, 1.16, 1.24)]
    else:
        raise ValueError(f"未知合成场景: {scenario}")

    records = []
    for index in range(6):
        records.append({
            "node_id": f"SYN-{group_number:06d}",
            "timestamp": (start + timedelta(seconds=index * 10)).isoformat().replace("+00:00", "Z"),
            "soil_moisture_pct": round(min(99.0, max(0.0, moisture[index])), 6),
            "tilt_deg": round(tilt[index], 6),
            "battery_pct": baseline_battery[index],
            "sequence": index + 1,
            "source": "simulated",
        })
    return records


def with_missing_measurement(records: list[dict], group_number: int) -> list[dict]:
    copied = [dict(record) for record in records]
    missing_field = "soil_moisture_pct" if group_number % 2 == 0 else "tilt_deg"
    copied[3 + (group_number % 3)][missing_field] = None
    return copied


def derive_features(records: list[dict]) -> dict[str, float]:
    """Compute frozen v1 features from baseline rows 1–3 and current rows 4–6."""
    baseline = records[:3]
    current = records[3:]
    baseline_tilt = sorted(record["tilt_deg"] for record in baseline)[1]
    current_tilt = sorted(record["tilt_deg"] for record in current)[1]
    deviations = [record["tilt_deg"] - baseline_tilt for record in current]
    moisture = [record["soil_moisture_pct"] for record in current]
    # x is elapsed time in minutes; using sample index would violate the contract.
    x = [
        (datetime.fromisoformat(record["timestamp"].replace("Z", "+00:00"))
         - datetime.fromisoformat(current[0]["timestamp"].replace("Z", "+00:00"))).total_seconds() / 60.0
        for record in current
    ]
    x_mean = sum(x) / len(x)
    y_mean = sum(moisture) / len(moisture)
    slope = sum((a - x_mean) * (b - y_mean) for a, b in zip(x, moisture)) / sum((a - x_mean) ** 2 for a in x)
    result = {
        "soil_moisture_delta_pp": moisture[-1] - moisture[0],
        "soil_moisture_slope_pp_per_min": slope,
        "tilt_median_deviation_deg": current_tilt - baseline_tilt,
        "tilt_min_abs_deviation_deg": min(abs(value) for value in deviations),
    }
    if set(result) != set(FEATURES) or not all(math.isfinite(value) for value in result.values()):
        raise ValueError("特征生成违反冻结 schema")
    return {key: round(result[key], 8) for key in FEATURES}


def assign_group_splits(rows: list[dict], seed: int) -> None:
    """Mutate valid rows with deterministic, within-label group split assignments."""
    rng = random.Random(seed)
    for label in (0, 1):
        by_label = [row for row in rows if row["label"] == label]
        if len(by_label) < 20:
            raise ValueError(f"每个标签至少需要 20 个有效独立组，label={label} 只有 {len(by_label)}")
        rng.shuffle(by_label)
        train_end = int(len(by_label) * 0.70)
        validation_count = int(len(by_label) * 0.15)
        validation_end = train_end + validation_count
        for row in by_label[:train_end]:
            row["split"] = "train"
        for row in by_label[train_end:validation_end]:
            row["split"] = "validation"
        for row in by_label[validation_end:]:
            row["split"] = "test"


def _write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)


def build_dataset(groups_per_class: int = 60, seed: int = DEFAULT_SEED,
                  algorithm_dir: Path = DEFAULT_ALGORITHM_DIR,
                  output_dir: Path | None = None,
                  contract_path: Path | None = None) -> dict:
    if type(groups_per_class) is not int or groups_per_class < 20:
        raise ValueError("groups_per_class 必须为不少于 20 的整数")
    if type(seed) is not int or seed < 0:
        raise ValueError("seed 必须为非负整数")
    evaluator, algorithm_sha256 = load_rule_evaluator(algorithm_dir)
    scenarios = ("normal", "attention", "warning")
    valid_rows: list[dict] = []
    excluded_rows: list[dict] = []
    audit_rows: list[dict] = []
    group_number = 1
    missing_per_class = max(2, groups_per_class // 10)

    for scenario in scenarios:
        for _ in range(groups_per_class):
            group_id = f"G-{group_number:06d}"
            records = make_history(group_number, scenario, seed)
            result = evaluator.evaluate(records)
            risk_level = result["risk_level"]
            expected = EXPECTED_RISK[scenario]
            if risk_level != scenario:
                raise RuntimeError(
                    f"合成模板和 B 规则不一致: {group_id} 预期 {scenario}，实际 {risk_level}；"
                    "停止生成，需核对算法版本和阈值。"
                )
            valid_rows.append({
                "group_id": group_id,
                "sample_id": group_id,
                "node_id": records[0]["node_id"],
                "split": "",
                "label": expected,
                "label_text": "rule_triggered" if expected else "rule_not_triggered",
                "teacher_risk_level": risk_level,
                **derive_features(records),
            })
            audit_rows.append({"group_id": group_id, "split": "PENDING", "history": records, "teacher_output": result})
            group_number += 1

        for _ in range(missing_per_class):
            group_id = f"G-{group_number:06d}"
            clean = make_history(group_number, scenario, seed)
            records = with_missing_measurement(clean, group_number)
            result = evaluator.evaluate(records)
            if result["risk_level"] != "unknown":
                raise RuntimeError(f"缺测审计窗预期 unknown 但算法返回 {result['risk_level']}: {group_id}")
            excluded_rows.append({
                "group_id": group_id,
                "sample_id": group_id,
                "node_id": records[0]["node_id"],
                "split": "excluded_unknown",
                "label": "",
                "teacher_risk_level": result["risk_level"],
                "missing_fields": json.dumps(result["missing_fields"], ensure_ascii=False),
                "reasons": json.dumps(result["reasons"], ensure_ascii=False),
            })
            audit_rows.append({"group_id": group_id, "split": "excluded_unknown", "history": records, "teacher_output": result})
            group_number += 1

    assign_group_splits(valid_rows, seed)
    audit_split_by_group = {row["group_id"]: row["split"] for row in valid_rows}
    for row in audit_rows:
        if row["group_id"] in audit_split_by_group:
            row["split"] = audit_split_by_group[row["group_id"]]

    all_groups = [row["group_id"] for row in valid_rows + excluded_rows]
    if len(all_groups) != len(set(all_groups)):
        raise RuntimeError("group_id 重复")
    split_groups = {name: {row["group_id"] for row in valid_rows if row["split"] == name} for name in SPLITS}
    if any(split_groups[a] & split_groups[b] for a in SPLITS for b in SPLITS if a != b):
        raise RuntimeError("分组泄漏：同一 group 出现在多个数据集")

    target_dir = Path(output_dir) if output_dir is not None else OUTPUT_DIR
    contract_file = Path(contract_path) if contract_path is not None else CONTRACT_PATH
    # Exclusive creation protects the handoff's historical artifacts. Callers
    # must choose a fresh directory for each TEST_ONLY export.
    target_dir.mkdir(parents=True, exist_ok=False)
    metadata = ["group_id", "sample_id", "node_id", "split", "label", "label_text", "teacher_risk_level"]
    columns = metadata + list(FEATURES)
    ordered_rows = sorted(valid_rows, key=lambda row: row["group_id"])
    _write_csv(target_dir / "dataset_all.csv", columns, ordered_rows)
    for name in SPLITS:
        training_columns = ["group_id", "sample_id", "split", "label", *FEATURES]
        partition_rows = [
            {column: row[column] for column in training_columns}
            for row in ordered_rows if row["split"] == name
        ]
        _write_csv(target_dir / f"{name}.csv", training_columns, partition_rows)
    excluded_columns = ["group_id", "sample_id", "node_id", "split", "label", "teacher_risk_level", "missing_fields", "reasons"]
    _write_csv(target_dir / "excluded_unknown.csv", excluded_columns, excluded_rows)
    with (target_dir / "synthetic_histories.jsonl").open("w", encoding="utf-8") as stream:
        for row in sorted(audit_rows, key=lambda item: item["group_id"]):
            stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

    counts = {}
    for split in SPLITS:
        partition = [row for row in valid_rows if row["split"] == split]
        counts[split] = {
            "rows": len(partition),
            "groups": len({row["group_id"] for row in partition}),
            "label_0": sum(row["label"] == 0 for row in partition),
            "label_1": sum(row["label"] == 1 for row in partition),
            "risk_level_counts": {level: sum(row["teacher_risk_level"] == level for row in partition) for level in ("normal", "attention", "warning")},
        }
    contract = json.loads(contract_file.read_text(encoding="utf-8"))
    summary = {
        "contract_id": contract["contract_id"],
        "contract_version": contract["contract_version"],
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_rule_version": evaluator.algorithm_version,
        "source_rule_sha256": algorithm_sha256,
        "labels_are_synthetic_proxy_labels_not_ground_truth": True,
        "generator_seed": seed,
        "groups_per_expected_risk_level": groups_per_class,
        "expected_synthetic_rows": len(valid_rows),
        "supervised_rows": len(valid_rows),
        "excluded_unknown_rows": len(excluded_rows),
        "features_in_order": list(FEATURES),
        "forbidden_features": ["label", "teacher_risk_level", "risk_level", "reasons", "group_id", "sample_id", "node_id", "sequence", "timestamp", "source", "battery_pct", "split", "generator_scenario", "random_seed"],
        "split_by_independent_groups": True,
        "split_overlap_detected": False,
        "splits": counts,
        "fitted_model": None,
        "model_metrics": None,
        "model_metrics_note": "模型尚未拟合；禁止将规则教师与自身生成标签的恒等复现分数报告为模型泛化性能。",
    }
    (target_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    metrics = {
        "contract_id": contract["contract_id"],
        "positive_class": contract["metrics"]["positive_class"],
        "binary_threshold": contract["metrics"]["binary_threshold"],
        "definitions": contract["metrics"]["required"],
        "undefined_denominators": contract["metrics"]["undefined_denominators"],
        "model_metrics": None,
        "reason": "此阶段只生成契约数据，不拟合模型或伪报模型分数。",
    }
    (target_dir / "metrics_template.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    readme = f"""智哨防灾 {contract['contract_id']} {contract['contract_version']} TEST_ONLY 合成规则蒸馏输出

本数据全部合成；标签来自队员 B 的 {evaluator.algorithm_version} 规则输出，不是真实灾害标签。
任何分数仅可解释为规则复现效果，不能解释为灾害预测性能。

复现：python synthetic_dataset.py --groups-per-class {groups_per_class} --seed {seed}
规则包 SHA-256：{algorithm_sha256}
有效监督窗口：{len(valid_rows)}；unknown 排除窗口：{len(excluded_rows)}

文件：train.csv、validation.csv、test.csv、dataset_all.csv、excluded_unknown.csv、
synthetic_histories.jsonl、summary.json、metrics_template.json。
模型输入列必须显式取：{', '.join(FEATURES)}
group_id/node_id/sequence/timestamp/source/battery/labels/reasons/split 全是非特征元数据。
"""
    (target_dir / "README.txt").write_text(readme, encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 TEST_ONLY 规则蒸馏 fixture；不可用于正式训练")
    parser.add_argument("--groups-per-class", type=int, default=60)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--algorithm-dir", type=Path, default=DEFAULT_ALGORITHM_DIR)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()
    try:
        summary = build_dataset(args.groups_per_class, args.seed, args.algorithm_dir, args.output_dir)
    except Exception as exc:
        print(f"生成失败：{exc}", file=sys.stderr)
        return 1
    print("TEST_ONLY 规则蒸馏数据生成完成（无模型训练）。")
    print(f"输出目录：{args.output_dir}")
    print(f"有效监督窗：{summary['supervised_rows']}；unknown 排除窗：{summary['excluded_unknown_rows']}")
    for split, info in summary["splits"].items():
        print(f"{split}: {info['rows']} 行，label_0={info['label_0']}，label_1={info['label_1']}")
    print("标签为演示规则合成代理标签，不能解释为灾害预测性能。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
