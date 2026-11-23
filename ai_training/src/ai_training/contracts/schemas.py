"""C-side envelope proposal, not B's approved scientific contract."""

from dataclasses import dataclass, asdict
from typing import Any


@dataclass(frozen=True)
class SplitAssignment:
    run_id: str
    split: str
    source_type: str
    parent_run: str | None = None
    group_id: str | None = None


@dataclass(frozen=True)
class SplitManifest:
    version: str
    dataset_version: str
    assignments: tuple[SplitAssignment, ...]

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class TrainingContract:
    schema_version: str | None = None
    contract_version: str | None = None
    status: str = "WAITING_FOR_B"
    declarations: tuple[str, ...] = ()
    approved_by: str | None = None
    feature_version: str | None = None
    ordered_features: tuple[str, ...] | None = None
    feature_units: dict | None = None
    feature_sources: dict | None = None
    feature_lookahead_s: dict | None = None
    dtype: str | None = None
    mask_semantics: dict | None = None
    coordinate_semantics: str | None = None
    sampling_alignment: dict | None = None
    window: dict | None = None
    label: dict | None = None
    split_manifest: SplitManifest | None = None
    normalization: dict | None = None
    metrics: tuple[str, ...] | None = None
    synthetic_constraints: dict | None = None
    nonfinite_policy: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
