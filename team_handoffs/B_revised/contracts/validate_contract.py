"""Fail-closed reader for the two machine-readable B handoff contracts."""

import argparse
import json
from pathlib import Path
import sys


RULE_ID = "B_RULE_DISTILLATION_CONTRACT"
FORMAL_ID = "B_FORMAL_TRAINING_CONTRACT"
STATUS_TEST = "READY_FOR_TEST_ONLY_FRAMEWORK_SMOKE_TEST"
STATUS_FORMAL_BLOCKED = "NOT_READY_FOR_FORMAL_TRAINING"
FORBIDDEN_MINIMUM = {
    "synthetic_source", "scenario", "label_source", "run_id", "group_id", "seed",
    "parameter_hash", "parent_run", "failure_time", "future_derived", "label",
}
TEST_FEATURES_V1 = [
    "soil_moisture_delta_pp", "soil_moisture_slope_pp_per_min",
    "tilt_median_deviation_deg", "tilt_min_abs_deviation_deg",
]


def _require(condition, message):
    if not condition:
        raise ValueError(f"invalid B handoff contract: {message}; correct the versioned source, never infer a default")


def _unique_pairs(pairs):
    value = {}
    for key, item in pairs:
        _require(key not in value, f"duplicate JSON key {key}")
        value[key] = item
    return value


def read_contract(path):
    def nonfinite(value):
        raise ValueError(f"non-finite JSON constant {value} is prohibited")
    result = json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=_unique_pairs,
                        parse_constant=nonfinite)
    _require(isinstance(result, dict), "root must be an object")
    return result


