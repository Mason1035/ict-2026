from dataclasses import replace
import numpy as np
import pytest

from ai_training.artifacts.manifest import load_manifest, manifest_hash
from ai_training.training.reproducibility import content_hash, read_json, seeded_rng


def test_config_and_manifest_hash_ignore_only_audit_time():
    assert content_hash({"a": 1, "b": [2, 3]}) == content_hash({"b": [2, 3], "a": 1})
    assert content_hash([2, 3]) != content_hash([3, 2])
    a = {"identity": {"seed": 1}, "started_at": "earlier", "ended_at": "earlier"}
    b = dict(a, started_at="later", ended_at="later")
    assert manifest_hash(a) == manifest_hash(b)
    assert manifest_hash(a) != manifest_hash(dict(a, identity={"seed": 2}))
    with pytest.raises(ValueError):
        content_hash({"invalid": np.nan})


def test_rng_is_explicit_and_reproducible():
    np.testing.assert_array_equal(seeded_rng(17).normal(size=10), seeded_rng(17).normal(size=10))
    for seed in (None, -1, True, 1.5):
        with pytest.raises(ValueError):
            seeded_rng(seed)


def test_test_only_run_is_bitwise_repeatable(toy, tmp_path):
    a = toy.run_case(tmp_path / "a")
    b = toy.run_case(tmp_path / "b")
    ma, mb = load_manifest(a), load_manifest(b)
    assert a.name == b.name
    assert ma["manifest_hash"] == mb["manifest_hash"]
    assert ma["artifact_hashes"] == mb["artifact_hashes"]
    for name in ma["artifact_hashes"]:
        assert (a / name).read_bytes() == (b / name).read_bytes()


def test_test_labels_do_not_change_training_decisions(case, toy, tmp_path):
    c, d, config = case
    altered = replace(d, samples=d.samples[:-1] + (replace(d.samples[-1], y=99999.),))
    a = toy.run_case(tmp_path / "original", case=case)
    b = toy.run_case(tmp_path / "changed-test", case=(c, altered, config))
    # Whole-dataset integrity identity changes, but no optimizer/selection state
    # may depend on the sealed Test target.
    pa = read_json(a / "checkpoints/last.json")["payload"]
    pb = read_json(b / "checkpoints/last.json")["payload"]
    assert pa["identity"]["dataset_hash"] != pb["identity"]["dataset_hash"]
    assert pa["state"] == pb["state"] and pa["best_state"] == pb["best_state"]
