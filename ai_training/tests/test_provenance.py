from dataclasses import replace
import csv
import hashlib
import json
import pytest

from ai_training.adapters.synthetic import SyntheticAdapter
from ai_training.datasets.provenance import Provenance
from ai_training.errors import IntegrityError
from ai_training.training.reproducibility import file_hash


def test_provenance_preserves_sources_without_inventing_real_fields(case):
    p = case[1].samples[0].provenance
    assert p.source_type == "SYNTHETIC" and p.generator_version == "TEST_ONLY.toy.v1"
    assert p.row_indices == (0, 1, 2) and p.parent_run is None
    real = Provenance("REAL", "TEST_ONLY.real-interface-placeholder", (0,))
    assert real.device_id is real.boot_id is real.calibration_version is None
    assert real.source_type != p.source_type
    assert replace(p, parent_run="TEST_ONLY.parent").to_dict()["parent_run"] == "TEST_ONLY.parent"


def observation_fixture(root):
    """TEST_ONLY / NOT_REAL_DATA / NOT_PROJECT_TRAINING_DATA artifact envelope."""
    config = {"purpose": "TEST_ONLY", "seed": 17, "note": "测试"}
    parameter_hash = hashlib.sha256(json.dumps(config, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    row = {"run_id": f"sim_{parameter_hash}", "row_index": 0, "is_synthetic": True,
           "generator_version": "0.1.1", "seed": 17, "parameter_hash": parameter_hash, "parent_run": ""}
    with (root / "simulation.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)
    meta = row | {"parent_run": None, "config": config, "artifact_kind": "simulator_observation_csv",
                  "observation_schema_version": "physics_sim.observation.v0.1.1",
                  "contract_status": "PRE_B_TRAINING_CONTRACT", "row_count": 1,
                  "csv_sha256": file_hash(root / "simulation.csv"),
                  "declarations": ["TEST_ONLY", "NOT_REAL_DATA", "NOT_PROJECT_TRAINING_DATA"]}
    (root / "metadata.json").write_text(json.dumps(meta))
    return meta


def test_synthetic_inspection_only_preserves_identity(tmp_path):
    meta = observation_fixture(tmp_path)
    rows = SyntheticAdapter().inspect(tmp_path)
    assert rows[0].run_id == meta["run_id"] and rows[0].row_indices == (0,)
    assert rows[0].parameter_hash == meta["parameter_hash"] and rows[0].seed == 17
    assert rows[0].dataset_version is rows[0].feature_version is rows[0].split is None


@pytest.mark.parametrize("change", ["hash", "schema", "status", "identity", "rows"])
def test_synthetic_inspection_rejects_inconsistent_artifacts(tmp_path, change):
    meta = observation_fixture(tmp_path)
    edits = {"hash": {"csv_sha256": "0" * 64}, "schema": {"observation_schema_version": "unknown"},
             "status": {"contract_status": "TRAINING_READY"}, "identity": {"run_id": "other"},
             "rows": {"row_count": 2}}
    (tmp_path / "metadata.json").write_text(json.dumps(meta | edits[change]))
    with pytest.raises(IntegrityError):
        SyntheticAdapter().inspect(tmp_path)
