"""Executable boundary tests for B → C; no disaster model is trained."""

import csv
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
RULE_DIR = ROOT / "队员B_算法开发交付"
sys.path.insert(0, str(RULE_DIR))

from contracts.validate_contract import (  # noqa: E402
    validate_contract, validate_contract_file, read_contract, STATUS_TEST, STATUS_FORMAL_BLOCKED,
)
from adapters.export_training_fixture import (  # noqa: E402
    export_fixture, verify_artifact, REQUIRED_FILES, DEFAULT_OUTPUT,
)
from examples import scenarios  # noqa: E402
from risk_algorithm import evaluate  # noqa: E402

RULE = ROOT / "contracts/B_RULE_DISTILLATION_CONTRACT.json"
FORMAL = ROOT / "contracts/B_FORMAL_TRAINING_CONTRACT_DRAFT.json"


class BAdaptationTests(unittest.TestCase):
    def test_original_risk_algorithm_and_demo_rules_unchanged(self):
        self.assertEqual(hashlib.sha256((RULE_DIR / "risk_algorithm.py").read_bytes()).hexdigest(),
                         "a7c70e74bc9449e3697c898459726f71b7e56e7f82653e4edbd5f2c7b45b0742")
        self.assertEqual(hashlib.sha256((RULE_DIR / "demo_rules.json").read_bytes()).hexdigest(),
                         "7a2a8b09a19edd369eb1ea7be6259c8c0fc9b309b275206f358e8170e48fd8ba")
        expected = read_contract(RULE_DIR / "sample_outputs.json")
        for name, records in scenarios().items():
            self.assertEqual(evaluate(records), expected[name])

    def test_rule_contract_parse_and_test_only_status(self):
        c = read_contract(RULE)
        self.assertEqual(validate_contract_file(RULE)["status"], STATUS_TEST)
        self.assertFalse(c["formal_training_ready"])
        self.assertFalse(c["physics_inspired"])

    def test_formal_draft_parse_and_fail_closed_status(self):
        c = read_contract(FORMAL)
        result = validate_contract_file(FORMAL)
        self.assertEqual(result["status"], STATUS_FORMAL_BLOCKED)
        self.assertEqual(result["waiting_for"], ["WAITING_FOR_A", "WAITING_FOR_B"])
        self.assertFalse(c["training_ready"])
        self.assertIsNone(c["feature_contract"]["ordered_features"])
        self.assertIsNone(c["label_contract"])
        self.assertIsNone(c["window_contract"]["window_length"])
        self.assertIsNone(c["split_contract"]["manifest"])

    def test_formal_cannot_claim_ready_by_status_or_boolean(self):
        c = read_contract(FORMAL)
        for key, value in (("status", "APPROVED"), ("training_ready", True),
                           ("formal_training_ready", True), ("contract_version", "1.0")):
            altered = deepcopy(c)
            altered[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_contract(altered)

    def test_rule_cannot_claim_production(self):
        c = read_contract(RULE)
        for key, value in (("status", "PRODUCTION_READY"), ("training_ready", True),
                           ("formal_training_ready", True), ("physics_inspired", True)):
            altered = deepcopy(c)
            altered[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_contract(altered)

    def test_model_features_exclude_all_provenance_and_forbidden_fields(self):
        c = read_contract(RULE)
        features = set(c["model_features"])
        self.assertEqual(len(features), 4)
        self.assertFalse(features & set(c["provenance_fields"]))
        self.assertFalse(features & set(c["forbidden_model_features"]))
        self.assertIn("synthetic_source", c["forbidden_model_features"])
        self.assertIn("failure_time", c["forbidden_model_features"])

    def test_forbidden_model_feature_is_enforced(self):
        c = read_contract(RULE)
        c["model_features"][0] = "synthetic_source"
        with self.assertRaises(ValueError):
            validate_contract(c)

    def test_test_only_version_rejects_silent_feature_window_split_drift(self):
        for mutate in (
            lambda c: c["model_features"].reverse(),
            lambda c: c["window"].update({"records_per_window": 7}),
            lambda c: c["split"].update({"ratios": {"train": 0.8, "validation": 0.1, "test": 0.1}}),
        ):
            c = read_contract(RULE)
            mutate(c)
            with self.assertRaises(ValueError):
                validate_contract(c)
        c = read_contract(RULE)
        c["forbidden_model_features"].remove("failure_time")
        with self.assertRaises(ValueError):
            validate_contract(c)

    def test_json_markdown_identity_agrees(self):
        for stem, path in (("B_RULE_DISTILLATION_CONTRACT", RULE),
                           ("B_FORMAL_TRAINING_CONTRACT_DRAFT", FORMAL)):
            json_value = read_contract(path)
            markdown = (ROOT / "contracts" / (stem + ".md")).read_text(encoding="utf-8")
            for key, marker in (("contract_id", "Contract ID"),
                                ("contract_version", "Contract Version"), ("status", "Status")):
                self.assertIn(f"{marker}: {json_value[key]}", markdown)

    def test_export_complete_artifact_and_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "fixture"
            result = export_fixture(out)
            self.assertEqual(result["status"], STATUS_TEST)
            self.assertEqual(result["file_hashes_verified"], len(REQUIRED_FILES))
            manifest = read_contract(out / "manifest.json")
            self.assertEqual(set(manifest["file_hashes"]), REQUIRED_FILES)
            for name, digest in manifest["file_hashes"].items():
                self.assertEqual(hashlib.sha256((out / name).read_bytes()).hexdigest(), digest)
            self.assertEqual(verify_artifact(out)["row_counts"], manifest["row_counts"])

    def test_split_counts_and_unknown_not_supervised(self):
        manifest = read_contract(DEFAULT_OUTPUT / "manifest.json")
        summary = read_contract(DEFAULT_OUTPUT / "summary.json")
        self.assertEqual(manifest["row_counts"], {"dataset_all": 180, "excluded_unknown": 18,
                                                   "train": 126, "validation": 27, "test": 27})
        all_ids = set()
        for split in ("train", "validation", "test"):
            with (DEFAULT_OUTPUT / f"{split}.csv").open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), summary["splits"][split]["rows"])
            ids = {row["group_id"] for row in rows}
            self.assertEqual(len(ids), len(rows))
            self.assertFalse(ids & all_ids)
            all_ids |= ids
        with (DEFAULT_OUTPUT / "excluded_unknown.csv").open(encoding="utf-8-sig", newline="") as stream:
            unknown = list(csv.DictReader(stream))
        self.assertTrue(all(row["label"] == "" and row["teacher_risk_level"] == "unknown" for row in unknown))
        self.assertFalse({row["group_id"] for row in unknown} & all_ids)
        self.assertEqual(len(unknown), summary["excluded_unknown_rows"])

    def test_original_demo_split_and_feature_bytes_preserved(self):
        legacy = ROOT / "智哨防灾_PRE_B_TRAINING_CONTRACT/artifacts/pre_b_training_contract"
        for name in ("dataset_all.csv", "train.csv", "validation.csv", "test.csv", "excluded_unknown.csv"):
            self.assertEqual((DEFAULT_OUTPUT / name).read_bytes(), (legacy / name).read_bytes(), name)
        # The archived Windows JSONL uses CRLF; compare audit records, not OS
        # newline encoding. CSV feature/label/split bytes above remain exact.
        self.assertEqual(
            [json.loads(line) for line in (DEFAULT_OUTPUT / "synthetic_histories.jsonl").read_text().splitlines()],
            [json.loads(line) for line in (legacy / "synthetic_histories.jsonl").read_text().splitlines()])

    def test_repeated_export_deterministic_without_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp) / "a", Path(tmp) / "b"
            export_fixture(a)
            export_fixture(b)
            self.assertEqual((a / "manifest.json").read_bytes(), (b / "manifest.json").read_bytes())
            before = (a / "manifest.json").read_bytes()
            with self.assertRaises(FileExistsError):
                export_fixture(a)
            self.assertEqual((a / "manifest.json").read_bytes(), before)

    def test_artifact_tampering_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "fixture"
            export_fixture(out)
            with (out / "train.csv").open("ab") as stream:
                stream.write(b"\n")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                verify_artifact(out)

    def test_rehashed_split_content_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "fixture"
            export_fixture(out)
            path = out / "train.csv"
            with path.open(encoding="utf-8-sig", newline="") as stream:
                reader = csv.DictReader(stream)
                names, rows = reader.fieldnames, list(reader)
            feature = read_contract(RULE)["model_features"][0]
            rows[0][feature] = "999"
            with path.open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=names)
                writer.writeheader()
                writer.writerows(rows)
            manifest = read_contract(out / "manifest.json")
            manifest["file_hashes"]["train.csv"] = hashlib.sha256(path.read_bytes()).hexdigest()
            (out / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "differs from dataset_all"):
                verify_artifact(out)

    def test_manifest_identity_and_status_unambiguous(self):
        manifest = read_contract(DEFAULT_OUTPUT / "manifest.json")
        self.assertEqual(manifest["artifact_role"], "AI_TRAINING_FRAMEWORK_TEST_FIXTURE")
        self.assertEqual(manifest["dataset_role"], "TEST_ONLY_RULE_DISTILLATION_FIXTURE")
        self.assertEqual(manifest["synthetic_source"], "b_rule_distillation_fixture")
        self.assertFalse(manifest["formal_training_dataset"] or manifest["physics_inspired"])
        self.assertIsNone(manifest["run_id"])
        self.assertIsNone(manifest["parent_run"])
        self.assertIsNone(manifest["parameter_hash"])
        self.assertEqual(manifest["model_features"], read_contract(RULE)["model_features"])

    def test_cli_machine_readable_statuses(self):
        script = ROOT / "contracts/validate_contract.py"
        for path, status in ((RULE, STATUS_TEST), (FORMAL, STATUS_FORMAL_BLOCKED)):
            result = subprocess.run([sys.executable, "-B", str(script), str(path)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["status"], status)

    def test_fixture_verifier_cli(self):
        script = ROOT / "adapters/export_training_fixture.py"
        result = subprocess.run([sys.executable, "-B", str(script), "--verify", str(DEFAULT_OUTPUT)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], STATUS_TEST)


if __name__ == "__main__":
    unittest.main()
