"""Traceable run manifests: content identity excludes wall-clock audit fields."""

from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from ai_training import __version__, STATUS
from ai_training.errors import IntegrityError
from ai_training.export.onnx_contract import ONNXExportManifest
from ai_training.training.checkpoint import load_checkpoint
from ai_training.training.reproducibility import content_hash, environment_identity, file_hash, read_json, write_json_exclusive


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def run_identity(config, contract, dataset):
    return {"framework_version": __version__, "training_seed": config.seed,
            "training_config_hash": content_hash(asdict(config)), "training_config": asdict(config),
            "training_contract_version": contract.contract_version, "contract_hash": content_hash(contract.to_dict()),
            "feature_version": contract.feature_version, "dataset_version": dataset.version,
            "dataset_hash": dataset.content_hash(), "split_manifest_hash": content_hash(contract.split_manifest.to_dict()),
            "model_config": config.model_config, **environment_identity()}


def allocate_run(root, identity):
    # Same inputs give the same logical ID. Replays must use a new output root;
    # exclusive mkdir protects earlier evidence even when contents would match.
    run_id = "training_" + content_hash(identity)
    directory = Path(root) / run_id
    directory.parent.mkdir(parents=True, exist_ok=True)
    directory.mkdir(exist_ok=False)
    return directory


def manifest_hash(manifest):
    # Audit timestamps are retained, but are not content identity. All other
    # fields, including dependency/code/data/checkpoint hashes, remain covered.
    return content_hash({k: v for k, v in manifest.items() if k not in ("started_at", "ended_at", "manifest_hash")})


def make_manifest(identity, *, created_by, started_at, sources, artifact_hashes, normalizer_version, completed, resumed_from=None):
    return {"schema_version": "ai_training.artifact.v0.1", "status": STATUS,
            "purpose": "TEST_ONLY", "training_run_id": "training_" + content_hash(identity),
            "identity": identity, "created_by": created_by, "started_at": started_at, "ended_at": utc_now(),
            "execution_status": "TEST_ONLY_COMPLETED" if completed else "TEST_ONLY_INTERRUPTED_AT_EPOCH",
            "sources": sources, "artifact_hashes": artifact_hashes, "resumed_from_checkpoint_hash": resumed_from,
            "normalizer_version": normalizer_version,
            "normalizer_hash": artifact_hashes.get("preprocessing/normalizer.json"),
            "checkpoint_hash": artifact_hashes.get("checkpoints/last.json"),
            "metrics_artifact_hash": artifact_hashes.get("evaluation/metrics.json"),
            "onnx": ONNXExportManifest().to_dict(), "onnx_parity_status": "NOT_RUN",
            "deployment_validation_status": "NOT_RUN", "independent_real_test_status": "NOT_RUN"}


