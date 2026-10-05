"""Versioned B handoff inspection; no formal science or production interpreter."""

import json
import os
from pathlib import Path
import subprocess
import sys

from ai_training.errors import ContractNotReadyError, IntegrityError
from ai_training.training.reproducibility import file_hash, read_json

RULE_ID = "B_RULE_DISTILLATION_CONTRACT"
FORMAL_ID = "B_FORMAL_TRAINING_CONTRACT"
TEST_READY = "READY_FOR_TEST_ONLY_FRAMEWORK_SMOKE_TEST"
FORMAL_BLOCKED = "NOT_READY_FOR_FORMAL_TRAINING"


def call_b_cli(handoff_root, script, *arguments):
    """Run the trusted local B delivery's public CLI in an isolated process.

    B's exporter owns its validation rules and uses a top-level `contracts` import.
    A subprocess avoids importing that namespace into C or duplicating B's formulas.
    This executes local source, not an untrusted downloaded artifact.
    """
    root = Path(handoff_root).resolve()
    if script not in ("contracts/validate_contract.py", "adapters/export_training_fixture.py"):
        raise IntegrityError("unsupported B CLI; use a reviewed handoff entry point")
    entry = root / script
    if not entry.is_file():
        raise IntegrityError(f"missing B validator {entry}; provide the complete B_revised handoff")
    try:
        result = subprocess.run([sys.executable, "-B", str(entry), *map(str, arguments)],
                                cwd=root, capture_output=True, text=True, timeout=30,
                                env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    except subprocess.TimeoutExpired as exc:
        raise IntegrityError("B validation timed out; inspect the handoff CLI before retrying") from exc
    if result.returncode:
        raise IntegrityError(f"B validation failed: {result.stderr.strip()}; restore/fix the upstream artifact")
    try:
        value = json.loads(result.stdout)
    except ValueError as exc:
        raise IntegrityError("B CLI returned invalid JSON; restore its public interface") from exc
    if not isinstance(value, dict):
        raise IntegrityError("B CLI returned a non-object; restore its public interface")
    return value


def inspect_b_contract(path, *, handoff_root):
    path = Path(path).resolve()
    raw = read_json(path)
    supported = {RULE_ID: ("1.0-test-only", TEST_READY), FORMAL_ID: ("0.1-draft", FORMAL_BLOCKED)}
    if not isinstance(raw, dict) or raw.get("contract_id") not in supported:
        raise ContractNotReadyError("unknown B contract ID; integrate a reviewed version before use")
    version, expected_status = supported[raw["contract_id"]]
    if raw.get("contract_version") != version:
        raise ContractNotReadyError("unsupported B contract version; obtain a version-specific C adapter")
    digest = file_hash(path)
    result = call_b_cli(handoff_root, "contracts/validate_contract.py", path)
    if (result.get("status") != expected_status or result.get("formal_training_ready") is not False
            or result.get("contract_id") != raw["contract_id"] or file_hash(path) != digest):
        raise IntegrityError("B readiness changed or identity mismatched; use an immutable, consistent handoff")
    # Preserve B's ownership/status declarations, including unresolved calibration.
    return {**result, "training_ready": False, "contract_sha256": digest,
            "validator_sha256": file_hash(Path(handoff_root) / "contracts/validate_contract.py"),
            "blocking_items": raw.get("unresolved_items", []),
            "blocking_statuses": sorted(set(result["waiting_for"]) |
                                        {item["status"] for item in raw.get("unresolved_items", [])})}


def reject_formal_draft(raw):
    # Even fully populated values/status changes cannot register a formal version.
    # WAITING_FOR_A/B: evidence and a reviewed interpreter are both prerequisites.
    if raw.get("contract_version") != "0.1-draft":
        raise ContractNotReadyError("unsupported B formal contract version; version-specific review required")
    items = raw.get("unresolved_items", [])
    raise ContractNotReadyError(
        f"{FORMAL_BLOCKED}: WAITING_FOR_A / WAITING_FOR_B / TODO_CALIBRATION. "
        f"B draft blocking items: {json.dumps(items, ensure_ascii=False)}. "
        "Deliver A real data and B approved contract, then integrate its reviewed interpreter; no defaults.")
