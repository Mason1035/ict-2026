"""TEST_ONLY adapter to Zhang Pengfei's pinned Telemetry v2 entry; no algorithm implementation."""

import risk_handoff
from mock_loader import plain
from teammate_source import initial_result, invoke_real, target_modules


def receive_validated(payload, *, context):
    handoff = risk_handoff.receive_validated(payload, context=context)
    result = initial_result("zhang", handoff["payload_sha256"])
    result.update(telemetry_accepted_by_teammate=False, formal_risk_executed=False,
                  risk_score_produced=False, boundary_scope="VALIDATED_TELEMETRY_V2_INTAKE")
    try:
        with target_modules("zhang") as modules:
            entry = modules["telemetry_v2_intake.entry"]
            call = invoke_real("zhang", entry.__name__, entry.evaluate_telemetry_v2,
                               payload, context=context)
            result["calls"].append(call)
        result.update(real_code_called=call["real_code_called"], reach_status=call["reach_status"])
        returned = call.get("returned")
        returned = returned if isinstance(returned, dict) else {}
        original = plain(payload)
        expected_observations = {
            "time": {k: original[k] for k in ("timestamp_ms", "uptime_ms", "time_synced")},
            "imu": {position: {k: v for k, v in imu.items() if k != "id"}
                    for position, imu in zip(("top", "toe"), original["imu"])},
            **{k: original[k] for k in ("soil", "system", "experiment")},
        }
        # Acceptance is established from a real returned receipt plus unchanged
        # identity/observations/risk, not from the local handoff's ACCEPTED label.
        checks = {
            "entry_returned": call["real_code_called"] and call["call_status"] == "RETURNED",
            "entry_status": returned.get("status") == "REAL_CODE_REACHED",
            "identity_preserved": returned.get("identity") == {k: original[k] for k in ("site_id", "device_id", "boot_id", "seq")},
            "observations_preserved": returned.get("observations") == expected_observations,
            "risk_preserved": returned.get("risk") == original["risk"],
            "risk_remains_blocked": returned.get("risk_execution") == "RISK_EXECUTION_BLOCKED",
            "sidecar_not_used_for_computation": returned.get("context_used_for_computation") is False,
        }
        accepted = all(checks.values())
        result.update(receipt_checks=checks, telemetry_accepted_by_teammate=accepted,
                      adapter_status="TELEMETRY_ACCEPTED" if accepted else "FAIL",
                      execution_status=returned.get("risk_execution", "FAIL") if accepted else "FAIL",
                      feature_status=returned.get("feature_status", "UNKNOWN"),
                      blocked_reason=returned.get("blocked_reason", []),
                      risk_fields_preserved=returned.get("risk"))
    except Exception as exc:
        result.update(adapter_status="BLOCKED", blocked_error=type(exc).__name__ + ": " + str(exc))
    handoff["teammate_integration"] = result
    return handoff
