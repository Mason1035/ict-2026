from dataclasses import replace

from ai_training.artifacts.manifest import load_manifest
from ai_training.training.reproducibility import read_json


class TestOnlyStopAfterOne:
    """TEST_ONLY policy; not a project early stopping recommendation."""
    implementation_id = "TEST_ONLY.stop_after_one"

    def should_stop(self, history):
        return len(history) == 1


def test_injected_early_stopping_records_actual_termination(case, toy, tmp_path):
    c, d, cfg = case
    policy = TestOnlyStopAfterOne()
    path = toy.run_case(tmp_path, case=(c, d, replace(cfg, early_stopping_id=policy.implementation_id)), early_stopping=policy)
    manifest = load_manifest(path)
    assert manifest["execution_status"] == "TEST_ONLY_EARLY_STOPPED"
    assert manifest["stop_reason"] == "INJECTED_EARLY_STOPPING"
    payload = read_json(path / "checkpoints/last.json")["payload"]
    assert payload["state"]["epoch"] == 1
    assert payload["state"]["metrics"] == payload["best_state"]["metrics"]
