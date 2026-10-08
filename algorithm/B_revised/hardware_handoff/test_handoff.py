import json
import unittest
from pathlib import Path

from hardware_handoff.run_vectors import check_vectors


class HardwareHandoffTests(unittest.TestCase):
    def test_all_test_only_vectors_match_reference(self):
        count, errors = check_vectors()
        self.assertEqual(count, 26)
        self.assertEqual(errors, [])

    def test_draft_config_is_unloadable_and_unresolved(self):
        path = Path(__file__).with_name("RISK_CONFIG_DRAFT_NOT_LOADABLE.json")
        config = json.loads(path.read_text(encoding="utf-8"))
        self.assertFalse(config["loadable_on_device"])
        self.assertTrue(all(value is None for value in config["todo_calibration"].values()))
        self.assertTrue(all(value is None for value in config["tbd_interface_review"].values()))


if __name__ == "__main__":
    unittest.main()
