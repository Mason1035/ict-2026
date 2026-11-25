"""仅用合成的内存/临时测试行验证 CSV 初检边界。"""

import csv
import tempfile
import unittest
from pathlib import Path

from data_intake.check_experiment_csv import HEADER, inspect_csv


class IntakeChecks(unittest.TestCase):
    def make_csv(self, rows):
        temp = tempfile.TemporaryDirectory()
        path = Path(temp.name) / "TEST_ONLY.csv"
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(HEADER)
            writer.writerows(rows)
        self.addCleanup(temp.cleanup)
        return path

    def row(self, ts, soil="", label="NORMAL"):
        record = {field: "" for field in HEADER}
        record.update(run_id="run_TEST_ONLY", timestamp_ms=ts, soil_top_raw=soil, label=label)
        return [record[field] for field in HEADER]

    def test_blank_is_missing_but_zero_is_observed(self):
        report = inspect_csv(self.make_csv([self.row(1000, ""), self.row(1100, "0")]))
        self.assertEqual(report["status"], "CSV_CHECKED")
        self.assertEqual(report["missing_count"]["soil_top_raw"], 1)
        self.assertEqual(report["runs"]["run_TEST_ONLY"]["channels"]["soil_top_raw"],
                         {"observed": 1, "missing": 1, "min": 0.0, "max": 0.0})

    def test_time_reversal_and_duplicate_are_reported(self):
        report = inspect_csv(self.make_csv([self.row(1000), self.row(900), self.row(900)]))
        self.assertEqual(report["status"], "REVIEW_REQUIRED")
        self.assertEqual(report["runs"]["run_TEST_ONLY"]["time_reversals"], 1)
        self.assertEqual(report["runs"]["run_TEST_ONLY"]["duplicate_timestamps"], 1)

    def test_invalid_label_and_integer_are_reported(self):
        report = inspect_csv(self.make_csv([self.row("1000.0", label="WARNING")]))
        self.assertEqual(report["status"], "REVIEW_REQUIRED")
        self.assertEqual({x["code"] for x in report["issues"]}, {"INVALID_LABEL", "INVALID_NUMBER"})


if __name__ == "__main__":
    unittest.main()
