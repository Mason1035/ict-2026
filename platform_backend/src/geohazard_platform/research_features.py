"""Causal CPU features over WP2 DTOs. No raw-file or production-store access."""

from __future__ import annotations

from bisect import bisect_right
from collections import deque
import math
import statistics

from .research_sessions import ANALYSIS_FORMAT_VERSION, AnalysisSession
from .sd_replay import SENSORS


def validate_session(session: AnalysisSession) -> None:
    m = session.metadata
    if (m.get("analysis_format_version") != ANALYSIS_FORMAT_VERSION
            or m.get("transport") != "sd_replay" or m.get("source") != "REAL"
            or m.get("scope") != "TEST_ONLY" or m.get("risk_eligible") is not False
            or m.get("fusion_eligible") is not False
            or not m.get("generated_replay_identity") or not m.get("replay_id")
            or m.get("integrity", {}).get("passed") is not True):
        raise ValueError("requires a registered, integrity-checked WP2 research session")
    if sorted(s.sensor_id for s in session.channels) != sorted(SENSORS.values()):
        raise ValueError("requires exactly five independent WP2 channels")
    for s in session.channels:
        if SENSORS.get((s.kind, s.channel)) != s.sensor_id:
            raise ValueError("channel identity mismatch")


class TimeIntegral:
    """Left-held values integrated over actual elapsed time, never future samples.

    A sample at t changes the value only from t onward. All windows are half-open
    [start, stop); the current sample cannot retroactively fill the last interval.
    Instances belong to one contiguous channel segment, reset at every bad row/gap.
    """

    def __init__(self):
        self.times = []
        self.values = []
        self.areas = []

    def append(self, time_us, value):
        if self.times and time_us <= self.times[-1]:
            raise ValueError("integral times must increase")
        area = (self.areas[-1] + self.values[-1] * (time_us - self.times[-1])
                if self.times else 0.0)
        self.times.append(time_us)
        self.values.append(value)
        self.areas.append(area)

    def _area(self, time_us):
        index = bisect_right(self.times, time_us) - 1
        return self.areas[index] + self.values[index] * (time_us - self.times[index])

    def mean(self, start_us, stop_us, *, expected_interval_us, minimum_coverage):
        if (not self.times or start_us < self.times[0] or stop_us > self.times[-1]
                or start_us >= stop_us):
            return None
        count = bisect_right(self.times, stop_us) - bisect_right(self.times, start_us)
        if count * expected_interval_us / (stop_us - start_us) < minimum_coverage:
            return None
        return max(0.0, (self._area(stop_us) - self._area(start_us)) / (stop_us - start_us))


def _angle(vector, reference):
    a = math.sqrt(sum(v * v for v in vector))
    b = math.sqrt(sum(v * v for v in reference))
    if a <= 1e-12 or b <= 1e-12:
        return None
    # atan2 is stable for the very small static angles in R4.
    cross = (vector[1] * reference[2] - vector[2] * reference[1],
             vector[2] * reference[0] - vector[0] * reference[2],
             vector[0] * reference[1] - vector[1] * reference[0])
    return math.degrees(math.atan2(math.sqrt(sum(v * v for v in cross)),
                                   sum(v * r for v, r in zip(vector, reference))))


