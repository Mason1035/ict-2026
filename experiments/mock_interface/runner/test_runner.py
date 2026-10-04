"""Focused local boundary tests; no production integration or hardware verdict."""

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import unittest

import edge_handoff
import risk_handoff
from mock_loader import load_case, SUPPORTED_CASES
from mock_v2_validator import validate
from run_mock_integration import run_case

CASES = Path(__file__).resolve().parent.parent / "cases"


class RunnerTests(unittest.TestCase):
    def loaded(self, name="M01_NORMAL"):
        return load_case(CASES / (name + ".json"))

    def test_positive_consumers_share_immutable_payload_and_preserve_nulls(self):
        for case_id in SUPPORTED_CASES[:3]:
            with self.subTest(case=case_id):
                seen = []

                def risk(payload, *, context):
                    seen.append(payload)
                    with self.assertRaises(TypeError):
                        payload["soil"]["middle_raw"] = 0
                    with self.assertRaises(TypeError):
                        payload["imu"][0]["ax"] = 99
                    return risk_handoff.receive_validated(payload, context=context)

                def edge(payload, *, context):
                    seen.append(payload)
                    return edge_handoff.receive_validated(payload, context=context)

                loaded = self.loaded(case_id)
                original = deepcopy(loaded.document)
                result = run_case(loaded, risk_consumer=risk, edge_consumer=edge)
                self.assertEqual(result["overall_status"], "LOCAL_RUNNER_PASS")
                self.assertIs(seen[0], seen[1])
                self.assertEqual(loaded.document, original)
                self.assertEqual(result["actual"]["accepted_message_count"], 1)
                self.assertEqual(result["actual"]["risk_handoff_call_count"], 1)
                self.assertEqual(result["actual"]["edge_handoff_call_count"], 1)
                row = result["messages"][0]
                self.assertEqual(row["risk_handoff_result"]["projection"]["risk"],
                                 {"sensor_score": None, "level": None, "reason_mask": None})
                if case_id == "M02_MISSING_SENSOR":
                    self.assertTrue(row["checks"]["middle_missing_preserved"])

    def test_m08_rejected_before_mapping_or_either_consumer(self):
        loaded = self.loaded("M08_INVALID_SCHEMA")
        doc = deepcopy(loaded.document)
        # A broken sidecar must not hide the intended payload type/schema errors.
        for message in doc["messages"]:
            message["sampling_snapshot"] = "bad TEST_ONLY sidecar"
        doc["expected_behavior"]["rejected_message_count"] = 999
        calls = []

        def forbidden(payload, *, context):
            calls.append(payload)
            raise AssertionError("An invalid message reached a normal consumer")

        result = run_case(replace(loaded, document=doc), risk_consumer=forbidden, edge_consumer=forbidden)
        self.assertEqual(result["overall_status"], "LOCAL_RUNNER_PASS")
        self.assertEqual(result["actual"]["rejected_message_count"], 4)
        self.assertEqual(calls, [])
        self.assertEqual([row["validator_result"]["errors"][0]["path"] for row in result["messages"]],
                         ["payload.schema", "payload.boot_id", "payload.seq", "payload.soil.middle_raw"])
        self.assertTrue(all(row["snapshot_check"]["status"] == "NOT_CALLED" for row in result["messages"]))

    def test_source_loss_rejects_before_handoffs(self):
        loaded = self.loaded()
        for outer in (True, False):
            doc = deepcopy(loaded.document)
            (doc if outer else doc["messages"][0])["source"] = "REAL"
            result = run_case(replace(loaded, document=doc))
            self.assertEqual(result["overall_status"], "FAIL")
            self.assertEqual(result["actual"]["risk_handoff_call_count"], 0)
            self.assertEqual(result["actual"]["edge_handoff_call_count"], 0)
            self.assertEqual(result["messages"][0]["validator_result"]["errors"][0]["code"], "SOURCE")

    def test_invalid_sidecar_fails_after_valid_payload_without_repair(self):
        loaded = self.loaded("M02_MISSING_SENSOR")
        doc = deepcopy(loaded.document)
        doc["messages"][0]["sampling_snapshot"]["soil"][1]["raw"] = 0
        result = run_case(replace(loaded, document=doc))
        self.assertEqual(result["messages"][0]["validator_result"]["status"], "ACCEPT")
        self.assertEqual(result["messages"][0]["snapshot_check"]["status"], "FAIL")
        self.assertEqual(result["actual"]["risk_handoff_call_count"], 0)
        self.assertIsNone(doc["messages"][0]["payload"]["soil"]["middle_raw"])

    def test_risk_consumer_failure_does_not_route_or_block_edge_via_risk_output(self):
        def broken(payload, *, context):
            raise RuntimeError("local risk adapter failure")
        result = run_case(self.loaded(), risk_consumer=broken)
        self.assertEqual(result["overall_status"], "FAIL")
        self.assertEqual(result["messages"][0]["risk_handoff_result"]["status"], "FAIL")
        self.assertEqual(result["messages"][0]["edge_handoff_result"]["status"], "ACCEPTED")

    def test_validator_is_format_gate_not_missing_policy(self):
        original = self.loaded().document["messages"][0]["payload"]
        payload = deepcopy(original)
        payload["soil"]["middle_raw"] = None
        payload["imu"][1]["valid"] = False
        for key in payload["imu"][1]:
            if key not in ("id", "valid"):
                payload["imu"][1][key] = None
        self.assertEqual(validate(payload)["status"], "ACCEPT")
        for field, value in (("boot_id", True), ("seq", -1), ("time_synced", 0),
                             ("timestamp_ms", "UTC"), ("mock", True)):
            bad = deepcopy(original)
            bad[field] = value
            self.assertEqual(validate(bad)["status"], "REJECT", field)
        for value in ("hello", False):
            bad = deepcopy(original)
            bad["soil"]["middle_raw"] = value
            self.assertEqual(validate(bad)["status"], "REJECT")
        bad = deepcopy(original)
        bad["imu"][0]["ax"] = float("nan")
        self.assertEqual(validate(bad)["status"], "REJECT")


if __name__ == "__main__":
    unittest.main()
