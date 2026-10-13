"""软件评价口径工具；labels、事件窗与匹配策略需调用方显式给出。"""
from __future__ import annotations

import math
from itertools import groupby


def _ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def classification_report(y_true, y_pred, *, labels):
    """unknown 真值排除并计数；未知预测保留为 UNSCORED，不能通过排除提升 recall。"""
    if len(y_true) != len(y_pred) or not labels or len(set(labels)) != len(labels):
        raise ValueError("样本数或显式 labels 不合法")
    if any(not isinstance(label, str) or not label or label == "UNSCORED" for label in labels):
        raise ValueError("labels 需要互异的非空字符串")
    matrix = [[0] * (len(labels) + 1) for _ in labels]
    excluded = scored = correct = 0
    for truth, prediction in zip(y_true, y_pred):
        if truth is None:
            excluded += 1
            continue
        if truth not in labels or (prediction is not None and prediction not in labels):
            raise ValueError("未知类别不能自动改成 normal")
        i = labels.index(truth)
        j = labels.index(prediction) if prediction is not None else len(labels)
        matrix[i][j] += 1
        scored += prediction is not None
        correct += prediction == truth
    per_class = {}
    for i, label in enumerate(labels):
        tp = matrix[i][i]
        support = sum(matrix[i])
        fp = sum(row[i] for row in matrix) - tp
        fn = support - tp  # 包含真实有标签但无法评分的样本
        precision, recall = _ratio(tp, tp + fp), _ratio(tp, tp + fn)
        f1 = _ratio(2 * tp, 2 * tp + fp + fn)
        per_class[label] = {"tp": tp, "fp": fp, "fn": fn, "support": support,
                            "precision": precision, "recall": recall, "f1": f1}
    known = sum(map(sum, matrix))
    return {"schema": "B.classification_metrics.v1", "formal_validation": False,
            "labels": list(labels), "prediction_columns": [*labels, "UNSCORED"],
            "confusion_matrix": matrix, "per_class": per_class,
            "excluded_unknown_truth": excluded, "known_truth_count": known,
            "scored_count": scored, "coverage": _ratio(scored, known),
            "accuracy_including_unscored": _ratio(correct, known),
            "accuracy_on_scored_only": _ratio(correct, scored),
            "macro_f1": (sum(v["f1"] for v in per_class.values() if v["f1"] is not None) /
                         sum(v["f1"] is not None for v in per_class.values()))
                         if any(v["f1"] is not None for v in per_class.values()) else None,
            "macro_f1_labels": [k for k, v in per_class.items() if v["f1"] is not None]}


def precision_recall_curve(y_true, scores):
    """二元标签 0/1，显式风险分数；null 分数计入正类漏评，不造 ROC/PR 泛化结论。"""
    if len(y_true) != len(scores):
        raise ValueError("样本数不一致")
    positives = sum(value == 1 for value in y_true if value is not None)
    pairs, excluded, unscored = [], 0, 0
    for truth, score in zip(y_true, scores):
        if truth is None:
            excluded += 1
            continue
        if type(truth) is not int or truth not in (0, 1):
            raise ValueError("PR 真值必须为 0/1/null")
        if score is None:
            unscored += 1
        elif type(score) not in (int, float) or not math.isfinite(score):
            raise ValueError("分数必须为有限数值或 null")
        else:
            pairs.append((float(score), truth))
    pairs.sort(reverse=True)
    tp = fp = 0
    points = []
    previous_recall, ap = 0.0, 0.0
    for threshold, grouped in groupby(pairs, key=lambda pair: pair[0]):
        tied = [truth for _, truth in grouped]
        tp += sum(tied)
        fp += len(tied) - sum(tied)
        precision, recall = _ratio(tp, tp + fp), _ratio(tp, positives)
        points.append({"threshold": threshold, "precision": precision, "recall": recall})
        if recall is not None:
            ap += (recall - previous_recall) * precision
            previous_recall = recall
    return {"schema": "B.binary_pr.v1", "formal_validation": False, "points": points,
            "average_precision_including_unscored_positives": ap if positives else None,
            "excluded_unknown_truth": excluded, "unscored": unscored,
            "positive_count": positives}


