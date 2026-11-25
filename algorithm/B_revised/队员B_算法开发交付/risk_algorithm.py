"""智哨防灾：可解释的演示规则；未验证用于实际灾害预测。

Only Python's standard library is required. Input records are never mutated.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median

FIELDS = (
    "node_id", "timestamp", "soil_moisture_pct", "tilt_deg",
    "battery_pct", "sequence", "source",
)
MEASUREMENTS = ("soil_moisture_pct", "tilt_deg", "battery_pct")
DEFAULT_CONFIG = Path(__file__).with_name("demo_rules.json")


def _result(level, reasons=None, missing=None):
    return {
        "risk_level": level,
        "reasons": list(reasons or []),
        "missing_fields": list(missing or []),
    }


def _number(value):
    return (
        type(value) in (int, float)
        and abs(value) <= 1e100
        and math.isfinite(value)
    )


def load_config(path=None):
    """Reject invalid configuration explicitly; never fall back silently."""
    with Path(path or DEFAULT_CONFIG).open(encoding="utf-8") as stream:
        config = json.load(stream)
    positive = (
        "baseline_max_tilt_spread_deg", "max_gap_seconds", "min_duration_seconds",
        "moisture_attention_delta_pp", "moisture_attention_rate_pp_per_min",
        "moisture_warning_delta_pp", "moisture_warning_rate_pp_per_min",
        "tilt_attention_deg", "tilt_warning_deg",
    )
    integer_keys = ("baseline_start_sequence", "baseline_samples", "window_samples")
    expected = set(positive + integer_keys + ("algorithm_version", "demo_only", "low_battery_pct"))
    if not isinstance(config, dict) or set(config) != expected:
        raise ValueError("配置键必须与 demo_rules.json 完全一致")
    if config["demo_only"] is not True:
        raise ValueError("本算法只允许演示模式 demo_only=true")
    if not isinstance(config["algorithm_version"], str) or not config["algorithm_version"].strip():
        raise ValueError("algorithm_version 必须为非空字符串")
    for key in integer_keys:
        if type(config[key]) is not int or config[key] < 1:
            raise ValueError(f"{key} 必须为正整数")
    if config["baseline_samples"] < 3 or config["window_samples"] < 3:
        raise ValueError("基线与判断窗口均至少需要 3 个样本")
    for key in positive:
        if not _number(config[key]) or config[key] <= 0:
            raise ValueError(f"{key} 必须为有限正数")
    if not _number(config["low_battery_pct"]) or not 0 <= config["low_battery_pct"] <= 100:
        raise ValueError("low_battery_pct 必须在 0～100 之间")
    for lower, upper in (
        ("moisture_attention_delta_pp", "moisture_warning_delta_pp"),
        ("moisture_attention_rate_pp_per_min", "moisture_warning_rate_pp_per_min"),
        ("tilt_attention_deg", "tilt_warning_deg"),
    ):
        if config[lower] >= config[upper]:
            raise ValueError(f"{upper} 必须大于 {lower}")
    if config["baseline_max_tilt_spread_deg"] >= config["tilt_attention_deg"]:
        raise ValueError("基线允许波动必须小于倾角关注阈值")
    for key in ("baseline_samples", "window_samples"):
        if (config[key] - 1) * config["max_gap_seconds"] < config["min_duration_seconds"]:
            raise ValueError("窗口样本数与允许间隔无法满足最短持续时间")
    return config


def _normalize(record):
    if not isinstance(record, dict) or set(record) != set(FIELDS):
        raise ValueError("每条采样必须恰含约定七字段")
    if not isinstance(record["node_id"], str) or not record["node_id"].strip():
        raise ValueError("node_id 必须为非空字符串")
    if record["source"] not in ("real", "simulated"):
        raise ValueError("source 只能为 real 或 simulated")
    if type(record["sequence"]) is not int or not 1 <= record["sequence"] <= 9007199254740991:
        raise ValueError("sequence 必须为 1～2^53-1 的整数，不能为布尔值")
    stamp = record["timestamp"]
    if not isinstance(stamp, str) or "T" not in stamp or not stamp.endswith(("Z", "+00:00")):
        raise ValueError("timestamp 必须为带 Z 或 +00:00 的 UTC 时间")
    try:
        parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("timestamp 无法解析") from error
    if parsed.utcoffset() != timedelta(0):
        raise ValueError("timestamp 必须为 UTC")
    for key in MEASUREMENTS:
        value = record[key]
        if value is None:
            continue
        if not _number(value):
            raise ValueError(f"{key} 必须为有限数值或 null")
        if key != "tilt_deg" and not 0 <= value <= 100:
            raise ValueError(f"{key} 必须在 0～100 之间或为 null")
    normalized = dict(record)
    normalized["timestamp"] = parsed
    return normalized


def _window_error(records, config, label):
    for previous, current in zip(records, records[1:]):
        if current["sequence"] != previous["sequence"] + 1:
            return f"{label}存在序号缺口，不能确认连续观测"
        seconds = (current["timestamp"] - previous["timestamp"]).total_seconds()
        if not 0 < seconds <= config["max_gap_seconds"]:
            return f"{label}采样时间不连续或间隔超过演示上限"
    duration = (records[-1]["timestamp"] - records[0]["timestamp"]).total_seconds()
    if duration < config["min_duration_seconds"]:
        return f"{label}持续时间不足 {config['min_duration_seconds']:g} 秒"
    return None


def _evaluate(history, config):
    if not isinstance(history, (list, tuple)):
        return _result("unknown", ["history 必须是同节点记录的列表或元组"])
    if not history:
        return _result("unknown", ["没有采样数据"])
    try:
        normalized = [_normalize(record) for record in history]
    except (ValueError, TypeError, OverflowError) as error:
        return _result("unknown", [f"输入无效：{error}"])
    if len({record["node_id"] for record in normalized}) != 1:
        return _result("unknown", ["输入包含多个节点，必须分别调用 evaluate"])
    unique = {}
    for record in normalized:
        sequence = record["sequence"]
        if sequence in unique and unique[sequence] != record:
            return _result("unknown", [f"序号 {sequence} 内容冲突；未覆盖任何记录"])
        unique[sequence] = record
    records = sorted(unique.values(), key=lambda record: record["sequence"])
    if len({record["source"] for record in records}) != 1:
        return _result("unknown", ["同一判断历史混有 real 和 simulated 来源"])
    for previous, current in zip(records, records[1:]):
        if current["timestamp"] <= previous["timestamp"]:
            return _result("unknown", ["采样时间随持久序号未严格递增，需排查设备时钟"])

    start = config["baseline_start_sequence"]
    end = start + config["baseline_samples"]
    baseline = [unique[sequence] for sequence in range(start, end) if sequence in unique]
    recent = records[-config["window_samples"]:]
    assessed = baseline + recent
    missing = [key for key in MEASUREMENTS if any(record[key] is None for record in assessed)]
    battery = records[-1]["battery_pct"]
    device_reasons = []
    if battery is None:
        device_reasons.append("设备状态：最新电量缺测；不直接改变地灾线索等级")
    elif battery <= config["low_battery_pct"]:
        device_reasons.append(f"设备状态：最新电量 {battery:g}%，低于或等于演示阈值；不直接改变地灾线索等级")

    def unknown(reason):
        return _result("unknown", [reason] + device_reasons, missing)

    if len(baseline) != config["baseline_samples"]:
        return unknown(f"基线不完整：需要序号 {start}～{end - 1} 的固定参考段")
    if len(recent) < config["window_samples"] or recent[0]["sequence"] < end:
        return unknown("样本不足：判断窗口必须位于完整基线之后，且不能与基线重叠")
    if "soil_moisture_pct" in missing or "tilt_deg" in missing:
        return unknown("基线或当前窗口存在湿度/倾角缺测；未校准湿度必须为 null，不能按 0 计算")
    for segment, label in ((baseline, "基线"), (recent, "当前窗口")):
        error = _window_error(segment, config, label)
        if error:
            return unknown(error)
    baseline_tilts = [record["tilt_deg"] for record in baseline]
    if max(baseline_tilts) - min(baseline_tilts) > config["baseline_max_tilt_spread_deg"]:
        return unknown("参考段倾角不稳定，不能建立可信的演示基线")

    baseline_tilt = median(baseline_tilts)
    deviations = [record["tilt_deg"] - baseline_tilt for record in recent]
    duration = (recent[-1]["timestamp"] - recent[0]["timestamp"]).total_seconds()
    minutes = [(record["timestamp"] - recent[0]["timestamp"]).total_seconds() / 60 for record in recent]
    moisture = [record["soil_moisture_pct"] for record in recent]
    x_mean = sum(minutes) / len(minutes)
    y_mean = sum(moisture) / len(moisture)
    slope = sum((x - x_mean) * (y - y_mean) for x, y in zip(minutes, moisture)) / sum((x - x_mean) ** 2 for x in minutes)
    delta = moisture[-1] - moisture[0]
    nondecreasing = all(right >= left for left, right in zip(moisture, moisture[1:]))
    moisture_attention = nondecreasing and delta >= config["moisture_attention_delta_pp"] and slope >= config["moisture_attention_rate_pp_per_min"]
    moisture_warning = nondecreasing and delta >= config["moisture_warning_delta_pp"] and slope >= config["moisture_warning_rate_pp_per_min"]

    def sustained_tilt(threshold):
        return all(value >= threshold for value in deviations) or all(value <= -threshold for value in deviations)

    tilt_attention = sustained_tilt(config["tilt_attention_deg"])
    tilt_warning = sustained_tilt(config["tilt_warning_deg"])
    reasons = []
    if moisture_attention:
        reasons.append(f"演示湿度趋势：{duration:g} 秒内净增 {delta:.3f} 个百分点，斜率 {slope:.3f} 个百分点/分钟，逐点不下降")
    if tilt_attention:
        reasons.append(f"演示倾角变化：相对固定基线 {baseline_tilt:.3f}°，连续 {len(recent)} 点同方向偏离至少 {min(abs(value) for value in deviations):.3f}°，持续 {duration:g} 秒；不等同山体位移")
    elif any(abs(value) >= config["tilt_attention_deg"] for value in deviations):
        reasons.append("倾角存在瞬时或变向波动，但未满足演示持续条件；建议复核传感器与安装状态，normal 不代表现场安全")
    if tilt_warning:
        level = "warning"
        reasons.append("触发演示 warning：持续倾角偏离达到较高阈值；不代表灾害预测结论")
    elif tilt_attention and moisture_warning:
        level = "warning"
        reasons.append("触发演示 warning：持续倾角偏离与较强湿度上升同时满足；不代表灾害预测结论")
    elif tilt_attention or moisture_attention:
        level = "attention"
    else:
        level = "normal"
    return _result(level, reasons + device_reasons, missing)


class RiskEvaluator:
    """Load one configuration per instance; create a new instance after changes."""

    def __init__(self, config_path=None):
        self._config = load_config(config_path)

    @property
    def algorithm_version(self):
        return self._config["algorithm_version"]

    def evaluate(self, history):
        return _evaluate(history, self._config)


def evaluate(history):
    """Public entry point: exactly three output fields, no network or writes."""
    return RiskEvaluator().evaluate(history)
