"""共享契约已固定的评分外壳；贡献映射和异常判定仍待标定。"""

from __future__ import annotations

import math


WEIGHTS = {"tilt": 0.30, "vibration": 0.25, "moisture": 0.25, "growth": 0.20}


def sensor_score(contributions: dict[str, float | None], consensus_bonus: float | None) -> float | None:
    """输入是已验证的 0..100 贡献值；缺失即返回 None，不作重归一。"""
    if set(contributions) != set(WEIGHTS) or consensus_bonus is None:
        return None
    if type(consensus_bonus) not in (int, float) or not math.isfinite(consensus_bonus) or consensus_bonus not in (0, 5):
        return None
    for value in contributions.values():
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 100:
            return None
    total = sum(WEIGHTS[name] * contributions[name] for name in WEIGHTS) + consensus_bonus
    return max(0.0, min(100.0, total))


def risk_level(score: float | None) -> str | None:
    """0–<30 NORMAL；30–<60 WATCH；60–<80 WARNING；80–100 EMERGENCY。"""
    if type(score) not in (int, float) or not math.isfinite(score) or not 0 <= score <= 100:
        return None
    if score < 30:
        return "NORMAL"
    if score < 60:
        return "WATCH"
    if score < 80:
        return "WARNING"
    return "EMERGENCY"