def validate_contract(contract):
    _require(isinstance(contract, dict), "root must be an object")
    kind = contract.get("contract_id")
    _require(kind in (RULE_ID, FORMAL_ID), "unknown contract_id")
    _require(isinstance(contract.get("contract_version"), str) and bool(contract["contract_version"]),
             "missing contract_version")
    _require(contract.get("owner") == "B" and contract.get("consumer") == "C", "owner/consumer boundary")
    _require(contract.get("training_ready") is False and contract.get("formal_training_ready") is False,
             "formal training may not be asserted by this unapproved handoff")
    for key in ("real_data_ready", "formal_feature_contract_ready", "formal_label_contract_ready", "formal_split_ready"):
        _require(contract.get(key) is False, f"{key} cannot be asserted without A/B handoff")

    if kind == RULE_ID:
        _require(contract["contract_version"] == "1.0-test-only" and contract.get("status") == "TEST_ONLY"
                 and contract.get("training_scope") == "RULE_DISTILLATION_TEST_ONLY", "unknown TEST_ONLY contract version/status")
        _require(set(contract.get("declarations", [])) ==
                 {"TEST_ONLY", "NOT_PROJECT_TRAINING_DATA", "NOT_APPROVED_FORMAL_CONTRACT"}, "TEST_ONLY declarations")
        _require(contract.get("synthetic_source") == "b_rule_distillation_fixture"
                 and contract.get("physics_inspired") is False, "synthetic source must remain rule distillation")
        features = contract.get("model_features")
        provenance = contract.get("provenance_fields")
        forbidden = contract.get("forbidden_model_features")
        _require(isinstance(features, list) and len(features) == 4 and all(isinstance(f, str) and f for f in features)
                 and len(set(features)) == len(features), "ordered test feature list")
        _require(features == TEST_FEATURES_V1, "feature order changed under TEST_ONLY.v1; version and generator must change together")
        _require(isinstance(provenance, list) and len(provenance) == len(set(provenance)), "provenance list")
        _require(isinstance(forbidden, list) and FORBIDDEN_MINIMUM <= set(forbidden), "forbidden field list")
        _require(not set(features) & (set(provenance) | set(forbidden)), "model_features overlap provenance/forbidden fields")
        _require(set(provenance) <= set(forbidden), "all provenance fields must be forbidden as model input")
        _require(set(contract.get("feature_units", {})) == set(features), "feature units/order metadata")
        _require(contract.get("label_name") == "label"
                 and contract.get("label_mapping") == {"normal": 0, "attention": 1, "warning": 1, "unknown": None},
                 "rule imitation label and unknown exclusion")
        _require(contract.get("window", {}).get("scope") == "TEST_ONLY_RULE_DISTILLATION"
                 and contract.get("split", {}).get("scope") == "TEST_ONLY_GROUP_SPLIT"
                 and contract["split"].get("formal_split_manifest") is None, "demo window/split must not claim formal status")
        window = contract["window"]
        split = contract["split"]
        _require(window.get("records_per_window") == 6
                 and window.get("baseline_sequences") == [1, 2, 3]
                 and window.get("current_sequences") == [4, 5, 6]
                 and window.get("sample_interval_seconds") == 10
                 and window.get("one_window_per_generated_group") is True,
                 "TEST_ONLY.v1 window drift; release a new version before changing it")
        _require(split.get("default_seed") == 20260925
                 and split.get("ratios") == {"train": 0.7, "validation": 0.15, "test": 0.15}
                 and split.get("method") == "deterministic stratified group split", "TEST_ONLY.v1 split drift")
        schema = contract.get("csv_schema", {})
        _require(schema.get("dataset_all.csv", [])[-len(features):] == features
                 and schema.get("train.csv/validation.csv/test.csv", [])[-len(features):] == features,
                 "CSV model feature order differs from contract")
        return {"contract_id": kind, "contract_version": contract["contract_version"],
                "status": STATUS_TEST, "formal_training_ready": False,
                "waiting_for": ["WAITING_FOR_A", "WAITING_FOR_B"]}

    _require(contract["contract_version"] == "0.1-draft" and contract.get("status") == "DRAFT"
             and contract.get("training_scope") == "FORMAL_PROJECT_TRAINING_UNRESOLVED",
             "unknown formal draft version/status; no approved version is registered")
    feature = contract.get("feature_contract")
    window = contract.get("window_contract")
    split = contract.get("split_contract")
    real = contract.get("real_data_requirements")
    _require(isinstance(feature, dict) and isinstance(window, dict) and isinstance(split, dict)
             and isinstance(real, dict), "missing formal contract sections")
    _require(window.get("causal") is True and split.get("group_keys") == ["run_id", "parent_run"],
             "causal/grouping boundary from shared contract")
    _require(real.get("status") == "WAITING_FOR_A_REAL_DATA", "A real data handoff is not yet evidenced")
    _require(contract.get("candidate_status") == "PENDING_FORMALIZATION_NOT_ORDERED_FEATURES", "candidate feature status")
    unresolved = []
    for name in ("feature_version", "ordered_features", "units", "dtype", "mask_semantics", "coordinate_semantics", "sampling_alignment", "validity_requirements"):
        if feature.get(name) is None:
            unresolved.append("feature_contract." + name)
    for name in ("window_length", "stride", "warmup_policy", "gap_policy", "padding_policy"):
        if window.get(name) is None:
            unresolved.append("window_contract." + name)
    for section in ("label_contract", "normalization_contract", "metrics_contract", "synthetic_constraints"):
        if contract.get(section) is None:
            unresolved.append(section)
    for name in ("manifest", "independent_real_test_protocol"):
        if split.get(name) is None:
            unresolved.append("split_contract." + name)
    if contract.get("leakage_rules", {}).get("formal_field_rules") is None:
        unresolved.append("leakage_rules.formal_field_rules")
    _require(bool(unresolved), "draft cannot become an approved contract by filling fields; versioned B review required")
    return {"contract_id": kind, "contract_version": contract["contract_version"],
            "status": STATUS_FORMAL_BLOCKED, "formal_training_ready": False,
            "waiting_for": ["WAITING_FOR_A", "WAITING_FOR_B"], "unresolved_fields": unresolved}


def validate_contract_file(path):
    return validate_contract(read_contract(path))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Check B handoff readiness without enabling formal training")
    parser.add_argument("contract", type=Path)
    args = parser.parse_args(argv)
    try:
        result = validate_contract_file(args.contract)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "INVALID_CONTRACT", "reason": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
