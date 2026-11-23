"""Audit identities are kept outside model inputs; real details stay nullable."""

from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class Provenance:
    source_type: str
    run_id: str
    row_indices: tuple[int, ...]
    parent_run: str | None = None
    dataset_version: str | None = None
    feature_version: str | None = None
    split: str | None = None
    generator_version: str | None = None
    seed: int | None = None
    parameter_hash: str | None = None
    device_id: str | None = None
    boot_id: int | None = None
    seq: int | None = None
    calibration_version: str | None = None
    source_artifact_hash: str | None = None

    def to_dict(self):
        return asdict(self)