def validate_manifest(directory, manifest):
    required = {"schema_version", "status", "purpose", "training_run_id", "identity", "created_by",
                "started_at", "ended_at", "execution_status", "stop_reason", "sources", "artifact_hashes",
                "resumed_from_checkpoint_hash", "normalizer_version", "normalizer_hash", "checkpoint_hash",
                "metrics_artifact_hash", "onnx", "onnx_parity_status", "deployment_validation_status",
                "independent_real_test_status"}
    if not isinstance(manifest, dict) or not required <= set(manifest):
        raise IntegrityError("manifest fields missing; retain complete run identity, status and artifact references")
    if (manifest.get("schema_version") != "ai_training.artifact.v0.1"
            or manifest.get("status") != STATUS or manifest.get("purpose") != "TEST_ONLY"
            or manifest.get("training_run_id") != "training_" + content_hash(manifest.get("identity"))):
        raise IntegrityError("invalid artifact identity/schema; use the matching skeleton manifest")
    if (manifest.get("onnx", {}).get("status") != "NOT_RUN" or manifest["onnx"].get("onnx_hash") is not None
            or any(manifest[k] != "NOT_RUN" for k in ("onnx_parity_status", "deployment_validation_status", "independent_real_test_status"))):
        raise IntegrityError("unsupported export/deployment success claim; no such stage ran")
    identity_fields = {"framework_version", "training_seed", "training_config_hash", "training_config",
                       "training_contract_version", "contract_hash", "feature_version", "dataset_version",
                       "dataset_hash", "split_manifest_hash", "model_config", "dependency_versions", "platform",
                       "source_code_revision", "source_tree_hash", "implementation_hashes"}
    if not isinstance(manifest["identity"], dict) or not identity_fields <= set(manifest["identity"]):
        raise IntegrityError("incomplete training identity; regenerate a complete framework artifact")
    references = {"normalizer_hash": "preprocessing/normalizer.json", "checkpoint_hash": "checkpoints/last.json",
                  "metrics_artifact_hash": "evaluation/metrics.json"}
    required_artifacts = set(references.values()) | {"training_config.json", "contract.json", "split_manifest.json", "training_log.csv"}
    if not isinstance(manifest["artifact_hashes"], dict) or not required_artifacts <= set(manifest["artifact_hashes"]):
        raise IntegrityError("required run artifacts missing; preserve checkpoint/config/contract/evaluation/preprocessing/log")
    if any(manifest[k] != manifest["artifact_hashes"][v] for k, v in references.items()):
        raise IntegrityError("manifest artifact aliases disagree; restore original hashes")
    root = Path(directory).resolve()
    for relative, digest in manifest["artifact_hashes"].items():
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or not path.is_file() or file_hash(path) != digest:
            raise IntegrityError(f"artifact hash/path mismatch: {relative}; restore the original run bundle")
    # File integrity alone does not link a valid file to THIS experiment. Bind
    # the serialized inputs back to the identity carried by every checkpoint.
    for filename, identity_key in (("training_config.json", "training_config_hash"),
                                   ("contract.json", "contract_hash"),
                                   ("split_manifest.json", "split_manifest_hash")):
        if content_hash(read_json(root / filename)) != manifest["identity"][identity_key]:
            raise IntegrityError(f"{filename} differs from run identity; do not mix artifacts from different experiments")
    checkpoint = load_checkpoint(root / "checkpoints/last.json", manifest["identity"], expected_hash=manifest["checkpoint_hash"])
    if "checkpoints/best.json" in manifest["artifact_hashes"]:
        load_checkpoint(root / "checkpoints/best.json", manifest["identity"],
                        expected_hash=manifest["artifact_hashes"]["checkpoints/best.json"])
    normalizer = read_json(root / "preprocessing/normalizer.json")
    payload = normalizer.get("payload", {})
    if (normalizer.get("content_hash") != content_hash(payload)
            or payload.get("identity") != manifest["identity"]
            or payload.get("normalizer_version") != manifest["normalizer_version"]):
        raise IntegrityError("normalizer identity/hash mismatch; restore preprocessing from the same run")
    evaluation = read_json(root / "evaluation/metrics.json")
    expected_evaluation = {"contract_hash": manifest["identity"]["contract_hash"],
                           "split_manifest_hash": manifest["identity"]["split_manifest_hash"],
                           "dataset_version": manifest["identity"]["dataset_version"],
                           "model_state_hash": content_hash(checkpoint["state"]["model"])}
    if any(evaluation.get(k) != v for k, v in expected_evaluation.items()):
        raise IntegrityError("evaluation identity mismatch; evaluate the checkpoint and split recorded in this run")


def save_manifest(directory, manifest):
    validate_manifest(directory, manifest)
    value = dict(manifest, manifest_hash=manifest_hash(manifest))
    write_json_exclusive(Path(directory) / "manifest.json", value)
    return value


def load_manifest(directory):
    value = read_json(Path(directory) / "manifest.json")
    if value.get("manifest_hash") != manifest_hash(value):
        raise IntegrityError("manifest hash mismatch; restore the original manifest")
    validate_manifest(directory, value)
    return value
