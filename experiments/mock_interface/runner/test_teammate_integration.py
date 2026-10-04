"""Focused pinned-source boundary tests; no formal Risk/Edge success claims."""

from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import he_adapter
import teammate_source
import zhang_adapter
from mock_loader import load_case
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

                result = run_case(loaded, risk_consumer=zhang, edge_consumer=he,
                                  integration_mode="TEAMMATE_BOUNDARY_V0.1")
                self.assertEqual(result["overall_status"], "LOCAL_RUNNER_PASS")
                self.assertIs(seen[0], seen[1])
                self.assertEqual(loaded.document, original)
                row = result["messages"][0]
                z, h = row["zhang_adapter_result"], row["he_adapter_result"]
                self.assertEqual(result["actual"]["zhang_real_function_call_count"], 4)
                self.assertEqual(result["actual"]["he_real_function_call_count"], 1)
                self.assertTrue(all(c["real_code_called"] for c in z["calls"] + h["calls"]))
                self.assertEqual(z["execution_status"], "RISK_EXECUTION_BLOCKED")
                self.assertFalse(z["formal_risk_executed"])
                self.assertTrue(all(c["returned"] is None for c in z["calls"]))
                self.assertEqual(h["adapter_status"], "INTERFACE_MISMATCH")
                self.assertEqual(h["execution_status"], "EDGE_INTAKE_NOT_IMPLEMENTED")
                self.assertFalse(h["telemetry_accepted_by_teammate"])
                self.assertEqual(h["calls"][0]["exception_type"], "ContractNotReadyError")
                self.assertEqual(h["calls"][0]["arguments"]["kwargs"]["artifact"], original["messages"][0]["payload"])
                self.assertIsNone(h["calls"][0]["arguments"]["kwargs"]["contract"])
                if name == "M02_MISSING_SENSOR":
                    self.assertIsNone(z["calls"][1]["arguments"]["args"][0])
                    self.assertTrue(row["checks"]["middle_missing_preserved"])
                self.assertNotIn("candidate_features", sys.modules)
                self.assertNotIn("ai_training", sys.modules)

    def test_m08_never_loads_or_calls_real_teammate_code(self):
        loaded = load_case(CASES / "M08_INVALID_SCHEMA.json")
        with patch.object(zhang_adapter, "target_modules", side_effect=AssertionError("Zhang called")) as z:
            with patch.object(he_adapter, "target_modules", side_effect=AssertionError("He called")) as h:
                result = run_case(loaded, risk_consumer=zhang_adapter.receive_validated,
                                  edge_consumer=he_adapter.receive_validated,
                                  integration_mode="TEAMMATE_BOUNDARY_V0.1")
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
                              integration_mode="TEAMMATE_BOUNDARY_V0.1")
        self.assertEqual(result["overall_status"], "FAIL")
        row = result["messages"][0]
        self.assertFalse(row["zhang_adapter_result"]["real_code_called"])
        self.assertEqual(row["zhang_adapter_result"]["adapter_status"], "BLOCKED")
        self.assertTrue(row["he_adapter_result"]["real_code_called"])


if __name__ == "__main__":
    unittest.main()
