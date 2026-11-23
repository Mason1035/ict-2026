"""Generic [time, feature] container; dimensions and semantics are external."""

from dataclasses import dataclass
from typing import Any

import numpy as np

from ai_training.contracts.validation import require, validate_feature_name
from ai_training.errors import LeakageError
from .provenance import Provenance


@dataclass(frozen=True)
class TrainingSample:
    X: np.ndarray
    mask: np.ndarray
    y: Any
    provenance: Provenance
    feature_names: tuple[str, ...]
    times: np.ndarray
    available_at: np.ndarray
    decision_time: float

    def validate(self, contract):
        # Matching counts is insufficient: a reordered feature matrix changes
        # model meaning. Never select all numeric CSV columns automatically.
        require(self.feature_names == contract.ordered_features, "sample feature order differs from contract")
        for name in self.feature_names:
            validate_feature_name(name)
        require(isinstance(self.X, np.ndarray) and self.X.ndim == 2, "X must have [time, feature] rank")
        require(self.X.shape == (contract.window["length"], len(self.feature_names)), "sample shape violates external window/order")
        require(str(self.X.dtype) == contract.dtype, "sample dtype differs from contract")
        require(self.mask.shape == self.X.shape and np.isin(self.mask, list(contract.mask_semantics)).all(), "invalid mask shape/code")
        require(np.isfinite(self.X).all(), "non-finite X; current executor supports explicit reject policy only")
        require(self.times.shape == (len(self.X),) and np.isfinite(self.times).all(), "invalid sample time axis")
        require(self.available_at.shape == self.X.shape and np.isfinite(self.available_at).all(), "missing input availability evidence")
        require(np.isfinite(self.decision_time), "invalid decision time")
        if (self.times > self.decision_time).any() or (self.available_at > self.decision_time).any():
            raise LeakageError("future input availability exceeds decision time; rebuild a causal window")
        require((np.diff(self.times) == contract.sampling_alignment["dt"]).all(), "gap/alignment violates test contract")
        require((self.available_at >= self.times[:, None]).all(), "availability predates source observation")
        require(type(self.y) in (int, float) and np.isfinite(self.y), "unsupported/non-finite test label")
        p = self.provenance
        require(isinstance(p, Provenance) and p.source_type in ("REAL", "SYNTHETIC"), "missing/unknown provenance source")
        require(bool(p.run_id) and len(p.row_indices) == len(self.X), "missing row/window source information")
        require(all(type(i) is int and i >= 0 for i in p.row_indices)
                and all(b > a for a, b in zip(p.row_indices, p.row_indices[1:])), "source rows must increase without duplicates")
        require(p.feature_version == contract.feature_version, "sample feature version mismatch")
        require(p.dataset_version == contract.split_manifest.dataset_version, "sample dataset version mismatch")
        if p.source_type == "SYNTHETIC":
            require(bool(p.generator_version) and type(p.seed) is int and p.seed >= 0
                    and isinstance(p.parameter_hash, str) and len(p.parameter_hash) == 64, "synthetic lineage incomplete")
        return self

    def to_dict(self):
        return {"X": self.X.tolist(), "mask": self.mask.tolist(), "y": self.y,
                "feature_names": self.feature_names, "times": self.times.tolist(),
                "available_at": self.available_at.tolist(), "decision_time": self.decision_time,
                "provenance": self.provenance.to_dict()}


def from_columns(columns, *, contract, mask, y, provenance, times, available_at, decision_time):
    """Explicit selection only; callers supply labels and lineage separately."""
    names = contract.ordered_features
    require(names is not None, "ordered_features missing")
    for name in names:
        validate_feature_name(name)
        require(name in columns, f"input feature {name!r} missing")
    X = np.column_stack([columns[name] for name in names])
    sample = TrainingSample(X, np.asarray(mask), y, provenance, names,
                            np.asarray(times), np.asarray(available_at), decision_time)
    return sample.validate(contract)
