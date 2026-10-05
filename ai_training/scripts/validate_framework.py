"""Explicit TEST_ONLY validation, or fail-closed external contract checking."""

import argparse
import importlib.util
import json
from pathlib import Path
import sys
import tempfile

from ai_training.artifacts.manifest import load_manifest
from ai_training.contracts.validation import load_training_contract
from ai_training.errors import FrameworkError, IntegrityError
from ai_training.training.reproducibility import file_hash, write_json_exclusive


def self_test(output_root):
    # Fixtures are deliberately outside the distributable package. This command
    # requires the source checkout and never substitutes toy data for A/B data.
    fixture = Path(__file__).resolve().parents[1] / "tests/fixtures/toy.py"
    spec = importlib.util.spec_from_file_location("training_toy_fixture", fixture)
    toy = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = toy
    spec.loader.exec_module(toy)
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    # Random directory suffix is a collision-safe storage location only. It is
    # excluded from training/content identity and from all numerical RNGs.
    evidence = Path(tempfile.mkdtemp(prefix="TEST_ONLY_validation_", dir=root))
    full_a = toy.run_case(evidence / "full_a")
    full_b = toy.run_case(evidence / "full_b")
    partial = toy.run_case(evidence / "partial", stop_after_epoch=2)
    checkpoint = partial / "checkpoints/last.json"
    resumed = toy.run_case(evidence / "resumed", resume=checkpoint, resume_hash=file_hash(checkpoint))
    ma, mb, mr = (load_manifest(p) for p in (full_a, full_b, resumed))
    checks = {
        "repeat_same_training_run_id": full_a.name == full_b.name,
        "repeat_same_manifest_content_hash": ma["manifest_hash"] == mb["manifest_hash"],
        "repeat_all_artifact_hashes_identical": ma["artifact_hashes"] == mb["artifact_hashes"],
        "resume_all_artifact_hashes_identical": ma["artifact_hashes"] == mr["artifact_hashes"],
        "checkpoint_bytes_identical": (full_a / "checkpoints/last.json").read_bytes() == (resumed / "checkpoints/last.json").read_bytes(),
        "formal_training_blocked": False,
    }
    try:
        load_training_contract(fixture.with_name("test_only_contract.json"))
    except FrameworkError:
        checks["formal_training_blocked"] = True
    if not all(checks.values()):
        raise IntegrityError(f"TEST_ONLY validation failed: {checks}; inspect preserved evidence at {evidence}")
    summary = {"status": "TEST_ONLY_VALIDATION_PASSED", "project_status": "PRE_B_TRAINING_CONTRACT",
               "declarations": ["TEST_ONLY", "NOT_REAL_DATA", "NOT_PROJECT_TRAINING_DATA"],
               "checks": checks, "training_run_id": ma["training_run_id"],
               "checkpoint_hash": ma["checkpoint_hash"], "manifest_content_hash": ma["manifest_hash"],
               "runs": {name: str(path.resolve()) for name, path in
                        (("full_a", full_a), ("full_b", full_b), ("partial", partial), ("resumed", resumed))},
               "evidence_directory": str(evidence.resolve()), "onnx_export": "NOT_RUN",
               "real_world_performance": "NOT_EVALUATED"}
    write_json_exclusive(evidence / "validation_summary.json", summary)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--self-test", action="store_true", help="run isolated deterministic TEST_ONLY fixtures")
    mode.add_argument("--contract", type=Path, help="validate a formal contract; remains blocked in V0.1")
    parser.add_argument("--output-root", type=Path, default=Path(__file__).resolve().parents[1] / "outputs")
    args = parser.parse_args(argv)
    try:
        result = self_test(args.output_root) if args.self_test else load_training_contract(args.contract)
    except (FrameworkError, OSError, ValueError) as exc:
        print(json.dumps({"status": "BLOCKED_OR_FAILED", "reason": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
