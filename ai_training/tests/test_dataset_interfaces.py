from dataclasses import replace
import numpy as np
import pytest

from ai_training.errors import ContractNotReadyError, LeakageError


def test_sample_separates_inputs_mask_label_provenance(case):
    contract, dataset, _ = case
    dataset.validate(contract, test_only=True)
    s = dataset.samples[0]
    assert s.X.shape == s.mask.shape == (3, 2)
    assert s.feature_names == ("toy_a", "toy_b")
    assert s.provenance.seed == 17 and s.provenance.run_id == "toy_train"
    np.testing.assert_array_equal(s.X[:, 0], s.times / 10)
    assert s.y == 0.4
    assert "seed" not in s.feature_names and "failure_time_s" not in s.feature_names


@pytest.mark.parametrize("change", ["order", "dtype", "nan", "inf", "mask", "gap", "shape"])
def test_sample_rejects_invalid_inputs(case, change):
    c, d, _ = case
    s = d.samples[0]
    changes = {
        "order": {"feature_names": tuple(reversed(s.feature_names))},
        "dtype": {"X": s.X.astype(np.float32)}, "nan": {"X": np.full(s.X.shape, np.nan)},
        "inf": {"X": np.full(s.X.shape, np.inf)}, "mask": {"mask": np.full(s.X.shape, "?")},
        "gap": {"times": np.array([0., 0., 2.])}, "shape": {"X": s.X[:2]},
    }
    with pytest.raises(ContractNotReadyError):
        replace(s, **changes[change]).validate(c)


def test_dataset_requires_version_and_manifest_consistency(case):
    c, d, _ = case
    with pytest.raises(ContractNotReadyError, match="dataset version"):
        replace(d, version="").validate(c, test_only=True)
    s = d.samples[-1]
    forged = replace(s, provenance=replace(s.provenance, split="train"))
    with pytest.raises(LeakageError, match="disagrees"):
        replace(d, samples=d.samples[:-1] + (forged,)).validate(c, test_only=True)
    with pytest.raises(ContractNotReadyError, match="duplicate"):
        replace(d, samples=d.samples + (d.samples[0],)).validate(c, test_only=True)
