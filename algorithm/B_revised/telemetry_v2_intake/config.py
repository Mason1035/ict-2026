"""Feature/Risk 配置的完整性门禁；哈希不等于实测或人工会签。"""
from __future__ import annotations

import copy
import hashlib
import json
import math

from candidate_features.risk_math import WEIGHTS

REASONS = ("TILT_CONTRIBUTION", "VIBRATION_CONTRIBUTION", "MOISTURE_CONTRIBUTION",
           "GROWTH_CONTRIBUTION", "DUAL_IMU_CONSENSUS")


def config_hash(config: dict) -> str:
    body = {key: value for key, value in config.items() if key != "config_hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode("utf-8")).hexdigest()


def finite(value, name, *, minimum=None):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f"{name}: 需要有限数值，不能是 null/bool")
    if minimum is not None and value < minimum:
        raise ValueError(f"{name}: 数值过小")
    return value


def integer(value, name, *, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name}: 需要 >= {minimum} 的整数")
    return value


def text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name}: 需要非空版本/标识")


def validate_config(config: dict) -> dict:
    try:
        return _validate_config(config)
    except (KeyError, TypeError, AttributeError, OverflowError) as exc:
        raise ValueError(f"配置结构不完整或类型错误: {exc}") from exc


def _validate_config(config: dict) -> dict:
    """加载前一次性校验并深复制，失败不更新已有引擎。"""
    c = copy.deepcopy(config)
    if c.get("schema") != "B.feature_risk.config.v1":
        raise ValueError("配置 schema 不匹配")
    if c.get("mode") not in ("TEST_ONLY", "CALIBRATED"):
        raise ValueError("DRAFT/未标定配置不可加载")
    for key in ("config_version", "feature_version", "calibration_version", "frame_id"):
        text(c.get(key), key)
    for key in ("site_id", "device_id"):
        text(c["device_identity"][key], f"device_identity.{key}")
    for group, positions in (("imu", ("top", "toe")), ("soil", ("top", "middle", "toe"))):
        if set(c["sensor_ids"][group]) != set(positions):
            raise ValueError("传感器标识与实验路数不一致")
        for p in positions:
            text(c["sensor_ids"][group][p], f"sensor_ids.{group}.{p}")
    ids = [v for group in c["sensor_ids"].values() for v in group.values()]
    if len(ids) != len(set(ids)):
        raise ValueError("传感器物理标识重复")
    if c.get("weights") != WEIGHTS or any(type(v) not in (int, float)
                                          for v in c["weights"].values()):
        raise ValueError("共享契约权重不可修改")
    expected = c.get("mode") == "CALIBRATED"
    if type(c.get("validated_for_runtime")) is not bool or c["validated_for_runtime"] != expected:
        raise ValueError("mode 与 validated_for_runtime 不一致")
    if expected:
        for owner in ("A", "B", "C"):
            text(c.get("review_refs", {}).get(owner), f"review_refs.{owner}")
        text(c.get("reason_mask_version"), "reason_mask_version")
        bits = c.get("reason_bits")
        if not isinstance(bits, dict) or set(bits) != set(REASONS):
            raise ValueError("缺少会签后的 reason bit 表")
        for key, bit in bits.items():
            integer(bit, key)
            if bit > 31:
                raise ValueError("reason bit 超过 32 位")
        if len(set(bits.values())) != len(bits):
            raise ValueError("reason bit 重复")
    elif c.get("reason_bits") is not None or c.get("reason_mask_version") is not None:
        raise ValueError("TEST_ONLY 不分配正式 reason bit")
    if c.get("missing_policy") != "REQUIRE_BOTH_IMU_AND_ALL_THREE_SOIL_V1":
        raise ValueError("当前仅实现保守全路有效策略；不支持自动重加权")
    for channel in ("imu", "soil"):
        finite(c["odr_hz"][channel], f"odr_hz.{channel}", minimum=0.001)
    imu = c["imu"]
    if imu.get("filter") != "CAUSAL_GRAVITY_LOWPASS_V1":
        raise ValueError("仅实现显式参数的候选重力低通方法")
    finite(imu["gravity_tau_ms"], "gravity_tau_ms", minimum=0.001)
    integer(imu["warmup_ms"], "warmup_ms", minimum=1)
    integer(imu["alignment_ms"], "imu.alignment_ms")
    for position in ("top", "toe"):
        vector = imu["baseline_gravity_mps2"][position]
        if not isinstance(vector, list) or len(vector) != 3:
            raise ValueError("每路 IMU 必须提供三轴静止重力基线")
        for value in vector:
            finite(value, "baseline")
        norm2 = sum(value * value for value in vector)
        if not math.isfinite(norm2) or norm2 <= 0:
            raise ValueError("基线不能是零向量")
    integer(c["soil"]["alignment_ms"], "soil.alignment_ms")
    for position in ("top", "middle", "toe"):
        probe = c["soil"]["calibration"][position]
        dry = finite(probe["dry_raw"], "dry_raw")
        wet = finite(probe["wet_raw"], "wet_raw")
        span = finite(probe["min_span_raw"], "min_span_raw", minimum=0.001)
        if not math.isfinite(wet - dry) or abs(wet - dry) < span:
            raise ValueError(f"{position}: 干湿差不足，不能标定")
    for name in ("tilt", "vibration", "soil_growth"):
        window = c["windows"][name]
        for key in ("lookback_ms", "max_gap_ms"):
            integer(window[key], f"{name}.{key}", minimum=1)
        integer(window["max_age_ms"], f"{name}.max_age_ms")
        integer(window["min_samples"], f"{name}.min_samples", minimum=2)
        integer(window["min_span_ms"], f"{name}.min_span_ms", minimum=1)
        if window["min_span_ms"] > window["lookback_ms"]:
            raise ValueError("窗口最小覆盖时长大于窗口长度")
    if set(c["curves"]) != set(WEIGHTS):
        raise ValueError("必须恰好有四路贡献曲线")
    for name, points in c["curves"].items():
        if not isinstance(points, list) or len(points) < 2:
            raise ValueError(f"{name}: 至少两个贡献曲线点")
        previous = None
        for pair in points:
            if not isinstance(pair, list) or len(pair) != 2:
                raise ValueError("曲线点必须是 [物理值, 贡献值]")
            x = finite(pair[0], "curve.x")
            y = finite(pair[1], "curve.y", minimum=0)
            if y > 100 or (previous and (x <= previous[0] or y < previous[1]
                                         or not math.isfinite(x - previous[0]))):
                raise ValueError("曲线 x 严格递增，贡献值在 0..100 且不下降")
            previous = (x, y)
    finite(c["consensus"]["tilt_threshold_deg"], "consensus threshold", minimum=0)
    finite(c["consensus"]["max_tilt_difference_deg"], "consensus difference", minimum=0)
    if type(c["consensus"]["bonus"]) not in (int, float) or c["consensus"]["bonus"] not in (0, 5):
        raise ValueError("当前共识奖励仅支持关闭或共享契约初值 5")
    if c.get("config_hash") != config_hash(c):
        raise ValueError("配置 SHA-256 不一致")
    return c


def contribution(value, points):
    """经批准的单调折线映射；端点外饱和，绝不对缺测填零。"""
    if value is None:
        return None
    finite(value, "feature")
    if value <= points[0][0]:
        return float(points[0][1])
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if value <= x1:
            return y0 + (y1 - y0) * (value - x0) / (x1 - x0)
    return float(points[-1][1])
