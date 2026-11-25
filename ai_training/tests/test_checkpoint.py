from copy import deepcopy
import json
import pytest

from ai_training.artifacts.manifest import load_manifest
from ai_training.errors import IntegrityError, ContractNotReadyError
from ai_training.training.checkpoint import load_checkpoint
from ai_training.training.reproducibility import file_hash, read_json


def test_checkpoint_resume_matches_uninterrupted_run(case, toy, tmp_path):
    full = toy.run_case(tmp_path / "full", case=case)
    partial = toy.run_case(tmp_path / "partial", case=case, stop_after_epoch=2)
    checkpoint = partial / "checkpoints/last.json"
    resumed = toy.run_case(tmp_path / "resumed", case=case, resume=checkpoint, resume_hash=file_hash(checkpoint))
    for relative in ("checkpoints/last.json", "checkpoints/best.json", "training_log.csv", "evaluation/metrics.json", "preprocessing/normalizer.json"):
        assert (full / relative).read_bytes() == (resumed / relative).read_bytes()
    mf = load_manifest(resumed)
    assert mf["resumed_from_checkpoint_hash"] == file_hash(checkpoint)
    payload = load_checkpoint(resumed / "checkpoints/last.json", mf["identity"], expected_hash=mf["checkpoint_hash"])
    assert payload["state"]["epoch"] == 4 and payload["state"]["step"] == 8
    assert payload["state"]["normalizer"]["fit_count"] == 1


@pytest.mark.parametrize("key", ["dataset_hash", "contract_hash", "split_manifest_hash", "training_seed", "source_tree_hash"])
def test_incompatible_checkpoint_identity_rejected(toy, tmp_path, key):
    directory = toy.run_case(tmp_path)
    identity = deepcopy(load_manifest(directory)["identity"])
    identity[key] = "changed"
    with pytest.raises(IntegrityError, match="incompatible"):
        load_checkpoint(directory / "checkpoints/last.json", identity)


def test_checkpoint_corruption_and_invalid_resume_position(toy, tmp_path):
    directory = toy.run_case(tmp_path / "partial", stop_after_epoch=2)
    path = directory / "checkpoints/last.json"
    identity = load_manifest(directory)["identity"]
    with pytest.raises(IntegrityError, match="file hash"):
        load_checkpoint(path, identity, expected_hash="0" * 64)
    with pytest.raises(ContractNotReadyError, match="interruption epoch"):
        toy.run_case(tmp_path / "bad-resume", resume=path, stop_after_epoch=1)
    envelope = read_json(path)
    envelope["payload"]["state"]["model"] = {"weights": [999., 999.]}
    path.write_text(json.dumps(envelope))
    with pytest.raises(IntegrityError, match="content hash"):
        load_checkpoint(path, identity)
