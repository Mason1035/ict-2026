"""Canonical pre-windowed data interface; window construction remains with B."""

from dataclasses import dataclass
from typing import Protocol

from ai_training.contracts.validation import validate_contract, validate_no_group_leakage, require
from ai_training.errors import LeakageError
from ai_training.training.reproducibility import content_hash
from .sample import TrainingSample


class WindowBuilder(Protocol):
    def build(self, artifact, contract) -> tuple[TrainingSample, ...]: ...


@dataclass(frozen=True)
class CanonicalDataset:
    version: str
    samples: tuple[TrainingSample, ...]
    declarations: tuple[str, ...]

    def validate(self, contract, *, test_only=False):
        validate_contract(contract, test_only=test_only)
        require(self.version == contract.split_manifest.dataset_version, "dataset version missing/mismatched")
        require(bool(self.samples), "dataset empty")
        if test_only:
            require(set(self.declarations) == {"TEST_ONLY", "NOT_REAL_DATA", "NOT_PROJECT_TRAINING_DATA"}, "test dataset not isolated")
        runs = validate_no_group_leakage(contract.split_manifest)
        seen = set()
        for sample in self.samples:
            sample.validate(contract)
            p = sample.provenance
            require(p.run_id in runs, "sample run absent from Split Manifest")
            entry = runs[p.run_id]
            if (p.split, p.parent_run, p.source_type) != (entry.split, entry.parent_run, entry.source_type):
                raise LeakageError("sample provenance disagrees with Split Manifest; fix assignment before use")
            require(p.source_type in contract.synthetic_constraints["allowed_sources"], "source forbidden by synthetic constraints")
            key = (p.run_id, p.row_indices)
            require(key not in seen, "duplicate source window; do not count replay artifacts as new samples")
            seen.add(key)
        return self

    def training_partition(self, split):
        # Test sealing is an API boundary, not a claim that Python objects are a
        # security sandbox. Trainer/normalizer/evaluator never request Test data.
        if split not in ("train", "validation"):
            raise LeakageError("Test is sealed; final evaluation release requires B's future protocol")
        return tuple(s for s in self.samples if s.provenance.split == split)

    def content_hash(self):
        return content_hash({"version": self.version, "declarations": self.declarations,
                             "samples": [s.to_dict() for s in self.samples]})
