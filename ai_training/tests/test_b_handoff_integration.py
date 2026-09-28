"""TEST_ONLY / NOT_REAL_DATA / NOT_PROJECT_TRAINING_DATA integration evidence."""

import csv
from dataclasses import replace
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import numpy as np
import pytest

from ai_training.adapters.b_rule_fixture import BRuleFixtureReader
from ai_training.contracts.b_handoff import inspect_b_contract, FORMAL_BLOCKED
from ai_training.contracts.validation import load_training_contract, validate_contract
from ai_training.errors import ContractNotReadyError, FormalTrainingNotAllowedError, IntegrityError, LeakageError
from ai_training.training.reproducibility import file_hash, read_json

ROOT = Path(__file__).resolve().parents[2]
B_ROOT = ROOT / "team_handoffs/B_revised"
ARTIFACT = B_ROOT / "artifacts/rule_distillation_demo"
FORMAL = B_ROOT / "contracts/B_FORMAL_TRAINING_CONTRACT_DRAFT.json"


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def rehash(directory, name):
    manifest = read_json(directory / "manifest.json")
    manifest["file_hashes"][name] = file_hash(directory / name)
    write(directory / "manifest.json", manifest)


@pytest.fixture
def copied(tmp_path):
    return Path(shutil.copytree(ARTIFACT, tmp_path / "fixture"))


def test_reader_preserves_B_order_labels_and_nullable_provenance():
    fixture = BRuleFixtureReader(B_ROOT).read(ARTIFACT, purpose="TEST_ONLY")
    contract = read_json(ARTIFACT / "contract.json")
    X, y, provenance = fixture.partition("train", purpose="TEST_ONLY")
    assert fixture.feature_names == tuple(contract["model_features"])
    assert X.shape == (126, 4) and y.shape == (126,)
    with (ARTIFACT / "dataset_all.csv").open(encoding="utf-8-sig") as stream:
        rows = [r for r in csv.DictReader(stream) if r["split"] == "train"]
    np.testing.assert_array_equal(X, [[float(r[n]) for n in fixture.feature_names] for r in rows])
    np.testing.assert_array_equal(y, [contract["label_mapping"][r["teacher_risk_level"]] for r in rows])
    assert fixture.dataset_role == "TEST_ONLY" and fixture.formal_training_dataset is False
    assert fixture.row_counts["excluded_unknown"] == 18
    assert set(fixture.feature_names).isdisjoint(contract["forbidden_model_features"])
    p = provenance[0]
    assert p["source_type"] == "SYNTHETIC" and p["synthetic_source"] == "b_rule_distillation_fixture"
    assert p["generator_seed"] == 20260925 and p["source_csv_hash"] == file_hash(ARTIFACT / "dataset_all.csv")
    assert all(p[k] is None for k in ("run_id", "parent_run", "parameter_hash", "scenario", "dataset_version", "feature_version"))
    with pytest.raises(TypeError):
        p["split"] = "test"
    X[:] = 999
    assert not np.any(fixture.partition("train", purpose="TEST_ONLY")[0] == 999)


def test_repeat_identity_independent_of_location_and_clock(copied, monkeypatch):
    import time
    a = BRuleFixtureReader(B_ROOT).read(ARTIFACT, purpose="TEST_ONLY")
    monkeypatch.setattr(time, "time", lambda: 0)
    b = BRuleFixtureReader(B_ROOT).read(copied, purpose="TEST_ONLY")
    assert a.fingerprint == b.fingerprint
    np.testing.assert_array_equal(a.partition("validation", purpose="TEST_ONLY")[0],
                                  b.partition("validation", purpose="TEST_ONLY")[0])


def test_formal_use_rejected_before_reading_and_test_is_sealed():
    reader = BRuleFixtureReader(B_ROOT)
    with pytest.raises(FormalTrainingNotAllowedError, match="This fixture is TEST_ONLY"):
        reader.read("nonexistent", purpose="FORMAL_PROJECT_TRAINING")
    fixture = reader.read(ARTIFACT, purpose="TEST_ONLY")
    with pytest.raises(LeakageError, match="sealed"):
        fixture.partition("test", purpose="TEST_ONLY")
    with pytest.raises(FormalTrainingNotAllowedError):
        fixture.partition("train", purpose="FORMAL_PROJECT_TRAINING")
    with pytest.raises(FormalTrainingNotAllowedError):
        load_training_contract(ARTIFACT / "contract.json", test_only=True)


def test_formal_readiness_preserves_B_blockers_and_loader_refuses():
    readiness = inspect_b_contract(FORMAL, handoff_root=B_ROOT)
    assert readiness["status"] == FORMAL_BLOCKED and readiness["training_ready"] is False
    assert set(readiness["blocking_statuses"]) == {"WAITING_FOR_A", "WAITING_FOR_B", "TODO_CALIBRATION"}
    assert readiness["blocking_items"] == read_json(FORMAL)["unresolved_items"]
    assert "feature_contract.ordered_features" in readiness["unresolved_fields"]
    with pytest.raises(ContractNotReadyError, match="WAITING_FOR_A / WAITING_FOR_B / TODO_CALIBRATION"):
        load_training_contract(FORMAL)


