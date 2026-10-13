"""文件回放、严格解析和产物审计的集成测试。"""
import json
import tempfile
import unittest
from pathlib import Path

from local_tools.common import dump, loads, verify_manifest
from telemetry_v2_intake.demo_runtime import fixture, test_only_config
from telemetry_v2_intake.replay import export_replay, replay_records


class ReplayTests(unittest.TestCase):
    def test_replay_duplicate_missing_and_restore(self):
        records = []
        for args in ({}, {}, {"start": 3010, "end": 3500, "seq": 2, "scenario": "missing"},
                     {"start": 3510, "end": 4000, "seq": 3}):
            p, c = fixture(**args)
            records.append((len(records) + 1, {"payload": p, "context": c}))
        outputs, report = replay_records(records, test_only_config())
        self.assertEqual(outputs[1]["result"]["processing"], "DUPLICATE_NO_RECOMPUTE")
        self.assertIsNone(outputs[2]["result"]["risk"]["sensor_score"])
        self.assertIsNone(outputs[3]["result"]["risk"]["sensor_score"])
        self.assertEqual(report["rejected_count"], 0)
        self.assertFalse(report["formal_training_ready"])

    def test_export_hashes_raw_bytes_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            p, c = fixture()
            source = root / "source.jsonl"
            source.write_text(json.dumps({"payload": p, "context": c}) + "\n", encoding="utf-8")
            config = root / "test_config.json"
            dump(config, test_only_config())
            target = root / "out"
            export_replay(source, config, target)
            verify_manifest(target)
            self.assertEqual(source.read_bytes(), (target / "input.jsonl").read_bytes())
            with self.assertRaises(FileExistsError):
                export_replay(source, config, target)
            (target / "results.jsonl").write_text("tampered", encoding="utf-8")
            with self.assertRaises(ValueError):
                verify_manifest(target)

    def test_nonfinite_duplicate_fields_and_unregistered_file_rejected(self):
        for text in ('{"x":NaN}', '{"x":1,"x":2}', '{"x":1e999}'):
            with self.assertRaises(ValueError):
                loads(text)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dump(root / "manifest.json", {"schema": "B.local_artifact_manifest.v1", "files": {}})
            with self.assertRaises(ValueError):
                verify_manifest(root)

    def test_draft_rejected_before_output_directory_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.jsonl"
            source.write_text('{}\n', encoding="utf-8")
            draft = Path(__file__).resolve().parent.parent / "telemetry_v2_intake" / "RUNTIME_CONFIG_DRAFT.json"
            with self.assertRaises(ValueError):
                export_replay(source, draft, root / "out")
            self.assertFalse((root / "out").exists())
