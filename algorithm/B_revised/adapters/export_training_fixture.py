"""Export and verify B's rule-distillation fixture; never a formal dataset."""

import argparse
import csv
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from contracts.validate_contract import validate_contract_file, read_contract, STATUS_TEST  # noqa: E402

CONTRACT_FILE = ROOT / "contracts/B_RULE_DISTILLATION_CONTRACT.json"
GENERATOR_FILE = ROOT / "智哨防灾_PRE_B_TRAINING_CONTRACT/synthetic_dataset.py"
ALGORITHM_DIR = ROOT / "队员B_算法开发交付"
DEFAULT_OUTPUT = ROOT / "artifacts/rule_distillation_demo"
REQUIRED_FILES = {
    "dataset_all.csv", "train.csv", "validation.csv", "test.csv", "excluded_unknown.csv",
    "contract.json", "summary.json", "synthetic_histories.jsonl", "metrics_template.json", "README.txt",
}


def _hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write_json(path, value, *, exclusive=True):
    with Path(path).open("x" if exclusive else "w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def _rows(path):
    with Path(path).open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise ValueError(f"duplicate/missing CSV columns: {path}")
        return reader.fieldnames, list(reader)


def _source_generator():
    # The old generator is used as an unchanged rule/split implementation.
    # It writes only to the explicit fresh output_dir passed by this adapter.
    spec = importlib.util.spec_from_file_location("b_test_only_source_generator", GENERATOR_FILE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def verify_artifact(directory):
    directory = Path(directory)
    manifest = read_contract(directory / "manifest.json")
    contract = read_contract(directory / "contract.json")
    result = validate_contract_file(directory / "contract.json")
    if (result["status"] != STATUS_TEST or manifest.get("artifact_role") != "AI_TRAINING_FRAMEWORK_TEST_FIXTURE"
            or manifest.get("status") != "TEST_ONLY"):
        raise ValueError("artifact is not a recognized TEST_ONLY framework fixture")
    expected = {"contract_id": contract["contract_id"], "contract_version": contract["contract_version"],
                "synthetic_source": contract["synthetic_source"], "training_scope": contract["training_scope"],
                "model_features": contract["model_features"], "feature_names": contract["model_features"],
                "label_name": contract["label_name"], "split_scope": contract["split"]["scope"]}
    if any(manifest.get(key) != value for key, value in expected.items()):
        raise ValueError("fixture manifest/contract identity or feature order mismatch")
    if (manifest.get("dataset_role") != "TEST_ONLY_RULE_DISTILLATION_FIXTURE"
            or manifest.get("generator_version") != contract["generator_version"]
            or manifest.get("formal_training_dataset") is not False
            or manifest.get("physics_inspired") is not False
            or manifest.get("formal_training_ready") is not False
            or manifest.get("real_data_ready") is not False
            or manifest.get("formal_feature_contract_ready") is not False
            or manifest.get("formal_label_contract_ready") is not False
            or manifest.get("formal_split_ready") is not False):
        raise ValueError("fixture cannot claim formal, real, or physics-inspired readiness")
    if (set(manifest.get("provenance_fields", [])) != set(contract["provenance_fields"])
            or set(manifest.get("forbidden_model_features", [])) != set(contract["forbidden_model_features"])):
        raise ValueError("fixture model/provenance boundary differs from contract")
    hashes = manifest.get("file_hashes")
    if not isinstance(hashes, dict) or set(hashes) != REQUIRED_FILES:
        raise ValueError("fixture file hash inventory incomplete")
    for name, digest in hashes.items():
        if not isinstance(digest, str) or len(digest) != 64 or _hash(directory / name) != digest:
            raise ValueError(f"fixture file hash mismatch: {name}")

    summary = read_contract(directory / "summary.json")
    if (summary.get("contract_id") != contract["contract_id"]
            or summary.get("contract_version") != contract["contract_version"]
            or summary.get("features_in_order") != contract["model_features"]
            or summary.get("formal_training_ready") is not False
            or summary.get("training_scope") != contract["training_scope"]):
        raise ValueError("fixture summary does not match TEST_ONLY contract")
    if (manifest.get("source_rule_sha256") != summary.get("source_rule_sha256")
            or manifest.get("source_rule_version") != summary.get("source_rule_version")
            or manifest.get("generator_seed") != summary.get("generator_seed")):
        raise ValueError("rule/generator provenance mismatch")
    source_digest = manifest.get("generator_source_sha256")
    if not isinstance(source_digest, str) or len(source_digest) != 64 or any(c not in "0123456789abcdef" for c in source_digest):
        raise ValueError("generator source hash missing or malformed")

    all_names, all_rows = _rows(directory / "dataset_all.csv")
    if all_names != contract["csv_schema"]["dataset_all.csv"]:
        raise ValueError("dataset_all.csv field order differs from contract")
    all_by_group = {row["group_id"]: row for row in all_rows}
    if len(all_by_group) != len(all_rows):
        raise ValueError("duplicate group in dataset_all.csv")
    labels = contract["label_mapping"]
    if any(row["teacher_risk_level"] not in ("normal", "attention", "warning")
           or row["label"] != str(labels[row["teacher_risk_level"]]) for row in all_rows):
        raise ValueError("rule proxy labels do not match their audit source")
    ids = set()
    split_rows = {}
    for split in ("train", "validation", "test"):
        names, rows = _rows(directory / f"{split}.csv")
        if names != contract["csv_schema"]["train.csv/validation.csv/test.csv"]:
            raise ValueError(f"{split}.csv field order differs from contract")
        split_rows[split] = rows
        if len(rows) != summary["splits"][split]["rows"] or len(rows) != manifest["row_counts"][split]:
            raise ValueError(f"{split} row count differs from summary/manifest")
        for row in rows:
            if row["split"] != split or row["label"] not in ("0", "1") or row["group_id"] in ids:
                raise ValueError("invalid supervised label or duplicate/cross-split group")
            source_row = all_by_group.get(row["group_id"])
            if source_row is None or any(row[key] != source_row[key]
                                         for key in ("sample_id", "split", "label", *contract["model_features"])):
                raise ValueError("split row differs from dataset_all source; restore the original fixture")
            ids.add(row["group_id"])
            for feature in contract["model_features"]:
                if not math.isfinite(float(row[feature])):
                    raise ValueError("non-finite demo feature")
    if len(all_rows) != len(ids) or {r["group_id"] for r in all_rows} != ids:
        raise ValueError("dataset_all and split partition groups differ")
    if len(ids) != summary["supervised_rows"] or manifest["row_counts"]["dataset_all"] != len(ids):
        raise ValueError("total supervised row count mismatch")
    unknown_names, unknown = _rows(directory / "excluded_unknown.csv")
    if unknown_names != contract["csv_schema"]["excluded_unknown.csv"]:
        raise ValueError("excluded_unknown.csv field order differs from contract")
    if (len(unknown) != summary["excluded_unknown_rows"]
            or len(unknown) != manifest["row_counts"]["excluded_unknown"]
            or len({r["group_id"] for r in unknown}) != len(unknown)
            or any(r["label"] != "" or r["teacher_risk_level"] != "unknown" or r["group_id"] in ids for r in unknown)):
        raise ValueError("unknown samples entered supervised data or counts disagree")
    return {"status": STATUS_TEST, "artifact": str(directory.resolve()),
            "row_counts": manifest["row_counts"], "file_hashes_verified": len(hashes)}


def export_fixture(output_dir=DEFAULT_OUTPUT, *, groups_per_class=60, seed=20260925):
    result = validate_contract_file(CONTRACT_FILE)
    if result["status"] != STATUS_TEST:
        raise ValueError("rule contract is not ready for TEST_ONLY export")
    output_dir = Path(output_dir)
    if output_dir.exists():
        raise FileExistsError(f"fixture output already exists: {output_dir}; choose a fresh --output-dir")
    generator = _source_generator()
    if list(generator.FEATURES) != read_contract(CONTRACT_FILE)["model_features"]:
        raise ValueError("generator feature order drifted from B rule contract")
    summary = generator.build_dataset(groups_per_class, seed, ALGORITHM_DIR,
                                      output_dir=output_dir, contract_path=CONTRACT_FILE)
    contract = read_contract(CONTRACT_FILE)
    summary.update({"generated_at_utc": None, "status": "TEST_ONLY", "training_scope": contract["training_scope"],
                    "formal_training_ready": False, "synthetic_source": contract["synthetic_source"],
                    "dataset_role": "TEST_ONLY_RULE_DISTILLATION_FIXTURE", "physics_inspired": False})
    _write_json(output_dir / "summary.json", summary, exclusive=False)
    with (output_dir / "contract.json").open("xb") as stream:
        stream.write(CONTRACT_FILE.read_bytes())
    counts = {split: summary["splits"][split]["rows"] for split in ("train", "validation", "test")}
    counts["dataset_all"] = summary["supervised_rows"]
    counts["excluded_unknown"] = summary["excluded_unknown_rows"]
    manifest = {
        "artifact_role": "AI_TRAINING_FRAMEWORK_TEST_FIXTURE",
        "contract_id": contract["contract_id"], "contract_version": contract["contract_version"],
        "status": "TEST_ONLY", "training_scope": contract["training_scope"],
        "dataset_role": "TEST_ONLY_RULE_DISTILLATION_FIXTURE",
        "synthetic_source": contract["synthetic_source"], "physics_inspired": False,
        "formal_training_dataset": False, "formal_training_ready": False, "real_data_ready": False,
        "formal_feature_contract_ready": False, "formal_label_contract_ready": False, "formal_split_ready": False,
        "generator_version": contract["generator_version"], "generator_seed": seed,
        "generator_source_sha256": _hash(GENERATOR_FILE),
        "source_rule_version": summary["source_rule_version"], "source_rule_sha256": summary["source_rule_sha256"],
        "run_id": None, "parent_run": None, "parameter_hash": None,
        "feature_names": contract["model_features"], "model_features": contract["model_features"],
        "label_name": contract["label_name"], "provenance_fields": contract["provenance_fields"],
        "forbidden_model_features": contract["forbidden_model_features"],
        "split_scope": contract["split"]["scope"], "row_counts": counts,
        "file_hashes": {name: _hash(output_dir / name) for name in sorted(REQUIRED_FILES)},
        "formal_split_manifest": None, "model_metrics": None,
    }
    _write_json(output_dir / "manifest.json", manifest)
    return verify_artifact(output_dir)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Export/verify TEST_ONLY B rule-distillation fixture")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--verify", type=Path, help="verify an existing fixture without writing")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--groups-per-class", type=int, default=60)
    parser.add_argument("--seed", type=int, default=20260925)
    args = parser.parse_args(argv)
    try:
        result = verify_artifact(args.verify) if args.verify else export_fixture(
            args.output_dir, groups_per_class=args.groups_per_class, seed=args.seed)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "FAILED", "reason": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
