"""交接预检：不把材料齐全升级为真实就绪。"""
import csv
import tempfile
import unittest
from pathlib import Path

from data_intake.check_experiment_csv import HEADER
from data_intake.check_handoff import SIDECARS, inspect_handoff
from local_tools.common import dump, load, sha256


class HandoffTests(unittest.TestCase):
    def make_handoff(self, root):
        csv_path = root / "raw.csv"
        with csv_path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(HEADER)
            values = {name: "0" for name in HEADER}
            values.update(run_id="TEST-RUN", label="NORMAL")
            writer.writerow([values[name] for name in HEADER])
        doc = {"schema": "B.run_handoff.draft.v1", "source": "TEST_ONLY", "run_id": "TEST-RUN",
               "identity": {"site_id": "TEST-SITE", "device_id": "TEST-NODE", "boot_id": 1},
               "frame_id": "TEST-FRAME", "firmware_version": "TEST-FW", "calibration_version": "TEST-CAL",
               "odr_hz": {"imu": 100, "soil": 2},
               "sensor_ids": {"imu": {p: "imu-" + p for p in ("top", "toe")},
                              "soil": {p: "soil-" + p for p in ("top", "middle", "toe")}},
               "csv": {"path": csv_path.name, "sha256": sha256(csv_path)}, "sidecars": {}}
        for name in SIDECARS:
            path = root / (name + ".txt")
            path.write_text("TEST_ONLY mock evidence: " + name, encoding="utf-8")
            doc["sidecars"][name] = {"path": path.name, "sha256": sha256(path)}
        manifest = root / "handoff.json"
        dump(manifest, doc)
        return manifest

    def test_files_present_is_still_review_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = inspect_handoff(self.make_handoff(Path(tmp)))
            self.assertEqual(result["status"], "MATERIALS_PRESENT_REVIEW_REQUIRED")
            self.assertFalse(result["formal_training_ready"])
            self.assertFalse(result["real_data_verified"])

    def test_template_waits_for_a(self):
        path = Path(__file__).parent / "A_RUN_HANDOFF_DRAFT.json"
        result = inspect_handoff(path)
        self.assertEqual(result["status"], "WAITING_FOR_A")
        self.assertIn("validity", result["missing"])

    def test_hash_mismatch_missing_and_outside_directory(self):
        for fault in ("hash", "missing", "outside", "same_file"):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                manifest = self.make_handoff(root)
                doc = load(manifest)
                if fault == "hash":
                    (root / "raw.csv").write_text("modified", encoding="utf-8")
                elif fault == "missing":
                    (root / "timing.txt").unlink()
                elif fault == "outside":
                    doc["sidecars"]["timing"]["path"] = "../outside.txt"
                else:
                    doc["sidecars"]["timing"] = doc["csv"]
                manifest.unlink()  # 只操作测试临时文件，原始交付工具不覆盖
                dump(manifest, doc)
                result = inspect_handoff(manifest)
                self.assertEqual(result["status"], "WAITING_FOR_A" if fault == "missing" else "INVALID_HANDOFF")
