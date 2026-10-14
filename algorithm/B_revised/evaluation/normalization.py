"""显式列顺序、真实 Train-only 的标准化工具；不决定正式特征契约。"""
from __future__ import annotations

import hashlib
import json
import math
import statistics

from evaluation.split_preflight import audit_split_plan

FORBIDDEN = {"run_id", "parent_run", "device_id", "node_id", "site_id", "boot_id", "seq", "sequence",
             "source", "is_synthetic", "label", "label_source", "split", "rain_level",
             "timestamp", "timestamp_ms", "uptime_ms", "time_to_event", "future_event",
             "sensor_score", "risk_level", "risk_label", "reason_mask"}


def _features(names):
    if not isinstance(names, list) or not names or any(not isinstance(n, str) or not n for n in names):
        raise ValueError("必须显式传入 ordered_features")
    if len(set(names)) != len(names):
        raise ValueError("特征名重复")
    if any(n.lower() in FORBIDDEN or n.lower().startswith(
            ("label_", "future_", "time_to_", "timestamp", "uptime", "risk_")) for n in names):
        raise ValueError("来源、身份、标签、未来信息不能进入模型 X")


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _row(row, names):
    if set(row["values"]) != set(names) or set(row["valid"]) != set(names):
        raise ValueError("数值和有效性映射必须与显式特征列表一致")
    for name in names:
        if type(row["valid"][name]) is not bool:
            raise ValueError("mask 必须是 bool")
        if row["valid"][name] and not _number(row["values"][name]):
            raise ValueError("有效特征必须是有限数值，null 不能补零")
        if not row["valid"][name] and row["values"][name] is not None:
            raise ValueError("无效派生特征必须为 null；原始值另行保留")


def fit_real_train(records: list[dict], *, ordered_features: list[str]) -> dict:
    _features(ordered_features)
    if not isinstance(records, list) or not records:
        raise ValueError("没有记录，不能拟合")
    groups = {}
    for row in records:
        _row(row, ordered_features)
        item = {k: row[k] for k in ("run_id", "parent_run", "split", "is_synthetic")}
        if item["run_id"] in groups and groups[item["run_id"]] != item:
            raise ValueError("同一 run 的 split/source/parent 冲突")
        groups[item["run_id"]] = item
    plan = audit_split_plan(list(groups.values()))
    if plan["issues"]:
        raise ValueError("来源划分不通过: " + json.dumps(plan["issues"], ensure_ascii=False))
    train = [r for r in records if r["split"] == "train" and not r["is_synthetic"]]
    if not train:
        raise ValueError("没有真实 Train，不能用 Validation/Test/Synthetic 代拟合")
    stats = {}
    for name in ordered_features:
        observed = [float(r["values"][name]) for r in train if r["valid"][name]]
        if not observed:
            raise ValueError(f"{name}: Train 中无有效值，不能伪造统计量")
        mean, std = statistics.fmean(observed), statistics.pstdev(observed)
        if not _number(mean) or not _number(std):
            raise ValueError("统计量非有限数值")
        stats[name] = {"mean": mean, "std": std, "scale": std if std > 0 else 1.0,
                       "constant": std == 0, "valid_count": len(observed)}
    result = {"schema": "B.standard_scaler.v1", "ordered_features": list(ordered_features),
              "fit_scope": "REAL_TRAIN_ONLY", "formal_training_ready": False,
              "fit_runs": sorted({r["run_id"] for r in train}), "statistics": stats}
    result["sha256"] = hashlib.sha256(json.dumps(result, sort_keys=True, allow_nan=False,
                                                separators=(",", ":")).encode()).hexdigest()
    return result


def transform(record: dict, scaler: dict) -> dict:
    body = {k: v for k, v in scaler.items() if k != "sha256"}
    digest = hashlib.sha256(json.dumps(body, sort_keys=True, allow_nan=False,
                                      separators=(",", ":")).encode()).hexdigest()
    if scaler.get("schema") != "B.standard_scaler.v1" or scaler.get("sha256") != digest:
        raise ValueError("Scaler 类型或 SHA-256 不匹配")
    names = scaler["ordered_features"]
    _features(names)
    _row(record, names)
    values = []
    for name in names:
        stat = scaler["statistics"][name]
        if not _number(stat["scale"]) or stat["scale"] <= 0 or not _number(stat["mean"]):
            raise ValueError("Scaler 统计量非法")
        value = ((record["values"][name] - stat["mean"]) / stat["scale"]
                 if record["valid"][name] else None)
        if value is not None and not _number(value):
            raise ValueError("变换结果非有限数值")
        values.append(value)
    return {"ordered_features": list(names), "values": values,
            "valid": [record["valid"][n] for n in names], "scaler_sha256": digest}
