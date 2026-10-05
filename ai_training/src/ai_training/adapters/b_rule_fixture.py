"""Read B's precomputed demo rows, never reinterpret them as formal time windows."""

import csv
from dataclasses import dataclass
import hashlib
import io
from pathlib import Path
from types import MappingProxyType

import numpy as np

from ai_training.contracts.b_handoff import call_b_cli, inspect_b_contract, TEST_READY
from ai_training.contracts.validation import validate_feature_name
from ai_training.errors import FormalTrainingNotAllowedError, IntegrityError, LeakageError
from ai_training.training.reproducibility import content_hash, file_hash, read_json


def require_test_only(purpose):
    if purpose != "TEST_ONLY":
        raise FormalTrainingNotAllowedError(
            "This fixture is TEST_ONLY and cannot be used as formal project training data. "
            "Use purpose='TEST_ONLY' only for isolated software checks; formal training awaits A/B.")


@dataclass(frozen=True)
class FixtureRow:
    features: tuple[float, ...]
    label: int
    provenance: object


@dataclass(frozen=True)
class BRuleFixture:
    """Tabular TEST_ONLY artifact; deliberately not a CanonicalDataset.

    B has already aggregated six demo readings into each row. Adding an invented
    time axis/mask would imply a window contract that neither A nor B delivered.
    """
    feature_names: tuple[str, ...]
    feature_units: object
    label_contract: object
    row_counts: object
    identity: object
    fingerprint: str
    _rows: tuple[FixtureRow, ...]

    @property
    def dataset_role(self):
        return "TEST_ONLY"

    @property
    def formal_training_dataset(self):
        return False

    def partition(self, split, *, purpose):
        require_test_only(purpose)
        # Test is audited for integrity, but never exposed through the training API.
        if split not in ("train", "validation"):
            raise LeakageError("Test is sealed; use only train/validation for TEST_ONLY smoke checks")
        rows = [r for r in self._rows if r.provenance["split"] == split]
        # float64/int64 here are only C reader containers, not a formal B dtype.
        return (np.asarray([r.features for r in rows], dtype=np.float64),
                np.asarray([r.label for r in rows], dtype=np.int64),
                tuple(r.provenance for r in rows))


class BRuleFixtureReader:
    def __init__(self, handoff_root):
        self.handoff_root = Path(handoff_root).resolve()

    def read(self, directory, *, purpose):
        require_test_only(purpose)
        directory = Path(directory).resolve()
        contract_path = directory / "contract.json"
        result = inspect_b_contract(contract_path, handoff_root=self.handoff_root)
        if result["status"] != TEST_READY:
            raise IntegrityError("B artifact is not a rule fixture; provide the TEST_ONLY export")
        contract = read_json(contract_path)
        external = read_json(self.handoff_root / "contracts/B_RULE_DISTILLATION_CONTRACT.json")
        if contract != external:
            raise IntegrityError("embedded contract differs from B source contract; regenerate with the reviewed version")
        manifest_path = directory / "manifest.json"
        manifest = read_json(manifest_path)
        manifest_digest = file_hash(manifest_path)
        call_b_cli(self.handoff_root, "adapters/export_training_fixture.py", "--verify", directory)
        source = self.handoff_root / "队员B_算法开发交付"
        rule_digest = hashlib.sha256((source / "risk_algorithm.py").read_bytes()
                                     + (source / "demo_rules.json").read_bytes()).hexdigest()
        if (manifest.get("source_rule_sha256") != rule_digest
                or manifest.get("generator_source_sha256") != file_hash(
                    self.handoff_root / "智哨防灾_PRE_B_TRAINING_CONTRACT/synthetic_dataset.py")
                or type(manifest.get("generator_seed")) is not int or manifest["generator_seed"] < 0):
            raise IntegrityError("fixture source/seed differs from B handoff; restore matching rule and generator evidence")
        if (manifest.get("formal_split_manifest") is not None or manifest.get("model_metrics") is not None
                or any(manifest.get(k) is not None for k in ("run_id", "parent_run", "parameter_hash"))):
            raise IntegrityError("demo has no formal split, model metrics or run lineage; retain explicit null values")
        features = tuple(contract["model_features"])
        forbidden = set(contract["provenance_fields"]) | set(contract["forbidden_model_features"])
        for name in features:
            validate_feature_name(name)
            if name in forbidden:
                raise LeakageError("B provenance/forbidden field in X; restore the explicit model_features whitelist")
        # Read only bytes bound by the manifest. Rechecking also catches an artifact
        # replaced between the upstream verifier and the consumer read.
        payloads = {}
        for name, digest in manifest["file_hashes"].items():
            if Path(name).name != name:
                raise IntegrityError("fixture hash path escapes artifact directory; restore the B export")
            payloads[name] = (directory / name).read_bytes()
            if hashlib.sha256(payloads[name]).hexdigest() != digest:
                raise IntegrityError(f"fixture hash mismatch: {name}; restore original bytes")
        if (file_hash(manifest_path) != manifest_digest
                or hashlib.sha256(payloads["contract.json"]).hexdigest() != result["contract_sha256"]):
            raise IntegrityError("fixture changed while reading; retry with an immutable handoff")
        rows = []
        sample_ids = set()
        for index, row in enumerate(csv.DictReader(io.StringIO(payloads["dataset_all.csv"].decode("utf-8-sig")))):
            if None in row or any(v is None for v in row.values()):
                raise IntegrityError("malformed CSV row width; restore the complete B fixture")
            if not all(row[k] for k in ("group_id", "sample_id", "node_id")) or row["sample_id"] in sample_ids:
                raise IntegrityError("missing/duplicate demo sample identity; preserve unique source rows")
            sample_ids.add(row["sample_id"])
            values = tuple(float(row[name]) for name in features)
            if not np.isfinite(values).all():
                raise IntegrityError("non-finite fixture input; restore finite TEST_ONLY features")
            # Only contract-selected observations become X. Teacher outputs, seed,
            # synthetic source and grouping remain audit metadata, including nulls.
            provenance = {key: row.get(key, manifest.get(key)) for key in contract["provenance_fields"]}
            provenance.update(source_type="SYNTHETIC", source_file="dataset_all.csv", source_row_index=index,
                              source_artifact_hash=manifest_digest, source_csv_hash=manifest["file_hashes"]["dataset_all.csv"],
                              dataset_version=None, feature_version=None)
            rows.append(FixtureRow(values, int(row[contract["label_name"]]), MappingProxyType(provenance)))
        # Content identity excludes wall clock/path. It binds source validation code
        # too, but a hash is integrity evidence, not B approval or scientific validity.
        identity = {"contract_sha256": result["contract_sha256"], "manifest_sha256": manifest_digest,
                    "file_hashes": manifest["file_hashes"], "validator_sha256": result["validator_sha256"],
                    "exporter_sha256": file_hash(self.handoff_root / "adapters/export_training_fixture.py"),
                    "contract_version": contract["contract_version"], "dataset_role": "TEST_ONLY",
                    "formal_training_dataset": False, "physics_inspired": False}
        return BRuleFixture(features, MappingProxyType(contract["feature_units"]),
                            MappingProxyType({"name": contract["label_name"],
                                              "mapping": MappingProxyType(contract["label_mapping"])}),
                            MappingProxyType(manifest["row_counts"]), MappingProxyType(identity),
                            content_hash(identity), tuple(rows))
