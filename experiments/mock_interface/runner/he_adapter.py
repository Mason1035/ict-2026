"""TEST_ONLY adapter to He Yuxuan's pinned Edge Intake; no training-artifact probe."""

import edge_handoff
from mock_loader import plain
from teammate_source import initial_result, invoke_real, target_modules


def receive_validated(payload, *, context):
    handoff = edge_handoff.receive_validated(payload, context=context)
    result = initial_result("he", handoff["payload_sha256"])
    result.update(edge_intake_exists=True, telemetry_accepted_by_teammate=False,
                  boundary_scope="VALIDATED_TELEMETRY_V2_IN_MEMORY_EDGE_INTAKE")
    try:
        with target_modules("he") as modules:
            entry = modules["edge_intake.intake"]
            call = invoke_real("he", entry.__name__, entry.receive_validated_telemetry,
                               payload, context=context)
            result["calls"].append(call)
        result.update(real_code_called=call["real_code_called"], reach_status=call["reach_status"])
        returned = call.get("returned")
        returned = returned if isinstance(returned, dict) else {}
        checks = {
            "entry_returned": call["real_code_called"] and call["call_status"] == "RETURNED",
            "entry_status": returned.get("status") == "ACCEPTED_BY_EDGE_INTAKE",
            "payload_preserved": returned.get("payload") == plain(payload),
            "context_preserved": returned.get("context") == plain(context),
            "source_preserved": returned.get("source") == context["source"],
            "identity_preserved": returned.get("identity") == {k: payload[k] for k in ("device_id", "boot_id", "seq")},
            "payload_hash_matches": returned.get("payload_sha256") == handoff["payload_sha256"],
            "not_durable": returned.get("durable") is False,
            "downstream_not_implemented": returned.get("downstream") == "NOT_IMPLEMENTED"
                and returned.get("downstream_status") == "DOWNSTREAM_NOT_IMPLEMENTED",
        }
        accepted = all(checks.values())
        result.update(receipt_checks=checks, telemetry_accepted_by_teammate=accepted,
                      adapter_status="EDGE_INTAKE_ACCEPTED" if accepted else "FAIL",
                      execution_status=returned.get("downstream_status", "FAIL") if accepted else "FAIL",
                      durable=returned.get("durable"))
    except Exception as exc:
        result.update(adapter_status="BLOCKED", blocked_error=type(exc).__name__ + ": " + str(exc))
    handoff["teammate_integration"] = result
    return handoff
