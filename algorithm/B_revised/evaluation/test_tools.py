"""评价与 Train-only 数据边界；所有数据是软件 TEST_ONLY 夹具。"""
import copy
import unittest

from evaluation.metrics import classification_report, event_report, precision_recall_curve
from evaluation.normalization import fit_real_train, transform


def row(run, split, value, *, parent=None, synthetic=False, valid=True):
    return {"run_id": run, "parent_run": parent, "split": split, "is_synthetic": synthetic,
            "values": {"test_feature": value}, "valid": {"test_feature": valid}}


class NormalizationTests(unittest.TestCase):
    def test_only_real_train_changes_statistics(self):
        rows = [row("r1", "train", 0), row("r1", "train", 2), row("r1", "train", None, valid=False),
                row("r2", "validation", 900), row("r3", "test", -900),
                row("s1", "train", 9000, parent="r1", synthetic=True)]
        scaler = fit_real_train(rows, ordered_features=["test_feature"])
        self.assertEqual(scaler["statistics"]["test_feature"]["mean"], 1)
        self.assertEqual(scaler["statistics"]["test_feature"]["scale"], 1)
        self.assertEqual(transform(rows[0], scaler)["values"], [-1])
        self.assertEqual(transform(rows[2], scaler)["values"], [None])
        self.assertEqual(scaler["fit_runs"], ["r1"])
        self.assertFalse(scaler["formal_training_ready"])

    def test_same_parent_cannot_cross_split(self):
        with self.assertRaises(ValueError):
            fit_real_train([row("r1", "train", 1), row("r2", "test", 2, parent="r1")],
                           ordered_features=["test_feature"])

    def test_no_train_or_all_missing_or_wrong_mask_rejected(self):
        for rows in ([row("r1", "test", 1)], [row("r1", "train", None, valid=False)],
                     [row("r1", "train", None)], [row("r1", "train", True)]):
            with self.assertRaises(ValueError):
                fit_real_train(rows, ordered_features=["test_feature"])

    def test_forbidden_features_and_tampering(self):
        for name in ("run_id", "timestamp_ms", "future_label", "sensor_score"):
            with self.assertRaises(ValueError):
                fit_real_train([], ordered_features=[name])
        rows = [row("r1", "train", 5)]
        scaler = fit_real_train(rows, ordered_features=["test_feature"])
        self.assertTrue(scaler["statistics"]["test_feature"]["constant"])
        self.assertEqual(transform(rows[0], scaler)["values"], [0])
        scaler["statistics"]["test_feature"]["mean"] = 99
        with self.assertRaises(ValueError):
            transform(rows[0], scaler)


class MetricTests(unittest.TestCase):
    def test_unscored_is_not_excluded_from_recall(self):
        r = classification_report(["N", "S", "S", None], ["N", None, "N", "S"], labels=["N", "S"])
        self.assertEqual(r["confusion_matrix"], [[1, 0, 0], [1, 0, 1]])
        self.assertEqual(r["per_class"]["S"]["fn"], 2)
        self.assertEqual(r["coverage"], 2 / 3)
        self.assertEqual(r["accuracy_including_unscored"], 1 / 3)
        self.assertEqual(r["accuracy_on_scored_only"], .5)
        self.assertEqual(r["excluded_unknown_truth"], 1)

    def test_empty_or_missing_classes_are_undefined(self):
        r = classification_report([], [], labels=["N", "S"])
        self.assertIsNone(r["macro_f1"])
        self.assertIsNone(r["coverage"])
        with self.assertRaises(ValueError):
            classification_report(["N"], ["fake"], labels=["N"])

    def test_tied_pr_and_missing_positive(self):
        r = precision_recall_curve([1, 0, 1, 0], [.9, .9, None, .2])
        self.assertEqual(r["points"][0], {"threshold": .9, "precision": .5, "recall": .5})
        self.assertEqual(r["average_precision_including_unscored_positives"], .25)
        self.assertEqual(r["unscored"], 1)
        self.assertIsNone(precision_recall_curve([0], [1])["average_precision_including_unscored_positives"])

    def test_event_match_is_one_to_one_and_signed(self):
        def item(i, t):
            return {"id": i, "run_id": "r", "boot_id": 1, "time_ms": t}
        events = [item("e1", 1000), item("e2", 1100)]
        alarms = [item("a1", 900), item("a2", 1150), item("a3", 3000)]
        r = event_report(events, alarms, observation_intervals=[
            {"run_id": "r", "boot_id": 1, "start_ms": 0, "end_ms": 3_600_000}],
            early_window_ms=300, late_window_ms=100)
        self.assertEqual([v["lead_time_ms"] for v in r["matches"]], [100, -50])
        self.assertEqual(r["false_alarms_per_hour"], 1)
        self.assertEqual(r["event_recall"], 1)

    def test_event_windows_do_not_cross_gaps(self):
        event = {"id": "e", "run_id": "r", "boot_id": 1, "time_ms": 2100}
        alarm = {"id": "a", "run_id": "r", "boot_id": 1, "time_ms": 900}
        intervals = [{"run_id": "r", "boot_id": 1, "start_ms": 0, "end_ms": 1000},
                     {"run_id": "r", "boot_id": 1, "start_ms": 2000, "end_ms": 3000}]
        r = event_report([event], [alarm], observation_intervals=intervals,
                         early_window_ms=2000, late_window_ms=0)
        self.assertEqual(r["event_recall"], 0)
        self.assertEqual(r["observation_hours"], 2000 / 3_600_000)
        bad = copy.deepcopy(intervals)
        bad[1]["start_ms"] = 900
        with self.assertRaises(ValueError):
            event_report([], [], observation_intervals=bad, early_window_ms=0, late_window_ms=0)
