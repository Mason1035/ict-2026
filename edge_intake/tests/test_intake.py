"""TEST_ONLY software checks. MOCK acceptance is not real hardware evidence."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
from types import MappingProxyType

import pytest

from edge_intake import EdgeIntakeError, receive_validated_telemetry
from edge_intake.scripts.verify_mock_intake import verify_cases, write_report
import edge_intake.scripts.verify_mock_intake as mock_check


FIXTURES = Path(__file__).parent / "fixtures/a_mock"


def message(case_id="M01_NORMAL"):
    return json.loads((FIXTURES / "cases" / (case_id + ".json")).read_text(encoding="utf-8"))["messages"][0]


def freeze(value):
    if isinstance(value, dict):
        return MappingProxyType({key: freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(freeze(item) for item in value)
    return value


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


@pytest.mark.parametrize("case_id", ["M01_NORMAL", "M02_MISSING_SENSOR", "M07_RISK_NOT_CALIBRATED"])
def test_frozen_payload_and_context_preserved(case_id):
    source = message(case_id)
    context = {"source": "MOCK", "sampling_snapshot": source["sampling_snapshot"]}
    before = deepcopy(source)
    result = receive_validated_telemetry(freeze(source["payload"]), context=freeze(context))
    assert source == before
    assert result["payload"] == source["payload"]
    assert result["context"] == context
    assert result["identity"] == {key: source["payload"][key] for key in ("device_id", "boot_id", "seq")}
    assert result["payload_sha256"] == canonical_hash(source["payload"])
    assert result["source"] == "MOCK"
    assert "source" not in result["payload"]
    assert result["status"] == "ACCEPTED_BY_EDGE_INTAKE"
    assert result["downstream"] == "NOT_IMPLEMENTED"
    assert result["downstream_status"] == "DOWNSTREAM_NOT_IMPLEMENTED"
    assert result["durable"] is False


def test_missing_soil_and_uncalibrated_risk_stay_null():
    soil = receive_validated_telemetry(message("M02_MISSING_SENSOR")["payload"])
    risk = receive_validated_telemetry(message("M07_RISK_NOT_CALIBRATED")["payload"])
    assert soil["payload"]["soil"]["middle_raw"] is None
    assert risk["payload"]["risk"] == {"sensor_score": None, "level": None, "reason_mask": None}


def test_snapshots_are_isolated_from_caller_mutations():
    source = message()
    context = {"source": "MOCK", "sampling_snapshot": source["sampling_snapshot"]}
    result = receive_validated_telemetry(source["payload"], context=context)
    original_hash = result["payload_sha256"]
    source["payload"]["imu"][0]["ax"] = 123
    context["sampling_snapshot"]["soil"][0]["raw"] = 456
    assert result["payload"]["imu"][0]["ax"] != 123
    assert result["context"]["sampling_snapshot"]["soil"][0]["raw"] != 456
    assert canonical_hash(result["payload"]) == original_hash
    result["payload"]["soil"]["top_raw"] = 789
    result["context"]["sampling_snapshot"]["soil"][0]["raw"] = 999
    assert source["payload"]["soil"]["top_raw"] != 789
    assert context["sampling_snapshot"]["soil"][0]["raw"] == 456


def test_canonical_hash_is_key_order_and_context_independent():
    payload = message()["payload"]
    reordered = dict(reversed(tuple(payload.items())))
    one = receive_validated_telemetry(payload, context={"source": "MOCK", "received_at": "first"})
    two = receive_validated_telemetry(reordered, context={"source": "MOCK", "received_at": "later"})
    assert one["payload_sha256"] == two["payload_sha256"] == canonical_hash(payload)


@pytest.mark.parametrize("context", [None, {}, {"source": None}])
def test_unknown_source_is_never_invented(context):
    result = receive_validated_telemetry(message()["payload"], context=context)
    assert result["source"] is None
    assert result["context"] == context


@pytest.mark.parametrize("field,value", [
    ("schema", "zhifang.telemetry.v999"), ("schema", None),
    ("device_id", ""), ("device_id", "  "), ("device_id", 1),
    ("boot_id", "1"), ("boot_id", True), ("boot_id", -1),
    ("seq", "1"), ("seq", False), ("seq", -1), ("seq", None),
])
def test_boundary_guards_never_coerce_invalid_identity(field, value):
    payload = message()["payload"]
    payload[field] = value
    before = deepcopy(payload)
    with pytest.raises(EdgeIntakeError):
        receive_validated_telemetry(payload)
    assert payload == before


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), object(), {1, 2}])
def test_non_json_values_fail_at_boundary(value):
    payload = message()["payload"]
    payload["imu"][0]["ax"] = value
    with pytest.raises(EdgeIntakeError):
        receive_validated_telemetry(payload)


def test_cyclic_input_and_non_string_json_keys_rejected():
    payload = message()["payload"]
    payload["loop"] = payload
    with pytest.raises(EdgeIntakeError):
        receive_validated_telemetry(payload)
    del payload["loop"]
    payload[1] = "invalid key"
    with pytest.raises(EdgeIntakeError):
        receive_validated_telemetry(payload)


@pytest.mark.parametrize("context", [["MOCK"], {"source": 1}, {"source": ""}, {"source": "MOCK", "value": float("nan")}])
def test_invalid_sidecar_rejected_without_source_guess(context):
    with pytest.raises(EdgeIntakeError):
        receive_validated_telemetry(message()["payload"], context=context)


def test_four_A_mock_cases_use_real_upstream_gate():
    report = verify_cases()
    cases = {case["case_id"]: case for case in report["cases"]}
    assert report["edge_check_status"] == "PASS"
    assert report["edge_call_count"] == 3
    assert [case["edge_call_count"] for case in report["cases"]] == [1, 1, 1, 0]
    invalid = cases["M08_INVALID_SCHEMA"]
    assert len(invalid["messages"]) == 4
    assert all(row["validator"]["status"] == "REJECT" and row["edge_called"] is False and row["edge_status"] == "NOT_CALLED" and row["sampling_snapshot_check"] == "NOT_CALLED" for row in invalid["messages"])
    assert report["three_person_integration"] == "NOT_RUN"
    assert report["B_risk_consumer"] == "NOT_CALLED"
    assert report["production_validator"] == "NOT_IMPLEMENTED"


def test_evidence_creation_never_overwrites_artifact(tmp_path):
    output = tmp_path / "evidence.json"
    report = verify_cases()
    write_report(report, output)
    before = output.read_bytes()
    assert json.loads(before) == report
    with pytest.raises(FileExistsError):
        write_report({"replacement": True}, output)
    assert output.read_bytes() == before


def test_evidence_is_deterministic_for_same_code_and_snapshots():
    assert verify_cases() == verify_cases()


@pytest.mark.parametrize("location", ["payload", "context"])
def test_unencodable_utf8_rejected(location):
    payload = message()["payload"]
    context = {"source": "MOCK"}
    if location == "payload":
        payload["device_id"] = "\ud800"
    else:
        context["note"] = "\ud800"
    with pytest.raises(EdgeIntakeError, match="UTF-8"):
        receive_validated_telemetry(payload, context=context)


def test_changed_pinned_helper_rejected_before_execution(tmp_path, monkeypatch):
    fixtures = tmp_path / "a_mock"
    shutil.copytree(FIXTURES, fixtures)
    (fixtures / "runner/mock_v2_validator.py").write_text(
        "raise RuntimeError('altered helper must never execute')\n", encoding="utf-8"
    )
    monkeypatch.setattr(mock_check, "_FIXTURE_ROOT", fixtures)
    with pytest.raises(ValueError, match="source hash mismatch"):
        verify_cases()
