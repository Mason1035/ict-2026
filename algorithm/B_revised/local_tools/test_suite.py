"""多场景以及独立交接包测试。"""
import tempfile
import unittest
import zipfile
from pathlib import Path

from local_tools.build_package import build, verify
from local_tools.scenarios import check_scenario, scenarios
from telemetry_v2_intake.demo_runtime import test_only_config
from telemetry_v2_intake.replay import replay_records


class IndependentSuiteTests(unittest.TestCase):
    def test_all_eight_scenarios(self):
        cases = scenarios()
        self.assertEqual(len(cases), 8)
        for name, records in cases.items():
            with self.subTest(name=name):
                outputs, _ = replay_records(list(enumerate(records, 1)), test_only_config())
                self.assertEqual(check_scenario(name, outputs)["status"], "TEST_ONLY_EXPECTATIONS_MET")

    def test_package_no_environment_or_raw_data_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "b.zip"
            manifest = build(path)
            self.assertFalse(manifest["formal_training_ready"])
            self.assertIn("telemetry_v2_intake/runtime.py", manifest["files"])
            self.assertFalse(any(".venv" in n or "local_runs" in n or n.endswith(".csv") for n in manifest["files"]))
            verify(path)
            with self.assertRaises(FileExistsError):
                build(path)

    def test_zip_tampering_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, corrupt = Path(tmp) / "b.zip", Path(tmp) / "bad.zip"
            build(source)
            with zipfile.ZipFile(source) as old, zipfile.ZipFile(corrupt, "x") as new:
                for name in old.namelist():
                    new.writestr(name, b"tampered" if name == "run_independent.py" else old.read(name))
            with self.assertRaises(ValueError):
                verify(corrupt)