def event_report(events, alarms, *, observation_intervals, early_window_ms, late_window_ms):
    """run/boot 内按事件时间顺序一对一匹配最早未用警报；正提前量=事件前发现。

    观察区间为半开区间。警报输入必须是一次触发事件，不是每帧高分。
    事件、警报和匹配窗不得跨未观察区间；不使用风险规则自行生成真值。
    """
    for value in (early_window_ms, late_window_ms):
        if type(value) is not int or value < 0:
            raise ValueError("事件窗需要显式非负整数毫秒")
    intervals = {}
    for row in observation_intervals:
        if not isinstance(row["run_id"], str) or not row["run_id"] or type(row["boot_id"]) is not int or row["boot_id"] < 0:
            raise ValueError("观察区间必须标识 run 和非负整数 boot")
        key = (row["run_id"], row["boot_id"])
        start, end = row["start_ms"], row["end_ms"]
        if type(start) is not int or type(end) is not int or not 0 <= start < end:
            raise ValueError("观察区间非法")
        intervals.setdefault(key, []).append((start, end))
    for key, values in intervals.items():
        values.sort()
        if any(b[0] < a[1] for a, b in zip(values, values[1:])):
            raise ValueError("观察区间重叠，不能重复计算观察小时")
        merged = []
        for start, end in values:
            if merged and merged[-1][1] == start:
                merged[-1] = (merged[-1][0], end)
            else:
                merged.append((start, end))
        intervals[key] = merged
    def location(row):
        key = (row["run_id"], row["boot_id"])
        t = row["time_ms"]
        if not isinstance(key[0], str) or not key[0] or type(key[1]) is not int or key[1] < 0:
            raise ValueError("事件/警报必须标识 run 和非负整数 boot")
        if type(t) is not int or t < 0:
            raise ValueError("事件/警报时间必须是非负整数毫秒")
        for start, end in intervals.get(key, []):
            if start <= t < end:
                return key, start, end
        raise ValueError("事件或警报位于未观察区间")
    for collection in (events, alarms):
        ids = [r["id"] for r in collection]
        if any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
            raise ValueError("事件/警报 id 缺失或重复")
        for row in collection:
            location(row)
    remaining = set(range(len(alarms)))
    matches = []
    for event in sorted(events, key=lambda r: (str(r["run_id"]), str(r["boot_id"]), r["time_ms"], r["id"])):
        segment = location(event)
        eligible = [i for i in remaining if location(alarms[i]) == segment and
                    event["time_ms"] - early_window_ms <= alarms[i]["time_ms"] <= event["time_ms"] + late_window_ms]
        if eligible:
            i = min(eligible, key=lambda j: (alarms[j]["time_ms"], alarms[j]["id"]))
            remaining.remove(i)
            matches.append({"event_id": event["id"], "alarm_id": alarms[i]["id"],
                            "lead_time_ms": event["time_ms"] - alarms[i]["time_ms"]})
    hours = sum(end - start for values in intervals.values() for start, end in values) / 3_600_000
    return {"schema": "B.event_metrics.v1", "formal_validation": False,
            "matching_policy": "CHRONOLOGICAL_EVENT_EARLIEST_UNUSED_ALARM_SAME_OBSERVED_SEGMENT",
            "event_count": len(events), "matched_event_count": len(matches),
            "event_recall": _ratio(len(matches), len(events)), "matches": matches,
            "false_alarm_ids": [alarms[i]["id"] for i in sorted(remaining)],
            "observation_hours": hours, "false_alarms_per_hour": _ratio(len(remaining), hours),
            "early_window_ms": early_window_ms, "late_window_ms": late_window_ms}
