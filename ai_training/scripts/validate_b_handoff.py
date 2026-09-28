"""TEST_ONLY B→C artifact smoke test; does not fit or evaluate any model."""

import argparse
import json
from pathlib import Path
import sys

import numpy as np

from ai_training import __version__
from ai_training.adapters.b_rule_fixture import BRuleFixtureReader
from ai_training.contracts.b_handoff import inspect_b_contract
from ai_training.contracts.validation import load_training_contract
from ai_training.errors import ContractNotReadyError, FormalTrainingNotAllowedError, FrameworkError, IntegrityError
from ai_training.training.reproducibility import write_json_exclusive


def validate_handoff(handoff_root, artifact):
    reader = BRuleFixtureReader(handoff_root)
    first = reader.read(artifact, purpose="TEST_ONLY")
    repeated = reader.read(artifact, purpose="TEST_ONLY")
    checks = {"repeat_identity": first.fingerprint == repeated.fingerprint,
              "repeat_inputs": all(np.array_equal(first.partition(s, purpose="TEST_ONLY")[0],
                                                  repeated.partition(s, purpose="TEST_ONLY")[0])
                                   for s in ("train", "validation")),
              "formal_fixture_rejected": False, "formal_draft_rejected": False}
    try:
        reader.read(artifact, purpose="FORMAL_PROJECT_TRAINING")
    except FormalTrainingNotAllowedError:
        checks["formal_fixture_rejected"] = True
    formal_path = Path(handoff_root) / "contracts/B_FORMAL_TRAINING_CONTRACT_DRAFT.json"
    formal = inspect_b_contract(formal_path, handoff_root=handoff_root)
    try:
        load_training_contract(formal_path)
    except ContractNotReadyError:
        checks["formal_draft_rejected"] = True
    if not all(checks.values()):
        raise IntegrityError(f"B→C smoke test failed: {checks}; inspect the versioned handoff")
    return {"status": "READY_FOR_TEST_ONLY_INTEGRATION", "training_framework_version": __version__,
            "dataset_role": first.dataset_role, "formal_training_dataset": first.formal_training_dataset,
            "fixture_fingerprint": first.fingerprint, "identity": dict(first.identity),
            "model_features": list(first.feature_names), "feature_units": dict(first.feature_units),
            "row_counts": dict(first.row_counts), "checks": checks, "formal_readiness": formal,
            "model_training": "NOT_RUN", "model_version": None, "model_metrics": None,
            "onnx_export": "NOT_RUN", "real_world_performance": "NOT_EVALUATED"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--handoff-root", required=True, type=Path, help="trusted local B_revised source checkout")
    parser.add_argument("--artifact", required=True, type=Path, help="exported B TEST_ONLY fixture directory")
    parser.add_argument("--output", type=Path, help="optional new report file; never overwrite")
    args = parser.parse_args(argv)
    try:
        result = validate_handoff(args.handoff_root.resolve(), args.artifact.resolve())
        if args.output:
            write_json_exclusive(args.output, result)
    except (FrameworkError, OSError, ValueError) as exc:
        print(json.dumps({"status": "BLOCKED_OR_FAILED", "reason": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
