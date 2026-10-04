"""TEST_ONLY / INTEGRATION_ADAPTER: real skeleton capability probe, NOT Edge Intake.

RealAdapter is a training artifact boundary and unconditionally raises today.
Calling it proves a real module was reached, NOT that it can consume v2/accept data.
"""

import edge_handoff
from teammate_source import initial_result, invoke_real, target_modules


def receive_validated(payload, *, context):
    handoff = edge_handoff.receive_validated(payload, context=context)
    result = initial_result("he", handoff["payload_sha256"])
    result.update(
        adapter_status="INTERFACE_MISMATCH", execution_status="EDGE_INTAKE_NOT_IMPLEMENTED",
        edge_intake_exists=False, telemetry_accepted_by_teammate=False,
        boundary_scope="NEGATIVE_CAPABILITY_PROBE_OF_TRAINING_ADAPTER_SKELETON",
        blocked_reason=["Existing RealAdapter expects an artifact/TrainingContract, not Telemetry v2.",
                        "Pinned RealAdapter.to_dataset always raises ContractNotReadyError.",
                        "No real Telemetry Validator / Edge Intake entry exists in this source version."],
    )
    try:
        with target_modules("he") as modules:
            real = modules["ai_training.adapters.real"]
            errors = modules["ai_training.errors"]
            # Explicit incompatible-input probe, without forging an artifact or contract.
            # This is the SAME shared immutable Telemetry received by Zhang Adapter.
            call = invoke_real("he", real.__name__, real.RealAdapter().to_dataset,
                               artifact=payload, contract=None,
                               expected_exception=errors.ContractNotReadyError)
            result["calls"].append(call)
        result["real_code_called"] = call["real_code_called"]
        result["reach_status"] = call["reach_status"]
        if not call["real_code_called"] or call["call_status"] != "EXPECTED_BLOCK":
            # A changed API/return is a review event, never automatic integration success.
            result.update(adapter_status="FAIL", execution_status="FAIL")
    except Exception as exc:
        result.update(adapter_status="BLOCKED", blocked_error=type(exc).__name__ + ": " + str(exc))
    handoff["teammate_integration"] = result
    return handoff
