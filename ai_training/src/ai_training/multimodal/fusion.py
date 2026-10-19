"""Causal research evidence summaries, with no calibrated risk classification.

Branch states must come from an explicitly defined upstream method. This module
does not infer states from scores or invent thresholds, and its summaries must
not be used as NORMAL/SLIP labels or as device control decisions.
"""

from dataclasses import dataclass
import math
from numbers import Real
from typing import Any


@dataclass(frozen=True)
class BranchEvidence:
    modality: str
    state: str
    observed_at: float
    run_id: str
    clock_id: str
    valid: bool


def _finite_time(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite number")
    try:
        number = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} must be a finite number")
    return number


def fuse(soil: BranchEvidence | None, motion: BranchEvidence | None, *,
         decision_time: float, run_id: str, clock_id: str,
         max_soil_age: float, max_motion_age: float) -> dict[str, Any]:
    """Summarize compatible, fresh branch evidence without averaging scores.

    All times and maximum ages must use the same explicit clock and unit.
    Freshness bounds are inclusive. Missing or unusable branches make status
    INSUFFICIENT_DATA; an independently usable motion anomaly remains visible
    in summary. Neither a complete pair nor NO_DETECTED_CHANGE establishes
    safety, a failure class, or a calibrated local decision threshold.
    """
    decision_time = _finite_time(decision_time, "decision_time")
    max_soil_age = _finite_time(max_soil_age, "max_soil_age")
    max_motion_age = _finite_time(max_motion_age, "max_motion_age")
    for name, value in (("max_soil_age", max_soil_age), ("max_motion_age", max_motion_age)):
        if value < 0:
            raise ValueError(f"{name} must be nonnegative")
    for name, value in (("run_id", run_id), ("clock_id", clock_id)):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a nonempty string")

    reasons: list[str] = []

    def usable_state(branch: BranchEvidence | None, modality: str, max_age: float) -> str | None:
        if branch is None:
            reasons.append(f"{modality}:missing")
            return None
        if not isinstance(branch, BranchEvidence):
            raise TypeError(f"{modality} must be BranchEvidence or None")
        problems = []
        if branch.modality != modality:
            problems.append("modality_mismatch")
        allowed = {"stable", "wetting", "drying"} if modality == "soil" else {"quiet", "anomalous"}
        if not isinstance(branch.state, str) or branch.state not in allowed:
            problems.append("unknown_state")
        if type(branch.valid) is not bool:
            problems.append("invalid_valid_flag")
        elif not branch.valid:
            problems.append("invalid")
        if branch.run_id != run_id:
            problems.append("run_mismatch")
        if branch.clock_id != clock_id:
            problems.append("clock_mismatch")
        try:
            observed_at = _finite_time(branch.observed_at, "observed_at")
        except ValueError:
            problems.append("invalid_observed_at")
        else:
            age = decision_time - observed_at
            if age < 0:
                problems.append("future_observation")
            elif age > max_age:
                problems.append("stale")
        if problems:
            reasons.extend(f"{modality}:{problem}" for problem in problems)
            return None
        reasons.append(f"{modality}:{branch.state}")
        return branch.state

    soil_state = usable_state(soil, "soil", max_soil_age)
    motion_state = usable_state(motion, "motion", max_motion_age)
    complete = soil_state is not None and motion_state is not None
    if motion_state == "anomalous":
        summary = "COINCIDENT_WETTING_AND_MOTION" if soil_state == "wetting" else "MOTION_ANOMALY"
    elif complete:
        summary = {
            "wetting": "WETTING_WITHOUT_DETECTED_MOTION",
            "drying": "DRYING_WITHOUT_DETECTED_MOTION",
            "stable": "NO_DETECTED_CHANGE",
        }[soil_state]
    else:
        summary = "UNKNOWN"
    return {
        "scope": "RESEARCH_ONLY",
        "status": "EVIDENCE_AVAILABLE" if complete else "INSUFFICIENT_DATA",
        "summary": summary,
        "states": {"soil": soil_state, "motion": motion_state},
        "reasons": reasons,
        "interpretation": "Evidence summary only; paired local validation and calibrated thresholds are required for risk decisions.",
    }
