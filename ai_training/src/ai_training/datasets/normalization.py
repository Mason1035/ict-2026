"""Train-only fitting wrapper; there is no project default normalizer."""

from typing import Protocol
import numpy as np

from ai_training.contracts.validation import validate_no_group_leakage, require
from ai_training.errors import LeakageError
from ai_training.training.reproducibility import write_json_exclusive, read_json, content_hash


class NormalizerProtocol(Protocol):
    implementation_id: str
    def fit(self, inputs): ...
    def transform(self, X, mask): ...
    def state_dict(self) -> dict: ...
    def load_state_dict(self, state: dict): ...


def transform_checked(normalizer, sample, contract):
    require(normalizer.implementation_id == contract.normalization["implementation"], "normalizer implementation mismatch")
    X = normalizer.transform(sample.X.copy(), sample.mask.copy())
    require(isinstance(X, np.ndarray) and X.shape == sample.X.shape
            and str(X.dtype) == contract.dtype and np.isfinite(X).all(),
            "normalizer produced invalid shape/dtype/non-finite inputs; fix the injected implementation")
    return X


def fit_train_only(normalizer, samples, contract):
    samples = tuple(samples)
    require(bool(samples), "normalizer requires Train samples")
    runs = validate_no_group_leakage(contract.split_manifest)
    require(normalizer.implementation_id == contract.normalization["implementation"], "normalizer implementation differs from contract")
    for sample in samples:
        sample.validate(contract)
        p = sample.provenance
        # Both provenance AND manifest must say Train; relabeling a Test sample
        # locally must never authorize fitting on held-out values.
        if (p.split != "train" or p.run_id not in runs or runs[p.run_id].split != "train"
                or (p.source_type, p.parent_run) != (runs[p.run_id].source_type, runs[p.run_id].parent_run)):
            raise LeakageError("normalizer fit received non-Train data; use only B-manifest Train runs")
    normalizer.fit(tuple((s.X.copy(), s.mask.copy()) for s in samples))


def save_normalizer(path, normalizer, identity):
    payload = {"normalizer_version": normalizer.implementation_id,
               "identity": identity, "state": normalizer.state_dict()}
    return write_json_exclusive(path, {"payload": payload, "content_hash": content_hash(payload)})


def load_normalizer(path, normalizer, identity):
    envelope = read_json(path)
    payload = envelope["payload"]
    require(content_hash(payload) == envelope["content_hash"], "normalizer artifact hash mismatch")
    require(payload["identity"] == identity and payload["normalizer_version"] == normalizer.implementation_id,
            "normalizer identity mismatch")
    normalizer.load_state_dict(payload["state"])
