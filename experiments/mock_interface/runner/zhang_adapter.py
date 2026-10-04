"""TEST_ONLY / INTEGRATION_ADAPTER, no replacement Feature/Risk implementation."""

import risk_handoff
from teammate_source import initial_result, invoke_real, target_modules


def receive_validated(payload, *, context):
    # Retain the existing local preservation checks, distinctly from real calls.
    handoff = risk_handoff.receive_validated(payload, context=context)
    result = initial_result("zhang", handoff["payload_sha256"])
    result.update(
        execution_status="RISK_EXECUTION_BLOCKED", formal_risk_executed=False,
        risk_score_produced=False, risk_fields_preserved=handoff["projection"]["risk"],
        blocked_reason=["No reviewed per-probe dry/wet calibration; pass None, never guessed constants.",
                        "No calibrated tilt/baseline, dynamic-acceleration/window or contribution mapping.",
                        "No integrated formal Missing Policy / invalid-input policy or reason_mask table."],
        boundary_scope="REAL_CANDIDATE_FUNCTIONS_WITH_MISSING_PARAMETERS_NOT_FORMAL_SCORING",
    )
    try:
        with target_modules("zhang") as modules:
            reference = modules["candidate_features.reference"]
            for site in ("top", "middle", "toe"):
                call = invoke_real("zhang", reference.__name__, reference.relative_wetness_index,
                                   payload["soil"][site + "_raw"], None, None)
                call["channel"] = site
                call["parameter_source"] = "raw from unchanged v2; dry_raw/wet_raw unavailable (None)"
                result["calls"].append(call)
            # Existing derived tilt fields are unknown in these cases; preserve None.
            call = invoke_real("zhang", reference.__name__, reference.dual_imu_tilt_difference_deg,
                               payload["imu"][0]["tilt_deg"], payload["imu"][1]["tilt_deg"])
            call["parameter_source"] = "existing v2 tilt_deg fields; no baseline, filter or angle invented"
            result["calls"].append(call)
        calls = result["calls"]
        result["real_code_called"] = any(c["real_code_called"] for c in calls)
        result["reach_status"] = "REAL_CODE_REACHED" if result["real_code_called"] else "NOT_CALLED"
        # These pinned functions explicitly return None when required inputs are absent.
        expected = len(calls) == 4 and all(c["real_code_called"] and c["call_status"] == "RETURNED"
                                         and c.get("returned") is None for c in calls)
        result["adapter_status"] = "REAL_CODE_REACHED" if expected else "FAIL"
        if not expected:
            result["execution_status"] = "FAIL"
    except Exception as exc:
        result.update(adapter_status="BLOCKED", blocked_error=type(exc).__name__ + ": " + str(exc))
        result["real_code_called"] = any(c["real_code_called"] for c in result["calls"])
        result["reach_status"] = "REAL_CODE_REACHED" if result["real_code_called"] else "NOT_CALLED"
    handoff["teammate_integration"] = result
    return handoff
