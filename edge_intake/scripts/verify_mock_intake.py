"""Exercise C's intake behind A's pinned TEST_ONLY mock validator.

This checks only the C intake boundary. It neither calls B nor replaces A's
three-person integration runner or production Validator.
"""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

from edge_intake import __version__, receive_validated_telemetry


_FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "tests/fixtures/a_mock"
_CASES = ("M01_NORMAL", "M02_MISSING_SENSOR", "M07_RISK_NOT_CALIBRATED", "M08_INVALID_SCHEMA")
_EXPECTED_REJECTIONS = (
    ("payload.schema", "SCHEMA_NAME"),
    ("payload.boot_id", "TYPE"),
    ("payload.seq", "REQUIRED"),
    ("payload.soil.middle_raw", "TYPE"),
)


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_module(name, path):
    # Only execute explicitly pinned A test helpers. No production code depends
    # on this loader; the hashes below prevent unnoticed fixture drift.
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses resolves the module during loading.
    spec.loader.exec_module(module)
    return module


def _sources(a_repo):
    manifest = json.loads((_FIXTURE_ROOT / "manifest.json").read_text(encoding="utf-8"))
    if a_repo is None:
        base = _FIXTURE_ROOT
        mode = "PINNED_TEST_SNAPSHOTS"
    else:
        repository = Path(a_repo).resolve()
        revision = subprocess.run(
            ["git", "-C", str(repository), "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        if revision != manifest["source_commit"]:
            raise ValueError("A source revision differs from pinned evidence; use the documented A commit or review and update snapshots explicitly")
        base = repository / "experiments/mock_interface"
        mode = "PINNED_A_CHECKOUT"
    hashes = {}
    for relative, expected in manifest["files"].items():
        actual = _sha256(base / relative)
        if actual != expected["sha256"]:
            raise ValueError("A TEST_ONLY source hash mismatch: " + relative + "; restore the pinned source rather than silently updating evidence")
        hashes[relative] = actual
    return base, manifest, mode, hashes


def verify_cases(a_repo=None):
    """Return actual call/rejection evidence from the four isolated MOCK cases."""
    base, manifest, mode, source_hashes = _sources(a_repo)
    loader = _load_module("_edge_check_a_mock_loader", base / "runner/mock_loader.py")
    validator = _load_module("_edge_check_a_mock_validator", base / "runner/mock_v2_validator.py")
    cases = []
    for case_id in _CASES:
        loaded = loader.load_case(base / "cases" / (case_id + ".json"))
        rows = []
        violations = []
        edge_calls = 0
        if loaded.document.get("source") != "MOCK":
            raise ValueError(case_id + ": only explicitly marked MOCK test inputs may be consumed")
        for index, message in enumerate(loaded.document["messages"]):
            if message.get("source") != "MOCK":
                raise ValueError(case_id + ": message source must remain MOCK")
            payload = message["payload"]
            validation = validator.validate(payload)
            row = {
                "message_index": index,
                "payload_sha256_before": loader.payload_hash(payload),
                "validator": validation,
                "sampling_snapshot_check": "NOT_CALLED",
                "edge_called": False,
                "edge_status": "NOT_CALLED",
                "edge_result": None,
            }
            # Validation is the routing gate. Invalid inputs never reach the
            # snapshot checker or C; a rejection cannot be counted as acceptance.
            if validation["status"] == "ACCEPT":
                snapshot_errors = loader.check_snapshot(message["sampling_snapshot"], payload)
                row["sampling_snapshot_check"] = {"errors": snapshot_errors}
                if snapshot_errors:
                    violations.append("message %d: sampling snapshot mismatch" % index)
                else:
                    context = {
                        "source": "MOCK", "case_id": case_id,
                        "sampling_snapshot": message["sampling_snapshot"], "scope": "TEST_ONLY",
                    }
                    frozen_payload, frozen_context = loader.freeze(payload), loader.freeze(context)
                    edge_calls += 1
                    row["edge_called"] = True
                    result = receive_validated_telemetry(frozen_payload, context=frozen_context)
                    row["edge_result"] = result
                    row["edge_status"] = result["status"]
                    checks = {
                        "accepted_by_edge": result["status"] == "ACCEPTED_BY_EDGE_INTAKE",
                        "identity_preserved": result["identity"] == {key: payload[key] for key in ("device_id", "boot_id", "seq")},
                        "source_preserved_as_sidecar": result["source"] == "MOCK" and "source" not in result["payload"],
                        "payload_preserved": result["payload"] == payload,
                        "context_preserved": result["context"] == context,
                        "payload_hash_matches_A": result["payload_sha256"] == loader.payload_hash(payload),
                        "caller_payload_unchanged": loader.payload_hash(frozen_payload) == row["payload_sha256_before"],
                        "downstream_unimplemented": result["downstream"] == "NOT_IMPLEMENTED" and result["downstream_status"] == "DOWNSTREAM_NOT_IMPLEMENTED",
                        "not_durable_ack": result["durable"] is False,
                    }
                    if case_id == "M02_MISSING_SENSOR":
                        checks["missing_soil_remains_null"] = result["payload"]["soil"]["middle_raw"] is None
                        checks["validity_remains_sidecar"] = result["context"]["sampling_snapshot"]["soil"][1]["validity"] == "Unavailable"
                    if case_id == "M07_RISK_NOT_CALIBRATED":
                        checks["uncalibrated_risk_remains_null"] = all(result["payload"]["risk"][key] is None for key in ("sensor_score", "level", "reason_mask"))
                    row["checks"] = checks
                    violations.extend("message %d: %s" % (index, key) for key, passed in checks.items() if not passed)
            if case_id == "M08_INVALID_SCHEMA":
                actual = {(error["path"], error["code"]) for error in validation["errors"]}
                if index >= len(_EXPECTED_REJECTIONS) or actual != {_EXPECTED_REJECTIONS[index]}:
                    violations.append("message %d: unexpected upstream rejection" % index)
                if row["edge_called"] or row["sampling_snapshot_check"] != "NOT_CALLED":
                    violations.append("message %d: rejected input reached a downstream consumer" % index)
            elif validation["status"] != "ACCEPT":
                violations.append("message %d: valid fixture rejected upstream" % index)
            rows.append(row)
        expected_count = 0 if case_id == "M08_INVALID_SCHEMA" else 1
        if edge_calls != expected_count:
            violations.append("actual Edge call count differs from required case count")
        if case_id == "M08_INVALID_SCHEMA" and len(rows) != 4:
            violations.append("M08 must exercise all four negative messages")
        cases.append({
            "case_id": case_id, "input_sha256": loaded.input_sha256,
            "edge_call_count": edge_calls, "status": "FAIL" if violations else "PASS",
            "violations": violations, "messages": rows,
        })
    package_root = Path(__file__).resolve().parents[1]
    return {
        "scope": "TEST_ONLY / MOCK_ONLY / NOT_REAL_DATA / NOT_PROJECT_TRAINING_DATA",
        "edge_check_status": "PASS" if all(case["status"] == "PASS" for case in cases) else "FAIL",
        "intake_version": __version__,
        "source_mode": mode,
        "A_source_commit": manifest["source_commit"],
        "A_source_file_sha256": source_hashes,
        "C_intake_source_sha256": {name: _sha256(package_root / name) for name in ("__init__.py", "intake.py")},
        "edge_call_count": sum(case["edge_call_count"] for case in cases),
        "three_person_integration": "NOT_RUN",
        "A_adapter_status": "WAITING_FOR_A_UPDATE_TO_NEW_EDGE_ENTRY",
        "B_risk_consumer": "NOT_CALLED",
        "production_validator": "NOT_IMPLEMENTED",
        "downstream": "NOT_IMPLEMENTED",
        "durable_storage": "NOT_IMPLEMENTED",
        "cases": cases,
    }


def write_report(report, output):
    """Create new evidence; never replace an earlier experimental artifact."""
    with Path(output).open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        handle.write("\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--a-repo", type=Path, help="Read-only A checkout at the pinned source commit")
    parser.add_argument("--output", type=Path, help="Create a new evidence JSON (existing paths are rejected)")
    args = parser.parse_args(argv)
    try:
        report = verify_cases(args.a_repo)
        if args.output:
            write_report(report, args.output)
            print(json.dumps({"edge_check_status": report["edge_check_status"], "edge_call_count": report["edge_call_count"], "three_person_integration": "NOT_RUN", "output": str(args.output)}, ensure_ascii=False))
        else:
            print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False))
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        parser.exit(2, "MOCK verification failed: %s\n" % exc)
    return 0 if report["edge_check_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
