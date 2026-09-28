import unittest

from evaluation.split_preflight import audit_split_plan


def item(run_id, parent, split, synthetic=False):
    return {"run_id": run_id, "parent_run": parent, "split": split, "is_synthetic": synthetic}


class SplitPreflightTests(unittest.TestCase):
    def test_empty_plan_requires_review(self):
        result = audit_split_plan([])
        self.assertEqual(result["status"], "REVIEW_REQUIRED")
        self.assertIn("EMPTY_PLAN", {issue["code"] for issue in result["issues"]})

    def test_independent_real_test_and_train_synthetic_are_structural_only(self):
        result = audit_split_plan([
            item("real_a", None, "train"), item("aug_a", "real_a", "train", True),
            item("real_b", None, "validation"), item("real_c", None, "test")])
        self.assertEqual(result["status"], "STRUCTURE_CHECKED_ONLY")
        self.assertEqual(result["real_test_groups"], ["real_c"])
        self.assertFalse(result["formal_training_ready"])

    def test_parent_group_cannot_cross_splits(self):
        result = audit_split_plan([item("real_a", None, "train"), item("derived_a", "real_a", "test")])
        self.assertIn("PARENT_GROUP_LEAKAGE", {issue["code"] for issue in result["issues"]})

    def test_synthetic_requires_real_train_parent(self):
        result = audit_split_plan([item("synthetic_a", "missing", "train", True)])
        self.assertIn("SYNTHETIC_PARENT_NOT_REAL_TRAIN", {issue["code"] for issue in result["issues"]})

    def test_synthetic_never_in_validation_or_test(self):
        result = audit_split_plan([item("real_a", None, "test"), item("synthetic_a", "real_a", "test", True)])
        self.assertIn("SYNTHETIC_OUTSIDE_TRAIN", {issue["code"] for issue in result["issues"]})

    def test_duplicate_run_is_rejected(self):
        result = audit_split_plan([item("real_a", None, "train"), item("real_a", None, "train")])
        self.assertIn("DUPLICATE_RUN_ID", {issue["code"] for issue in result["issues"]})

    def test_malformed_split_is_reported_without_exception(self):
        result = audit_split_plan([item("real_a", None, {}, False)])
        self.assertIn("INVALID_SPLIT_OR_SOURCE", {issue["code"] for issue in result["issues"]})


if __name__ == "__main__":
    unittest.main()
