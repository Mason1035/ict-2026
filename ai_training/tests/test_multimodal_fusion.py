from dataclasses import FrozenInstanceError, replace
import math

import pytest

from ai_training.multimodal.fusion import BranchEvidence, fuse


def evidence(modality_name, state_name, **changes):
    values = dict(modality=modality_name, state=state_name, observed_at=90.0,
                  run_id="run-a", clock_id="elapsed-seconds", valid=True)
    values.update(changes)
    return BranchEvidence(**values)


def decide(soil=None, motion=None, **changes):
    options = dict(decision_time=100.0, run_id="run-a", clock_id="elapsed-seconds",
                   max_soil_age=30.0, max_motion_age=10.0)
    options.update(changes)
    return fuse(soil, motion, **options)


@pytest.mark.parametrize(("soil_state", "motion_state", "summary"), [
    ("wetting", "anomalous", "COINCIDENT_WETTING_AND_MOTION"),
    ("wetting", "quiet", "WETTING_WITHOUT_DETECTED_MOTION"),
    ("stable", "anomalous", "MOTION_ANOMALY"),
    ("drying", "anomalous", "MOTION_ANOMALY"),
    ("stable", "quiet", "NO_DETECTED_CHANGE"),
    ("drying", "quiet", "DRYING_WITHOUT_DETECTED_MOTION"),
])
def test_rules_summarize_branch_evidence_without_risk_classes(soil_state, motion_state, summary):
    result = decide(evidence("soil", soil_state), evidence("motion", motion_state))
    assert result["status"] == "EVIDENCE_AVAILABLE"
    assert result["summary"] == summary
    assert result["scope"] == "RESEARCH_ONLY"
    assert f"soil:{soil_state}" in result["reasons"]
    assert f"motion:{motion_state}" in result["reasons"]
    assert not {"score", "risk", "risk_level", "class", "label"} & result.keys()
    assert result["summary"] not in {"NORMAL", "SLIP", "LOW", "HIGH"}


def test_no_evidence_and_missing_motion_never_imply_normal():
    empty = decide()
    assert empty["status"] == "INSUFFICIENT_DATA" and empty["summary"] == "UNKNOWN"
    assert {"soil:missing", "motion:missing"} <= set(empty["reasons"])
    soil_only = decide(evidence("soil", "stable"))
    assert soil_only["status"] == "INSUFFICIENT_DATA" and soil_only["summary"] == "UNKNOWN"


def test_motion_anomaly_is_preserved_without_claiming_a_complete_fusion():
    result = decide(motion=evidence("motion", "anomalous"))
    assert result["status"] == "INSUFFICIENT_DATA"
    assert result["summary"] == "MOTION_ANOMALY"
    assert "soil:missing" in result["reasons"]
    assert result["states"]["soil"] is None


@pytest.mark.parametrize(("changes", "reason"), [
    ({"run_id": "other-run"}, "run_mismatch"),
    ({"clock_id": "utc-seconds"}, "clock_mismatch"),
    ({"observed_at": 100.01}, "future_observation"),
    ({"observed_at": 69.99}, "stale"),
    ({"observed_at": math.nan}, "invalid_observed_at"),
    ({"observed_at": math.inf}, "invalid_observed_at"),
    ({"observed_at": True}, "invalid_observed_at"),
    ({"valid": False}, "invalid"),
    ({"valid": "false"}, "invalid_valid_flag"),
    ({"modality": "motion"}, "modality_mismatch"),
    ({"state": "unknown"}, "unknown_state"),
    ({"state": "0.95"}, "unknown_state"),
])
def test_unusable_soil_cannot_create_coincidence(changes, reason):
    result = decide(evidence("soil", "wetting", **changes), evidence("motion", "anomalous"))
    assert result["status"] == "INSUFFICIENT_DATA"
    assert result["summary"] == "MOTION_ANOMALY"
    assert f"soil:{reason}" in result["reasons"]
    assert result["states"]["soil"] is None


def test_each_branch_has_its_own_explicit_freshness_limit():
    soil = evidence("soil", "wetting", observed_at=70.0)
    motion = evidence("motion", "anomalous", observed_at=89.99)
    result = decide(soil, motion)
    assert result["summary"] == "UNKNOWN" and result["status"] == "INSUFFICIENT_DATA"
    assert "motion:stale" in result["reasons"] and "soil:stale" not in result["reasons"]
    accepted = decide(soil, replace(motion, observed_at=90.0))
    assert accepted["summary"] == "COINCIDENT_WETTING_AND_MOTION"


def test_current_observation_is_accepted_when_max_age_is_zero():
    result = decide(evidence("soil", "stable", observed_at=100.0),
                    evidence("motion", "quiet", observed_at=100.0),
                    max_soil_age=0.0, max_motion_age=0.0)
    assert result["summary"] == "NO_DETECTED_CHANGE"


def test_future_motion_is_not_used_even_when_soil_is_wetting():
    result = decide(evidence("soil", "wetting"), evidence("motion", "anomalous", observed_at=101.0))
    assert result["summary"] == "UNKNOWN" and result["status"] == "INSUFFICIENT_DATA"
    assert "motion:future_observation" in result["reasons"]


@pytest.mark.parametrize("option", ["decision_time", "max_soil_age", "max_motion_age"])
@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf, True, "10"])
def test_nonfinite_or_nonnumeric_timing_configuration_is_rejected(option, value):
    with pytest.raises(ValueError, match=option):
        decide(**{option: value})


@pytest.mark.parametrize("option", ["max_soil_age", "max_motion_age"])
def test_negative_freshness_configuration_is_rejected(option):
    with pytest.raises(ValueError, match=option):
        decide(**{option: -0.01})


@pytest.mark.parametrize("option", ["run_id", "clock_id"])
@pytest.mark.parametrize("value", [None, "", "   "])
def test_missing_context_is_rejected(option, value):
    with pytest.raises(ValueError, match=option):
        decide(**{option: value})


def test_evidence_is_frozen_and_fusion_does_not_modify_it():
    soil = evidence("soil", "wetting")
    with pytest.raises(FrozenInstanceError):
        soil.state = "stable"
    decide(soil, evidence("motion", "quiet"))
    assert soil.state == "wetting" and soil.observed_at == 90.0
