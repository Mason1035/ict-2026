"""Local TEST_ONLY / MOCK_ONLY runner. Never declares three-person integration success."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import uuid

import edge_handoff
import risk_handoff
from mock_loader import SUPPORTED_CASES, check_snapshot, freeze, load_case, payload_hash
from mock_v2_validator import validate

RUNNER_VERSION = "0.1.0"
ROOT = Path(__file__).resolve().parents[3]
M08_ERRORS = (("payload.schema", "SCHEMA_NAME"), ("payload.boot_id", "TYPE"),
              ("payload.seq", "REQUIRED"), ("payload.soil.middle_raw", "TYPE"))


def now():
    return datetime.now(timezone.utc).isoformat()


def _invoke(consumer, payload, context):
    try:
        return consumer(payload, context=context)
    except Exception as exc:
        # Preserve the failure, and still allow the independent sibling consumer.
        return {"status": "FAIL", "error": type(exc).__name__ + ": " + str(exc)}


def run_case(loaded, *, risk_consumer=risk_handoff.receive_validated,
             edge_consumer=edge_handoff.receive_validated):
    """Execute only the four supported cases; observations drive all actual counts."""
    document = loaded.document
    case_id = document["case_id"]
    if case_id not in SUPPORTED_CASES:
        raise ValueError("Unsupported case: " + case_id)
    negative = case_id == "M08_INVALID_SCHEMA"
    rows = []
    for index, message in enumerate(document["messages"]):
        row = {"message_index": index, "source": document.get("source"),
               "original_message": message, "validator_result": {},
               "snapshot_check": {"status": "NOT_CALLED"},
               "risk_handoff_result": {"status": "NOT_CALLED"},
               "edge_handoff_result": {"status": "NOT_CALLED"},
               "risk_handoff_called": False, "edge_handoff_called": False,
               "same_payload_object": False, "checks": {}}
        source_ok = (document.get("source") == "MOCK" and isinstance(message, dict)
                     and message.get("source") == "MOCK")
        if not source_ok:
            result = {"status": "REJECT", "errors": [
                {"path": "source", "code": "SOURCE", "detail": "Case and message must retain source=MOCK"}]}
            row["source_check"] = "REJECT"
        else:
            row["source_check"] = "ACCEPT"
            result = validate(message.get("payload"))
        row["validator_result"] = result

        if result["status"] == "ACCEPT":
            payload = message["payload"]
            snapshot = message.get("sampling_snapshot")
            errors = check_snapshot(snapshot, payload)
            row["snapshot_check"] = {"status": "FAIL" if errors else "PASS", "errors": errors,
                                     "scope": "TEST_ONLY_MAPPING_NOT_PRODUCTION_VALIDITY"}
            if not errors:
                # Freeze ONCE, then pass the identical object to two sibling consumers.
                shared_payload = freeze(payload)
                context = freeze({"source": "MOCK", "case_id": case_id,
                                  "sampling_snapshot": snapshot, "scope": "TEST_ONLY"})
                digest = payload_hash(shared_payload)
                risk_input = shared_payload
                edge_input = shared_payload
                row["same_payload_object"] = risk_input is edge_input
                row["risk_handoff_called"] = True
                row["risk_handoff_result"] = _invoke(risk_consumer, risk_input, context)
                row["edge_handoff_called"] = True
                row["edge_handoff_result"] = _invoke(edge_consumer, edge_input, context)
                risk = row["risk_handoff_result"]
                edge = row["edge_handoff_result"]
                expected_projection = {
                    "identity": {k: payload[k] for k in ("device_id", "boot_id", "seq")},
                    "time": {k: payload[k] for k in ("uptime_ms", "timestamp_ms", "time_synced")},
                    **{k: payload[k] for k in ("imu", "soil", "risk", "system")},
                }
                row["checks"].update({
                    "shared_payload_unchanged": payload_hash(shared_payload) == digest,
                    "same_payload_object": row["same_payload_object"],
                    "risk_projection_preserved": risk.get("status") == "ACCEPTED" and risk.get("projection") == expected_projection,
                    "sidecar_preserved": risk.get("test_only_sidecar", {}).get("sampling_snapshot") == snapshot,
                    "edge_payload_preserved": edge.get("status") == "ACCEPTED" and edge.get("payload") == payload,
                    "consumer_hashes_match": risk.get("payload_sha256") == edge.get("payload_sha256") == digest,
                    "mock_source_retained": risk.get("source") == edge.get("source") == "MOCK",
                    "risk_null_preserved": payload["risk"] == {"sensor_score": None, "level": None, "reason_mask": None},
                })
                if case_id == "M02_MISSING_SENSOR":
                    side = risk.get("test_only_sidecar", {}).get("sampling_snapshot", {})
                    soil = side.get("soil", [])
                    row["checks"]["middle_missing_preserved"] = (
                        risk.get("projection", {}).get("soil", {}).get("middle_raw", "MISSING") is None
                        and len(soil) == 3 and soil[1]["validity"] == "Unavailable"
                        and soil[1]["raw"] is None)
                if case_id == "M07_RISK_NOT_CALIBRATED":
                    row["checks"]["all_observations_valid_without_fabricated_risk"] = (
                        all(s["validity"] == "Valid" for group in snapshot.values() for s in group)
                        and payload["system"]["sensor_degraded"] is True)

        if negative:
            expected_error = M08_ERRORS[index] if index < len(M08_ERRORS) else (None, None)
            row["expected"] = {"validator": "REJECT", "error_path": expected_error[0],
                               "error_code": expected_error[1], "handoffs": "NOT_CALLED"}
            row["checks"].update({
                "rejected_for_expected_error": result["status"] == "REJECT" and any(
                    (e["path"], e["code"]) == expected_error for e in result["errors"]),
                "no_snapshot_check_before_rejection": row["snapshot_check"]["status"] == "NOT_CALLED",
                "risk_handoff_not_called": row["risk_handoff_result"]["status"] == "NOT_CALLED",
                "edge_handoff_not_called": row["edge_handoff_result"]["status"] == "NOT_CALLED",
            })
        else:
            row["expected"] = {"validator": "ACCEPT", "handoffs": "preserve inputs", "risk": "null"}
            row["checks"].update({"validator_accepted": result["status"] == "ACCEPT",
                                  "snapshot_mapping_checked": row["snapshot_check"]["status"] == "PASS",
                                  "both_handoffs_called": row["risk_handoff_result"]["status"] != "NOT_CALLED"
                                  and row["edge_handoff_result"]["status"] != "NOT_CALLED"})
        row["local_status"] = "PASS" if all(row["checks"].values()) else "FAIL"
        rows.append(row)

    actual = {
        "message_count": len(rows),
        "accepted_message_count": sum(r["validator_result"]["status"] == "ACCEPT" for r in rows),
        "rejected_message_count": sum(r["validator_result"]["status"] == "REJECT" for r in rows),
        "risk_handoff_call_count": sum(r["risk_handoff_called"] for r in rows),
        "edge_handoff_call_count": sum(r["edge_handoff_called"] for r in rows),
    }
    expected = {"message_count": 4 if negative else 1, "accepted_message_count": 0 if negative else 1,
                "rejected_message_count": 4 if negative else 0,
                "risk_handoff_call_count": 0 if negative else 1, "edge_handoff_call_count": 0 if negative else 1}
    passed = actual == expected and all(r["local_status"] == "PASS" for r in rows)
    return {
        "case_id": case_id, "source": "MOCK", "input_file": str(loaded.path),
        "input_sha256": loaded.input_sha256, "execution_time": now(),
        "scope": "LOCAL_TEST_ONLY_MOCK_RUNNER", "expected": expected, "actual": actual,
        "messages": rows, "overall_status": "LOCAL_RUNNER_PASS" if passed else "FAIL",
        "validator_expectations": "VALIDATOR_PASS" if all(
            r["checks"].get("rejected_for_expected_error", r["checks"].get("validator_accepted", False)) for r in rows
        ) and len(rows) == expected["message_count"] else "FAIL",
        "handoff_expectations": ("NOT_CALLED" if negative and actual["risk_handoff_call_count"] == actual["edge_handoff_call_count"] == 0
                                 else "HANDOFF_PASS" if passed and not negative else "FAIL"),
        "formal_risk_execution": "BLOCKED / NOT_INTEGRATED",
        "production_validator": "NOT_IMPLEMENTED", "production_edge_intake": "NOT_IMPLEMENTED",
        "three_person_integration": "BLOCKED / NOT_INTEGRATED",
        "open_interface_gaps": ["G%02d" % i for i in range(1, 10)],
        "notes": ["PASS labels cover only actually executed local checks; no formal Risk algorithm called.",
                  "M08 rejections are validator observations; fixture expected_behavior is not used as actual counts.",
                  "TEST_ONLY sidecar does not solve G02/G03/G04; no gap is closed.",
                  "Local Mock Runner success is not THREE_PERSON_INTEGRATION_PASS."],
    }


def version_evidence(root):
    def git(*args):
        try:
            return subprocess.check_output(
                ["git", "--no-optional-locks", "-c", "safe.directory=" + root.as_posix(),
                 "-C", str(root), *args], stderr=subprocess.STDOUT).decode("utf-8").strip()
        except (OSError, subprocess.CalledProcessError):
            return "UNAVAILABLE"
    runner = Path(__file__).resolve().parent
    files = sorted(list(runner.glob("*.py")) + list(runner.glob("*.md")))
    return {"runner_version": RUNNER_VERSION, "git_commit": git("rev-parse", "HEAD"),
            "git_branch": git("branch", "--show-current"), "git_status_before_run": git("status", "--porcelain"),
            "runner_source_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
            "python_version": platform.python_version(), "python_executable": sys.executable}


def write_json(path, document):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(document, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", action="append", choices=SUPPORTED_CASES,
                        help="Repeat to select cases; default M01/M02/M07/M08 only")
    args = parser.parse_args(argv)
    selected = list(dict.fromkeys(args.case or SUPPORTED_CASES))
    evidence = version_evidence(ROOT)
    directory = ROOT / "experiments/mock_interface/results" / (
        "local_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8])
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "inputs").mkdir()
    records = []
    for case_id in selected:
        path = ROOT / "experiments/mock_interface/cases" / (case_id + ".json")
        raw = path.read_bytes()
        # Preserve exact original evidence, including deliberately invalid payloads.
        with (directory / "inputs" / path.name).open("xb") as stream:
            stream.write(raw)
        try:
            loaded = load_case(path)
            if loaded.input_bytes != raw:
                raise ValueError("Input changed during loading")
            report = run_case(loaded)
        except Exception as exc:
            report = {"case_id": case_id, "input_file": str(path),
                      "input_sha256": hashlib.sha256(raw).hexdigest(), "execution_time": now(),
                      "overall_status": "FAIL", "error": type(exc).__name__ + ": " + str(exc),
                      "three_person_integration": "BLOCKED / NOT_INTEGRATED"}
        report["execution"] = evidence
        report["invocation"] = [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]]
        report["original_input_evidence"] = "inputs/" + path.name
        write_json(directory / (case_id + ".result.json"), report)
        records.append({"case_id": case_id, "overall_status": report["overall_status"],
                        "actual": report.get("actual"), "report": case_id + ".result.json"})
    passed = all(r["overall_status"] == "LOCAL_RUNNER_PASS" for r in records)
    summary = {"scope": "TEST_ONLY / MOCK_ONLY", "execution_time": now(), "execution": evidence,
               "cases": records, "overall_status": "LOCAL_RUNNER_PASS" if passed else "FAIL",
               "three_person_integration": "BLOCKED / NOT_INTEGRATED",
               "notes": "本轮 Local Mock Runner 的通过不等于完整三人 Mock Integration PASS。"}
    write_json(directory / "summary.json", summary)
    print(json.dumps({"results_directory": str(directory), **summary}, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