def channel_features(series, parameters):
    """Evaluate only at new observations; initial baselines never use future rows.

    Failed initial reference collection stays unavailable for this session. After
    an established reference, a gap resets all dynamic windows but keeps that
    reference, so later changes cannot silently redefine the starting direction.
    """
    p = parameters
    imu = series.kind == "imu"
    maximum_gap = p["imu_max_gap_us"] if imu else p["soil_max_gap_us"]
    baseline_start = None
    baseline_values = []
    baseline = None
    baseline_failed = False
    previous_time = None
    high_water = None
    gravity = None
    energy = TimeIntegral()
    gyro = TimeIntegral()
    soil_filter = deque(maxlen=p["ain2_median_samples"] if series.sensor_id == "soil_toe" else 1)
    previous_raw = None
    previous_filtered = None
    previous_angle = None
    last_evaluation = None
    points = []
    for sample in series.observations:
        t = sample.relative_time_us
        flags = list(sample.quality_flags)
        if t is None or t < 0:
            flags.append("INVALID_TIME")
        elif high_water is not None and t <= high_water:
            flags.append("NON_MONOTONIC_TIME")
        if t is not None:
            high_water = max(high_water if high_water is not None else t, t)
        if previous_time is not None and t is not None and t - previous_time > maximum_gap:
            flags.append("LONG_GAP")
        payload = (sample.raw.acceleration_mps2 + sample.raw.angular_velocity_dps
                   if imu else (sample.raw.soil_raw,))
        if any(v is None or not math.isfinite(v) for v in payload):
            flags.append("INVALID_VALUE")
        if imu and all(v is not None for v in sample.raw.acceleration_mps2):
            if sum(v * v for v in sample.raw.acceleration_mps2) <= 1e-24:
                flags.append("ZERO_ACCELERATION_VECTOR")
        point = {"time_us": t, "source_line": sample.raw.source_line,
                 "acquisition_index": sample.raw.acquisition_index,
                 "quality_flags": sorted(set(flags)), "state": "WARMUP", "values": {}}
        if flags:
            if baseline is None:
                baseline_failed = True
            previous_time = None
            gravity = None
            energy, gyro = TimeIntegral(), TimeIntegral()
            soil_filter.clear()
            previous_raw = previous_filtered = previous_angle = last_evaluation = None
            point["state"] = "INVALID"
            points.append(point)
            continue
        dt = (t - previous_time) / 1e6 if previous_time is not None else None
        if baseline_start is None:
            baseline_start = t
        if imu:
            a = sample.raw.acceleration_mps2
            if gravity is None:
                gravity = a
            else:
                alpha = math.exp(-dt / p["gravity_tau_s"])
                gravity = tuple(alpha * g + (1 - alpha) * v for g, v in zip(gravity, a))
            energy.append(t, sum((v - g) ** 2 for v, g in zip(a, gravity)))
            gyro.append(t, sum(v * v for v in sample.raw.angular_velocity_dps))
            base_value = a
        else:
            raw = sample.raw.soil_raw
            soil_filter.append(raw)
            filtered = statistics.median(soil_filter) if len(soil_filter) == soil_filter.maxlen else None
            adjacent = abs(raw - previous_raw) if previous_raw is not None else None
            point["values"] = {"raw_adc_code": raw, "filtered_adc_code": filtered,
                               "adjacent_delta_adc_code": adjacent}
            if (series.sensor_id == "soil_toe" and adjacent is not None
                    and adjacent > p["ain2_adjacent_guard_adc"]):
                point["quality_flags"].append("AIN2_ADJACENT_JITTER_GUARD")
            previous_raw = raw
            base_value = filtered
        if baseline is None and not baseline_failed:
            if t - baseline_start < p["baseline_window_us"]:
                if base_value is not None:
                    baseline_values.append(base_value)
            elif baseline_values:
                baseline = (tuple(statistics.median(v[i] for v in baseline_values) for i in range(3))
                            if imu else statistics.median(baseline_values))
                baseline_values.clear()
        previous_time = t
        if imu and last_evaluation is not None and t - last_evaluation < p["evaluation_step_us"]:
            continue
        last_evaluation = t
        if baseline is None:
            point["state"] = "INSUFFICIENT_BASELINE" if baseline_failed else "WARMUP"
            points.append(point)
            continue
        if imu:
            angle = _angle(gravity, baseline)
            kwargs = {"expected_interval_us": p["imu_expected_interval_us"],
                      "minimum_coverage": p["minimum_coverage"]}
            sta = energy.mean(t - p["sta_window_us"], t, **kwargs)
            lta = energy.mean(t - p["sta_window_us"] - p["lta_window_us"],
                              t - p["sta_window_us"], **kwargs)
            rms_energy = energy.mean(t - p["rms_window_us"], t, **kwargs)
            gyro_energy = gyro.mean(t - p["rms_window_us"], t, **kwargs)
            rate = ((angle - previous_angle[1]) / ((t - previous_angle[0]) / 1e6)
                    if angle is not None and previous_angle is not None else None)
            previous_angle = (t, angle) if angle is not None else None
            point["values"] = {
                "direction_angle_deg": angle, "tilt_rate_deg_s": rate,
                "vibration_rms_mps2": math.sqrt(rms_energy) if rms_energy is not None else None,
                "sta_energy": sta, "lta_energy": lta,
                "sta_lta": (sta / max(lta, p["noise_floor_energy"][series.sensor_id])
                            if sta is not None and lta is not None else None),
                "gyro_rms_dps": math.sqrt(gyro_energy) if gyro_energy is not None else None,
            }
            point["state"] = ("READY" if angle is not None and rate is not None
                              and lta is not None and rms_energy is not None else "WARMUP")
        else:
            point["values"]["baseline_adc_code"] = baseline
            if baseline == 0:
                point["quality_flags"].append("ZERO_ADC_BASELINE")
                point["state"] = "INSUFFICIENT_BASELINE"
            elif filtered is not None:
                point["values"].update(
                    relative_change_fraction=(filtered - baseline) / abs(baseline),
                    adc_rate_code_s=((filtered - previous_filtered[1]) / ((t - previous_filtered[0]) / 1e6)
                                     if previous_filtered is not None else None),
                )
                point["state"] = "READY"
            previous_filtered = (t, filtered) if filtered is not None else None
        points.append(point)
    return points


def compute_features(session: AnalysisSession, parameters: dict) -> dict:
    validate_session(session)
    return {s.sensor_id: channel_features(s, parameters) for s in session.channels}
