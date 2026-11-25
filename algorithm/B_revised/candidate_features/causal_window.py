"""在线/回放共用的因果观测窗口参考；参数由调用方显式给出。

本模块只演示时间、分段、缺测边界，不选择正式窗口长度或危险阈值。
每次 add 仅代表一次*新的*物理观测，不接受转填到高频行的旧值。
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class WindowSlice:
    status: str
    start_uptime_ms: int
    end_uptime_ms: int
    samples: tuple[tuple[int, float], ...]


class CausalObservationBuffer:
    """分段 key 由调用方组合 run/boot/传感器/坐标/ODR/校准版本。"""

    def __init__(self, *, lookback_ms: int, max_gap_ms: int, max_age_ms: int):
        for name, value in (("lookback_ms", lookback_ms), ("max_gap_ms", max_gap_ms)):
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} 必须显式给出正整数；当前数值仅供 TEST_ONLY")
        if type(max_age_ms) is not int or max_age_ms < 0:
            raise ValueError("max_age_ms 必须显式给出非负整数")
        self.lookback_ms = lookback_ms
        self.max_gap_ms = max_gap_ms
        self.max_age_ms = max_age_ms
        self._segment_key: tuple[str, ...] | None = None
        self._last_uptime_ms: int | None = None
        self._observations: deque[tuple[int, float | None]] = deque()

    def add(self, *, segment_key: tuple[str, ...], uptime_ms: int,
            value: float | None, valid: bool) -> str | None:
        if not isinstance(segment_key, tuple) or not segment_key or not all(
            isinstance(part, str) and part for part in segment_key
        ):
            raise ValueError("segment_key 必须是非空字符串元组")
        if type(uptime_ms) is not int or uptime_ms < 0:
            raise ValueError("uptime_ms 必须是非负整数")
        if type(valid) is not bool:
            raise ValueError("valid 必须是布尔值")
        if valid and (value is None or not isinstance(value, (int, float))
                      or not math.isfinite(value)):
            raise ValueError("valid=true 时必须提供有限数值")
        if not valid:
            value = None  # 原始异常值由采集层保留，不流入特征数学。

        reset_reason = None
        if self._segment_key != segment_key:
            reset_reason = "SEGMENT_CHANGED"
        elif self._last_uptime_ms is not None and uptime_ms <= self._last_uptime_ms:
            reset_reason = "NON_MONOTONIC_TIME"
        elif (self._last_uptime_ms is not None
              and uptime_ms - self._last_uptime_ms > self.max_gap_ms):
            reset_reason = "OBSERVATION_GAP"
        if reset_reason:
            self._observations.clear()
        self._segment_key = segment_key
        self._last_uptime_ms = uptime_ms
        self._observations.append((uptime_ms, float(value) if value is not None else None))
        start = uptime_ms - self.lookback_ms
        while self._observations and self._observations[0][0] < start:
            self._observations.popleft()
        return reset_reason

    def window(self, *, end_uptime_ms: int, min_valid_samples: int) -> WindowSlice:
        if type(end_uptime_ms) is not int or end_uptime_ms < 0:
            raise ValueError("end_uptime_ms 必须是非负整数")
        if type(min_valid_samples) is not int or min_valid_samples <= 0:
            raise ValueError("min_valid_samples 必须显式给出正整数")
        if self._last_uptime_ms is not None and end_uptime_ms < self._last_uptime_ms:
            raise ValueError("不能在已接收未来样本的缓存上回算过去窗口")
        start = end_uptime_ms - self.lookback_ms
        valid_values = tuple((t, v) for t, v in self._observations
                             if start <= t <= end_uptime_ms and v is not None)
        if not valid_values:
            status = "INSUFFICIENT_VALID_DATA"
        elif end_uptime_ms - valid_values[-1][0] > self.max_age_ms:
            status = "STALE"
        elif any(right[0] - left[0] > self.max_gap_ms
                 for left, right in zip(valid_values, valid_values[1:])):
            status = "VALID_DATA_GAP"
        elif len(valid_values) < min_valid_samples:
            status = "INSUFFICIENT_VALID_DATA"
        else:
            status = "STRUCTURE_VALID_ONLY"
        return WindowSlice(status, start, end_uptime_ms, valid_values)
