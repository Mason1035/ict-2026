"""Generate synthetic reference vectors or compare an externally produced result."""
import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from telemetry_v2_intake.demo_runtime import fixture, test_only_config
from telemetry_v2_intake.runtime import FeatureRiskRuntime
from candidate_features.risk_math import risk_level

STATUS = "TEST_ONLY_NOT_CALIBRATION_OR_BOARD_ACCEPTANCE"


def load(path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key: " + key)
            result[key] = value
        return result
    def bad(value):
        raise ValueError("nonfinite JSON: " + value)
    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=pairs, parse_constant=bad)


def differences(ref, actual, path="$"):
    errors = []
    if isinstance(ref, dict):
        if not isinstance(actual, dict) or set(ref) != set(actual):
            return [path + ": object keys/type mismatch"]
        for key in ref:
            errors += differences(ref[key], actual[key], path + "." + key)
    elif isinstance(ref, list):
        if not isinstance(actual, list) or len(ref) != len(actual):
            return [path + ": list length/type mismatch"]
        for i, (a, b) in enumerate(zip(ref, actual)):
            errors += differences(a, b, path + f"[{i}]")
    elif type(ref) in (int, float) and path.rsplit(".", 1)[-1] not in ("reason_mask", "boot_id", "seq", "uptime_ms"):
        atol = 1e-4 if path.endswith(("vibration_rms", "vibration_mps2")) else 1e-3
        if (type(actual) not in (int, float) or not math.isfinite(actual)
                or not math.isfinite(ref) or abs(actual-ref) > atol + 1e-5*abs(ref)):
            errors.append(path + ": numeric tolerance exceeded/type mismatch")
    elif type(ref) != type(actual) or ref != actual:
        errors.append(path + ": exact value/type mismatch")
    return errors


def validate_risks(value, path="$"):
    errors = []
    if isinstance(value, dict):
        if set(("sensor_score", "level", "reason_mask")) <= set(value):
            score, level, mask = (value[k] for k in ("sensor_score", "level", "reason_mask"))
            if score is None:
                if level is not None or mask is not None:
                    errors.append(path + ": invalid risk must be all null")
            elif risk_level(score) is None or risk_level(score) != level:
                errors.append(path + ": score/level inconsistency")
            if mask is not None and (type(mask) is not int or not 0 <= mask <= 0xffffffff):
                errors.append(path + ": invalid uint32 mask")
        for k, v in value.items():
            errors += validate_risks(v, path + "." + k)
    elif isinstance(value, list):
        for i, v in enumerate(value):
            errors += validate_risks(v, path + f"[{i}]")
    return errors


def generate(output):
    out = Path(output)
    out.mkdir(parents=True, exist_ok=False)
    config = test_only_config()
    cases, results = [], []
    for scenario in ("normal", "abnormal", "missing"):
        payload, context = fixture(scenario=scenario)
        result = FeatureRiskRuntime(config).evaluate(payload, context=context)
        cases.append({"case_id":scenario,"payload":payload,"context":context})
        results.append({"case_id":scenario,"risk":result["risk"],"features":result["features"]})
    boundaries = []
    for edge in (0.,30.,60.,80.,100.):
        for number in (math.nextafter(edge, -math.inf), edge, math.nextafter(edge, math.inf)):
            boundaries.append({"score":number,"expected_level":risk_level(number),"score_hex":number.hex()})
    for name, doc in {"inputs.json":{"status":STATUS,"config":config,"cases":cases},
                      "expected.json":{"status":STATUS,"cases":results},
                      "binary64_boundaries.json":{"status":STATUS,"vectors":boundaries}}.items():
        (out/name).write_text(json.dumps(doc,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir()}
    (out/"manifest.json").write_text(json.dumps({"status":STATUS,"sha256":hashes},indent=2),encoding="utf-8")
    print("Generated TEST_ONLY inputs, expected results and binary64 boundary primitives:", out)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest="command",required=True)
    sub.add_parser("generate").add_argument("--output",required=True)
    c=sub.add_parser("compare")
    c.add_argument("--reference",required=True); c.add_argument("--actual",required=True)
    c.add_argument("--report",required=True)
    args=parser.parse_args()
    if args.command=="generate":
        generate(args.output); return 0
    ref,actual=load(args.reference),load(args.actual)
    if not isinstance(ref,dict) or ref.get("status") != STATUS:
        raise ValueError("reference must be TEST_ONLY")
    errors=differences(ref,actual)+validate_risks(ref)+validate_risks(actual)
    report={"status":STATUS,"passed":not errors,"errors":errors,
            "reference_sha256":hashlib.sha256(Path(args.reference).read_bytes()).hexdigest(),
            "actual_sha256":hashlib.sha256(Path(args.actual).read_bytes()).hexdigest(),
            "notice":"Comparison only; source authenticity and physical calibration not verified"}
    with Path(args.report).open("x",encoding="utf-8") as f:
        json.dump(report,f,ensure_ascii=False,indent=2)
    print("PASS" if not errors else "FAIL", "TEST_ONLY comparison; not board acceptance")
    return 1 if errors else 0


if __name__=="__main__":
    raise SystemExit(main())
