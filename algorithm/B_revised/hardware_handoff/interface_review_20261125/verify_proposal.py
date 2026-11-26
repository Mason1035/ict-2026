"""Offline proposal checks only; no GPIO, network or device config activation."""
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from telemetry_v2_intake.config import validate_config
from candidate_features.risk_math import risk_level


def compare(reference, actual, *, atol=0.001, rtol=1e-5):
    if reference is None or actual is None:
        return reference is actual
    if type(reference) not in (int, float) or type(actual) not in (int, float):
        return False
    return (math.isfinite(reference) and math.isfinite(actual)
            and abs(actual-reference) <= atol + rtol*abs(reference))


def check():
    proposal = json.loads((HERE / "INTERFACE_PROPOSAL.json").read_text(encoding="utf-8"))
    assert proposal["status"] == "PENDING_A_B_C_REVIEW"
    assert proposal["loadable_on_device"] is False
    assert all(v is None for v in proposal["review_refs"].values())
    bits = proposal["reason_mask_proposal"]["bits"]
    assert set(bits.values()) == set(range(5))
    assert sum(1 << bit for bit in bits.values()) == 31
    assert proposal["reason_mask_proposal"]["invalid_score_mask"] is None
    assert proposal["missing_policy"] == "REQUIRE_BOTH_IMU_AND_ALL_THREE_SOIL_V1"
    draft = json.loads((HERE / "RUNTIME_CONFIG_DRAFT.json").read_text(encoding="utf-8"))
    try:
        validate_config(draft)
    except ValueError as exc:
        assert "DRAFT" in str(exc)
    else:
        raise AssertionError("DRAFT must be rejected")
    policy = proposal["alarm_policy_proposal"]
    assert policy["mode"] == "DRAFT" and policy["unknown_keeps_latch"]
    assert not policy["auto_clear"] and policy["clear_requires_ack"]
    assert all(policy[k] is None for k in ("entry_dwell_ms", "clear_score_exclusive", "clear_dwell_ms"))
    assert compare(30, 30.0001)
    assert not compare(30, 30.1)
    assert compare(None, None) and not compare(None, 0)
    assert not compare(0, float("nan"))
    # Numeric tolerance never grants permission for a classification mismatch.
    assert compare(30, 29.9999) and risk_level(30) != risk_level(29.9999)
    for edge, below, at in [(30,"NORMAL","WATCH"),(60,"WATCH","WARNING"),(80,"WARNING","EMERGENCY")]:
        assert risk_level(edge - 0.001) == below
        assert risk_level(edge) == at
    print("PASS: proposal consistency, DRAFT rejection, null/finite checks and strict level boundaries")
    print("NOT device golden vectors; NOT AlarmTask implementation; NOT A/B/C approval")


if __name__ == "__main__":
    check()