@pytest.mark.parametrize("change", [{"contract_version": "unknown"}, {"training_ready": True}, {"status": "APPROVED"}])
def test_formal_draft_cannot_be_promoted(tmp_path, change):
    raw = read_json(FORMAL)
    raw.update(change)
    path = tmp_path / "draft.json"
    write(path, raw)
    with pytest.raises((ContractNotReadyError, IntegrityError)):
        inspect_b_contract(path, handoff_root=B_ROOT)
    with pytest.raises(ContractNotReadyError):
        load_training_contract(path)


@pytest.mark.parametrize("field", ["scenario", "synthetic_source", "teacher_risk_level", "group_id", "sample_id",
                                    "generator_seed", "source_rule_sha256", "label_source", "future_moisture"])
def test_B_audit_fields_cannot_enter_generic_model_input(case, field):
    with pytest.raises(LeakageError):
        validate_contract(replace(case[0], ordered_features=(field, "toy_b")), test_only=True)


@pytest.mark.parametrize("change", ["hash", "role", "physics", "fake_parent", "fake_metrics", "source", "missing_file"])
def test_corrupt_or_promoted_artifact_rejected(copied, change):
    manifest = read_json(copied / "manifest.json")
    if change == "hash":
        with (copied / "train.csv").open("a") as f:
            f.write("tampered\n")
    elif change == "missing_file":
        (copied / "train.csv").unlink()
    else:
        key, value = {"role": ("formal_training_dataset", True), "physics": ("physics_inspired", True),
                      "fake_parent": ("parent_run", "invented_real_run"), "fake_metrics": ("model_metrics", {"accuracy": 1}),
                      "source": ("generator_source_sha256", "0" * 64)}[change]
        manifest[key] = value
        write(copied / "manifest.json", manifest)
    with pytest.raises(IntegrityError):
        BRuleFixtureReader(B_ROOT).read(copied, purpose="TEST_ONLY")


@pytest.mark.parametrize("change", ["cross_split", "nonfinite", "label", "feature_order", "provenance_feature"])
def test_rehashed_semantic_corruption_rejected(copied, change):
    if change in ("feature_order", "provenance_feature"):
        contract = read_json(copied / "contract.json")
        if change == "feature_order":
            contract["model_features"].reverse()
        else:
            contract["model_features"][0] = "scenario"
        write(copied / "contract.json", contract)
        rehash(copied, "contract.json")
    else:
        path = copied / "train.csv"
        with path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            names, rows = reader.fieldnames, list(reader)
        if change == "cross_split":
            rows[0]["split"] = "test"
        elif change == "nonfinite":
            rows[0][names[-1]] = "nan"
        else:
            rows[0]["label"] = "99"
        with path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=names)
            writer.writeheader()
            writer.writerows(rows)
        rehash(copied, "train.csv")
    with pytest.raises(IntegrityError):
        BRuleFixtureReader(B_ROOT).read(copied, purpose="TEST_ONLY")


def test_cli_generates_auditable_report_without_overwrite(tmp_path):
    output = tmp_path / "report.json"
    env = dict(os.environ, PYTHONPATH=str(ROOT / "ai_training/src"), PYTHONDONTWRITEBYTECODE="1")
    command = [sys.executable, str(ROOT / "ai_training/scripts/validate_b_handoff.py"),
               "--handoff-root", str(B_ROOT), "--artifact", str(ARTIFACT), "--output", str(output)]
    result = subprocess.run(command, env=env, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    report = read_json(output)
    assert all(report["checks"].values()) and report["model_metrics"] is None
    assert report["onnx_export"] == "NOT_RUN" and report["model_training"] == "NOT_RUN"
    original = output.read_bytes()
    repeat = subprocess.run(command, env=env, text=True, capture_output=True)
    assert repeat.returncode == 2 and output.read_bytes() == original


def test_rehashed_nonfinite_in_both_source_and_partition_is_rejected(copied):
    # Updating the manifest is not enough: content semantics still must be valid.
    with (copied / "train.csv").open(encoding="utf-8-sig") as f:
        first = next(csv.DictReader(f))
    feature = read_json(copied / "contract.json")["model_features"][0]
    for name in ("train.csv", "dataset_all.csv"):
        path = copied / name
        with path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            fields, rows = reader.fieldnames, list(reader)
        for row in rows:
            if row["group_id"] == first["group_id"]:
                row[feature] = "inf"
        with path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        rehash(copied, name)
    with pytest.raises(IntegrityError, match="non-finite"):
        BRuleFixtureReader(B_ROOT).read(copied, purpose="TEST_ONLY")


def test_missing_B_validator_is_explicitly_blocked(tmp_path):
    with pytest.raises(IntegrityError, match="missing B validator"):
        inspect_b_contract(FORMAL, handoff_root=tmp_path)
