"""候选特征的纯数学参考实现。

本模块不读真实 CSV，不决定窗口/阈值/列顺序，也不把原始 Soil ADC 转成体积含水率。
调用方必须显式提供重力基线、动态加速度或逐探针干湿标定。
"""

from __future__ import annotations

import math
from collections.abc import Sequence


Vector3 = tuple[float, float, float]
TimedValue = tuple[int, float]


def _finite(*values: float) -> bool:
    return all(math.isfinite(float(value)) for value in values)


def gravity_tilt_change_deg(current: Vector3 | None, reference: Vector3 | None) -> float | None:
    """两个重力方向间的夹角，单位度；是相对倾斜线索而非地表位移。"""
    if current is None or reference is None:
        return None
    if len(current) != 3 or len(reference) != 3 or not _finite(*current, *reference):
        return None
    norm_current = math.sqrt(sum(x * x for x in current))
    norm_reference = math.sqrt(sum(x * x for x in reference))
    if norm_current == 0 or norm_reference == 0:
        return None
    cosine = sum(a * b for a, b in zip(current, reference)) / (norm_current * norm_reference)
    return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))


def causal_slope_per_second(samples: Sequence[TimedValue]) -> float | None:
    """按真实毫秒时间做最小二乘斜率；输入必须严格递增且只含当前及历史样本。"""
    if len(samples) < 2:
        return None
    if any(not isinstance(t, int) or not _finite(value) for t, value in samples):
        return None
    if any(right[0] <= left[0] for left, right in zip(samples, samples[1:])):
        return None
    start_ms = samples[0][0]
    times = [(timestamp - start_ms) / 1000.0 for timestamp, _ in samples]
    values = [value for _, value in samples]
    mean_t = sum(times) / len(times)
    mean_v = sum(values) / len(values)
    denominator = sum((time - mean_t) ** 2 for time in times)
    if denominator <= 0:
        return None
    return sum((time - mean_t) * (value - mean_v) for time, value in zip(times, values)) / denominator


def dynamic_accel_rms_mps2(samples: Sequence[Vector3 | None]) -> float | None:
    """对已按有效性与滤波配置得到的动态加速度向量求 RMS；不自行推断滤波参数。"""
    valid = [sample for sample in samples if sample is not None and len(sample) == 3 and _finite(*sample)]
    if not valid:
        return None
    return math.sqrt(sum(sum(axis * axis for axis in sample) for sample in valid) / len(valid))


def relative_wetness_index(raw: float | None, dry_raw: float | None, wet_raw: float | None) -> float | None:
    """每根探针单独标定的相对指标；不截断、不等同于 VWC 百分比。"""
    if raw is None or dry_raw is None or wet_raw is None or not _finite(raw, dry_raw, wet_raw):
        return None
    if wet_raw == dry_raw:
        return None
    return (raw - dry_raw) / (wet_raw - dry_raw)


def valid_probe_mean(values: Sequence[float | None]) -> tuple[float | None, int]:
    """只对有效探针求均值，并明确返回有效探针数；不足要求由上层决定。"""
    valid = [value for value in values if value is not None and _finite(value)]
    return (sum(valid) / len(valid), len(valid)) if valid else (None, 0)


def spatial_probe_spread(values: Sequence[float | None]) -> float | None:
    """至少两根有效且同尺度的探针才计算空间差异。"""
    valid = [value for value in values if value is not None and _finite(value)]
    return max(valid) - min(valid) if len(valid) >= 2 else None


def dual_imu_tilt_difference_deg(top: float | None, toe: float | None) -> float | None:
    """双 IMU 相对角度差；是否一致/异常需要经实验标定的阈值。"""
    if top is None or toe is None or not _finite(top, toe):
        return None
    return abs(top - toe)
