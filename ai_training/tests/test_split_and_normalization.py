from dataclasses import replace
import pytest
import numpy as np

from ai_training.contracts.schemas import SplitAssignment, SplitManifest
from ai_training.contracts.validation import validate_no_group_leakage
from ai_training.datasets.normalization import fit_train_only, save_normalizer, load_normalizer, transform_checked
from ai_training.evaluation.evaluator import Evaluator
from ai_training.errors import LeakageError, ContractNotReadyError


def manifest(*assignments):
    return SplitManifest("TEST_ONLY.v1", "TEST_ONLY.dataset.v1", assignments)


@pytest.mark.parametrize("assignments", [
    (SplitAssignment("a", "train", "REAL"), SplitAssignment("a", "test", "REAL")),
    (SplitAssignment("a", "train", "REAL"), SplitAssignment("b", "test", "SYNTHETIC", "a")),
    (SplitAssignment("a", "train", "REAL"), SplitAssignment("b", "train", "SYNTHETIC", "a"), SplitAssignment("c", "test", "SYNTHETIC", "b")),
    (SplitAssignment("a", "train", "REAL", group_id="g"), SplitAssignment("b", "test", "REAL", group_id="g")),
    (SplitAssignment("a", "train", "SYNTHETIC", "b"), SplitAssignment("b", "train", "SYNTHETIC", "a")),
])
def test_group_leakage_and_cycles(assignments):
    with pytest.raises(LeakageError):
        validate_no_group_leakage(manifest(*assignments))


def test_missing_manifest_and_missing_parent_rejected():
    with pytest.raises(ContractNotReadyError):
        validate_no_group_leakage(None)
    with pytest.raises(ContractNotReadyError, match="parent_run"):
        validate_no_group_leakage(manifest(SplitAssignment("child", "train", "SYNTHETIC", "missing")))


def test_related_real_synthetic_runs_can_share_split():
    result = validate_no_group_leakage(manifest(SplitAssignment("a", "train", "REAL"),
                                               SplitAssignment("b", "train", "SYNTHETIC", "a")))
    assert result["b"].parent_run == "a"


def test_test_and_validation_cannot_fit_normalizer(case, toy):
    c, d, _ = case
    for s in d.samples[-2:]:
        n = toy.IdentityNormalizer()
        with pytest.raises(LeakageError):
            fit_train_only(n, (s,), c)
        assert n.fit_count == 0
    test = d.samples[-1]
    with pytest.raises(LeakageError):
        fit_train_only(toy.IdentityNormalizer(), (replace(test, provenance=replace(test.provenance, split="train")),), c)


def test_normalizer_roundtrip_and_nonfinite_transform(case, toy, tmp_path):
    c, d, _ = case
    normalizer = toy.IdentityNormalizer()
    fit_train_only(normalizer, d.training_partition("train"), c)
    path = tmp_path / "normalizer.json"
    save_normalizer(path, normalizer, {"test": "identity"})
    restored = toy.IdentityNormalizer()
    load_normalizer(path, restored, {"test": "identity"})
    assert restored.state_dict() == normalizer.state_dict()
    np.testing.assert_array_equal(transform_checked(restored, d.samples[0], c), d.samples[0].X)
    restored.transform = lambda X, mask: X * np.nan
    with pytest.raises(ContractNotReadyError, match="non-finite"):
        transform_checked(restored, d.samples[0], c)


def test_test_sealed_and_evaluator_requires_contract_metrics(case, toy):
    c, d, _ = case
    with pytest.raises(LeakageError, match="sealed"):
        d.training_partition("test")
    ev = Evaluator()
    n = toy.IdentityNormalizer()
    fit_train_only(n, d.training_partition("train"), c)
    model = toy.TinyModel(np.random.default_rng(1), {"input_features": 2})
    with pytest.raises(ContractNotReadyError):
        ev.evaluate(None, d.samples[-2:-1], model, n, {})
    with pytest.raises(ContractNotReadyError, match="Metrics Contract"):
        ev.evaluate(c, d.samples[-2:-1], model, n, {}, test_only=True)
    with pytest.raises(LeakageError, match="sealed"):
        ev.evaluate(c, d.samples[-1:], model, n, {"TEST_ONLY.mse": toy.ToyMetric()}, test_only=True)
