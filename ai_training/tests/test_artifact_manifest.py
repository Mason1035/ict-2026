from copy import deepcopy
from dataclasses import replace
import pytest

from ai_training.artifacts.manifest import load_manifest, validate_manifest, manifest_hash
from ai_training.errors import IntegrityError, ContractNotReadyError
from ai_training.export.onnx_contract import ONNXExportManifest, ONNXParityResult
from ai_training.training.reproducibility import content_hash, read_json, file_hash
import json


def test_manifest_complete_and_no_overwrite(toy, tmp_path):
    directory = toy.run_case(tmp_path)
    m = load_manifest(directory)
    assert m["status"] == "PRE_B_TRAINING_CONTRACT" and m["purpose"] == "TEST_ONLY"
    assert m["training_run_id"] == "training_" + content_hash(m["identity"])
    assert m["manifest_hash"] == manifest_hash(m)
    assert m["onnx"]["status"] == m["onnx_parity_status"] == m["deployment_validation_status"] == "NOT_RUN"
    assert m["onnx"]["onnx_hash"] is None
    assert m["identity"]["dependency_versions"] and m["identity"]["implementation_hashes"]
    original = (directory / "manifest.json").read_bytes()
    with pytest.raises(FileExistsError):
        toy.run_case(tmp_path)
    assert (directory / "manifest.json").read_bytes() == original


def test_manifest_missing_fields_and_false_success_rejected(toy, tmp_path):
    directory = toy.run_case(tmp_path)
    m = load_manifest(directory)
    for field in ("created_by", "checkpoint_hash", "sources", "normalizer_version", "identity"):
        incomplete = deepcopy(m)
        del incomplete[field]
        with pytest.raises(IntegrityError):
            validate_manifest(directory, incomplete)
    for field in ("onnx_parity_status", "deployment_validation_status", "independent_real_test_status"):
        with pytest.raises(IntegrityError, match="success claim"):
            validate_manifest(directory, dict(m, **{field: "SUCCESS"}))
    with pytest.raises(IntegrityError):
        validate_manifest(directory, dict(m, artifact_hashes={}))


def test_artifact_tampering_detected(toy, tmp_path):
    directory = toy.run_case(tmp_path)
    (directory / "evaluation/metrics.json").write_text('{}')
    with pytest.raises(IntegrityError, match="hash/path"):
        load_manifest(directory)


def test_rehashed_config_from_another_run_rejected(toy, tmp_path):
    directory = toy.run_case(tmp_path)
    manifest = load_manifest(directory)
    path = directory / "training_config.json"
    config = read_json(path)
    path.write_text(json.dumps(config | {"seed": 999}))
    manifest["artifact_hashes"]["training_config.json"] = file_hash(path)
    with pytest.raises(IntegrityError, match="differs from run identity"):
        validate_manifest(directory, manifest)


def test_foreign_checkpoint_rejected_even_with_updated_file_hash(toy, case, tmp_path):
    c, d, cfg = case
    directory = toy.run_case(tmp_path / "original", case=case)
    other = toy.run_case(tmp_path / "other", case=(c, d, replace(cfg, seed=999)))
    manifest = load_manifest(directory)
    path = directory / "checkpoints/last.json"
    path.write_bytes((other / "checkpoints/last.json").read_bytes())
    manifest["artifact_hashes"]["checkpoints/last.json"] = manifest["checkpoint_hash"] = file_hash(path)
    with pytest.raises(IntegrityError, match="incompatible checkpoint identity"):
        validate_manifest(directory, manifest)


def test_onnx_schema_reserves_information_without_claiming_export():
    export = ONNXExportManifest(model_version="TEST_ONLY", input_shape=(None, None, None))
    assert export.status == ONNXParityResult().status == "NOT_RUN"
    for kwargs in ({"status": "SUCCESS"}, {"onnx_hash": "0" * 64}):
        with pytest.raises(ContractNotReadyError):
            ONNXExportManifest(**kwargs)
    with pytest.raises(ContractNotReadyError):
        ONNXParityResult(status="PASSED")
    with pytest.raises(ContractNotReadyError):
        ONNXParityResult(max_error=0.)
