"""Focused pinned-source boundary tests; no formal Risk/Edge success claims."""

from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import he_adapter
import teammate_source
import zhang_adapter
from mock_loader import freeze, load_case
from mock_v2_validator import validate
from run_mock_integration import run_case

CASES = Path(__file__).resolve().parent.parent / "cases"


class TeammateIntegrationTests(unittest.TestCase):
    def test_positive_cases_reach_real_functions_without_fabricating_results(self):
        for name in ("M01_NORMAL", "M02_MISSING_SENSOR", "M07_RISK_NOT_CALIBRATED"):
            with self.subTest(case=name):
                loaded = load_case(CASES / (name + ".json"))
                original = deepcopy(loaded.document)
                seen = []

                def zhang(payload, *, context):
                    seen.append(payload)
                    return zhang_adapter.receive_validated(payload, context=context)

                def he(payload, *, context):
                    seen.append(payload)
                    return he_adapter.receive_validated(payload, context=context)

                # Distinguish Zhang's legitimate internal Feature calls from an
                # adapter bypassing the public entry (even without invoke_real).
                old_probes = []
                previous_profile = sys.getprofile()

                def observe(frame, event, arg):
                    if event == "call":
                        code = frame.f_code
                        if code.co_name in ("relative_wetness_index", "dual_imu_tilt_difference_deg"):
                            caller = frame.f_back
                            if not (caller and caller.f_code.co_name == "evaluate_telemetry_v2"
                                    and caller.f_code.co_filename.startswith("git:")
                                    and caller.f_code.co_filename.endswith("/telemetry_v2_intake/entry.py")):
                                old_probes.append(code.co_name)
                        elif code.co_name == "to_dataset":
                            old_probes.append(code.co_name)
                    if previous_profile is not None:
                        previous_profile(frame, event, arg)

                try:
                    sys.setprofile(observe)
                    result = run_case(loaded, risk_consumer=zhang, edge_consumer=he,
                                      integration_mode="TEAMMATE_INTAKE_V0.2")
                finally:
                    sys.setprofile(previous_profile)
                self.assertEqual(old_probes, [], "Adapter called a legacy probe")
                self.assertEqual(result["overall_status"], "LOCAL_RUNNER_PASS")
                self.assertIs(seen[0], seen[1])
                self.assertEqual(loaded.document, original)
                row = result["messages"][0]
                z, h = row["zhang_adapter_result"], row["he_adapter_result"]
                self.assertEqual(result["actual"]["zhang_real_function_call_count"], 1)
                self.assertEqual(result["actual"]["he_real_function_call_count"], 1)
                self.assertTrue(all(c["real_code_called"] for c in z["calls"] + h["calls"]))
                self.assertEqual(z["execution_status"], "RISK_EXECUTION_BLOCKED")
                self.assertFalse(z["formal_risk_executed"])
                self.assertEqual(z["adapter_status"], "TELEMETRY_ACCEPTED")
                self.assertTrue(z["telemetry_accepted_by_teammate"])
                self.assertEqual(z["feature_status"], "BLOCKED")
                self.assertEqual(z["calls"][0]["source_function"], "evaluate_telemetry_v2")
                self.assertEqual(h["calls"][0]["source_function"], "receive_validated_telemetry")
                self.assertEqual(h["adapter_status"], "EDGE_INTAKE_ACCEPTED")
                self.assertEqual(h["execution_status"], "DOWNSTREAM_NOT_IMPLEMENTED")
                self.assertTrue(h["telemetry_accepted_by_teammate"])
                self.assertFalse(h["durable"])
                for adapter in (z, h):
                    self.assertEqual(len(adapter["calls"]), 1)
                    self.assertTrue(all(adapter["receipt_checks"].values()))
                    self.assertEqual(adapter["calls"][0]["arguments"]["args"][0], original["messages"][0]["payload"])
                self.assertEqual(z["calls"][0]["returned"]["risk"], original["messages"][0]["payload"]["risk"])
                self.assertEqual(h["calls"][0]["returned"]["payload"], original["messages"][0]["payload"])
                if name == "M02_MISSING_SENSOR":
                    self.assertIsNone(z["calls"][0]["returned"]["observations"]["soil"]["middle_raw"])
                    self.assertIsNone(h["calls"][0]["returned"]["payload"]["soil"]["middle_raw"])
                    self.assertTrue(row["checks"]["middle_missing_preserved"])
                self.assertNotIn("candidate_features", sys.modules)
                self.assertNotIn("telemetry_v2_intake", sys.modules)
                self.assertNotIn("edge_intake", sys.modules)

    def test_he_returns_handoff_with_real_edge_receipt(self):
        loaded = load_case(CASES / "M02_MISSING_SENSOR.json")
        message = loaded.document["messages"][0]
        self.assertEqual(validate(message["payload"])["status"], "ACCEPT")
        payload = freeze(message["payload"])
        context = freeze({"source": "MOCK", "case_id": loaded.document["case_id"],
                          "sampling_snapshot": message["sampling_snapshot"], "scope": "TEST_ONLY"})
        handoff = he_adapter.receive_validated(payload, context=context)
        self.assertIsNotNone(handoff)
        self.assertIsInstance(handoff, dict)
        self.assertEqual(handoff["payload"], message["payload"])
        result = handoff["teammate_integration"]
        self.assertEqual(result["adapter_status"], "EDGE_INTAKE_ACCEPTED")
        self.assertEqual(result["execution_status"], "DOWNSTREAM_NOT_IMPLEMENTED")
        self.assertFalse(result["durable"])
        self.assertEqual(len(result["calls"]), 1)
        call = result["calls"][0]
        self.assertTrue(call["real_code_called"])
        self.assertEqual(call["source_function"], "receive_validated_telemetry")
        self.assertEqual(call["returned"]["status"], "ACCEPTED_BY_EDGE_INTAKE")
        self.assertTrue(all(result["receipt_checks"].values()))

    def test_he_returns_blocked_handoff_on_loading_or_invocation_exception(self):
        message = load_case(CASES / "M01_NORMAL.json").document["messages"][0]
        payload = freeze(message["payload"])
        context = freeze({"source": "MOCK", "sampling_snapshot": message["sampling_snapshot"]})
        for boundary in ("target_modules", "invoke_real"):
            with self.subTest(boundary=boundary), patch.object(
                he_adapter, boundary, side_effect=RuntimeError("test boundary unavailable")
            ):
                handoff = he_adapter.receive_validated(payload, context=context)
            self.assertIsNotNone(handoff)
            self.assertIsInstance(handoff, dict)
            result = handoff["teammate_integration"]
            self.assertEqual(result["adapter_status"], "BLOCKED")
            self.assertIn("test boundary unavailable", result["blocked_error"])
            self.assertFalse(result["real_code_called"])
            self.assertFalse(result["telemetry_accepted_by_teammate"])

    def test_m08_never_loads_or_calls_real_teammate_code(self):
        loaded = load_case(CASES / "M08_INVALID_SCHEMA.json")
        with patch.object(zhang_adapter, "target_modules", side_effect=AssertionError("Zhang called")) as z:
            with patch.object(he_adapter, "target_modules", side_effect=AssertionError("He called")) as h:
                result = run_case(loaded, risk_consumer=zhang_adapter.receive_validated,
                                  edge_consumer=he_adapter.receive_validated,
                                  integration_mode="TEAMMATE_INTAKE_V0.2")
        z.assert_not_called()
        h.assert_not_called()
        self.assertEqual(result["overall_status"], "LOCAL_RUNNER_PASS")
        self.assertEqual(result["actual"]["rejected_message_count"], 4)
        self.assertEqual(result["actual"]["zhang_real_function_call_count"], 0)
        self.assertEqual(result["actual"]["he_real_function_call_count"], 0)

    def test_hash_mismatch_blocks_before_any_teammate_call(self):
        spec = teammate_source.source_spec("zhang")
        spec["modules"][0]["sha256"] = "0" * 64
        with patch.object(teammate_source, "source_spec", return_value=spec):
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                with teammate_source.target_modules("zhang"):
                    self.fail("Unverified source loaded")
        self.assertNotIn("candidate_features", sys.modules)

    def test_missing_git_source_cannot_be_reported_as_reached(self):
        loaded = load_case(CASES / "M01_NORMAL.json")
        with patch.object(zhang_adapter, "target_modules", side_effect=RuntimeError("Git object missing")):
            result = run_case(loaded, risk_consumer=zhang_adapter.receive_validated,
                              edge_consumer=he_adapter.receive_validated,
                              integration_mode="TEAMMATE_INTAKE_V0.2")
        self.assertEqual(result["overall_status"], "FAIL")
        row = result["messages"][0]
        self.assertFalse(row["zhang_adapter_result"]["real_code_called"])
        self.assertEqual(row["zhang_adapter_result"]["adapter_status"], "BLOCKED")
        self.assertTrue(row["he_adapter_result"]["real_code_called"])

    def test_receipt_corruption_cannot_be_reported_as_acceptance(self):
        loaded = load_case(CASES / "M02_MISSING_SENSOR.json")
        for adapter, key in ((zhang_adapter, "zhang"), (he_adapter, "he")):
            original_invoke = adapter.invoke_real

            def corrupt(*args, **kwargs):
                record = original_invoke(*args, **kwargs)
                receipt = record["returned"]
                soil = receipt["observations"]["soil"] if key == "zhang" else receipt["payload"]["soil"]
                soil["middle_raw"] = 0
                return record

            with self.subTest(adapter=key), patch.object(adapter, "invoke_real", side_effect=corrupt):
                result = run_case(loaded, risk_consumer=zhang_adapter.receive_validated,
                                  edge_consumer=he_adapter.receive_validated,
                                  integration_mode="TEAMMATE_INTAKE_V0.2")
            failed = result["messages"][0][key + "_adapter_result"]
            self.assertTrue(failed["real_code_called"])
            self.assertFalse(failed["telemetry_accepted_by_teammate"])
            self.assertEqual(failed["adapter_status"], "FAIL")
            self.assertEqual(result["overall_status"], "FAIL")

    def test_loader_does_not_shadow_second_namespace(self):
        import types
        sentinel = types.ModuleType("telemetry_v2_intake")
        with patch.dict(sys.modules, {"telemetry_v2_intake": sentinel}):
            with self.assertRaisesRegex(RuntimeError, "Refusing to shadow"):
                with teammate_source.target_modules("zhang"):
                    self.fail("Existing module was overwritten")
            self.assertIs(sys.modules["telemetry_v2_intake"], sentinel)
        self.assertNotIn("candidate_features", sys.modules)


if __name__ == "__main__":
    unittest.main()
