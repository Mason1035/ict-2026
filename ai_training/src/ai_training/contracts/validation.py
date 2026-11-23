"""Fail closed on missing policy, unsafe feature sources or unsupported contracts."""

from dataclasses import fields
from pathlib import Path
import math
import re

from ai_training.errors import ContractNotReadyError, LeakageError
from ai_training.training.reproducibility import read_json, canonical_bytes
from .schemas import TrainingContract, SplitAssignment, SplitManifest

ENVELOPE_VERSION = "ai_training.contract-envelope.v0.1"
TEST_DECLARATIONS = {"TEST_ONLY", "NOT_PROJECT_CONTRACT", "NOT_APPROVED_BY_B"}
FORBIDDEN_INPUTS = frozenset((
    "run_id", "row_index", "device_id", "boot_id", "seq", "seed", "training_seed",
    "parameter_hash", "parent_run", "is_synthetic", "source_type", "generator_version",
    "dataset_version", "feature_version", "split", "label", "state", "failure_time", "failure_time_s",
    "moisture_latent", "instability_drive", "displacement_latent", "velocity_latent",
    "scenario", "synthetic_source", "group_id", "sample_id", "node_id", "teacher_risk_level",
    "risk_level", "reasons", "source_rule_version", "source_rule_sha256", "generator_seed",
    "timestamp", "sequence", "source", "battery_pct",
    "generator_scenario", "random_seed",
))


def require(condition, message):
    if not condition:
        raise ContractNotReadyError(f"{message}; no fallback is allowed; obtain/fix B's versioned contract")


def validate_feature_name(name):
    key = name.casefold() if isinstance(name, str) else ""
    if (not key or key in FORBIDDEN_INPUTS or "future" in key or "failure_time" in key
            or re.search(r"(^|_)label($|_)", key)):
        raise LeakageError(f"feature {name!r} is provenance/label/future-derived; remove it from X and retain it in metadata")


def validate_contract(contract, *, test_only=False):
    require(isinstance(contract, TrainingContract), "Training Contract missing")
    c = contract
    require(c.schema_version == ENVELOPE_VERSION, "unknown contract schema version")
    required = ("contract_version", "feature_version", "ordered_features", "feature_units", "feature_sources",
                "feature_lookahead_s", "dtype", "mask_semantics", "coordinate_semantics", "sampling_alignment",
                "window", "label", "split_manifest", "normalization", "metrics", "synthetic_constraints", "nonfinite_policy")
    for field in required:
        require(bool(getattr(c, field)), f"missing {field}")
    # No approved B machine contract has been received. A status string or a
    # caller's approval claim must not activate a guessed project interpreter.
    if not test_only:
        raise ContractNotReadyError("formal training blocked: WAITING_FOR_A / WAITING_FOR_B; publish and integrate B's contract before training")
    require(c.contract_version == "TEST_ONLY.v1", "unsupported contract version")
    require(c.status == "TEST_ONLY" and c.approved_by is None
            and set(c.declarations) == TEST_DECLARATIONS, "contract is not an isolated TEST_ONLY fixture")
    require(isinstance(c.ordered_features, tuple) and len(set(c.ordered_features)) == len(c.ordered_features), "duplicate/malformed feature order")
    for name in c.ordered_features:
        validate_feature_name(name)
    for mapping in (c.feature_units, c.feature_sources, c.feature_lookahead_s):
        require(isinstance(mapping, dict) and set(mapping) == set(c.ordered_features), "feature metadata/order mismatch")
    for name in c.ordered_features:
        require(isinstance(c.feature_units[name], str) and bool(c.feature_units[name]), "missing feature unit")
        sources = c.feature_sources[name]
        require(isinstance(sources, (list, tuple)) and bool(sources), "missing feature source lineage")
        for source in sources:
            validate_feature_name(source)
        lookahead = c.feature_lookahead_s[name]
        if type(lookahead) not in (int, float) or not math.isfinite(lookahead) or lookahead != 0:
            raise LeakageError("noncausal feature lookahead; use only past/current observations for X")
    require(c.dtype in ("float32", "float64"), "unsupported numeric dtype")
    require(c.nonfinite_policy == "reject", "non-finite handling not implemented; provide a supported policy")
    require(isinstance(c.mask_semantics, dict) and bool(c.mask_semantics), "invalid mask semantics")
    require(set(c.mask_semantics.values()) <= {"valid", "missing", "padded", "unavailable"}, "unknown mask state")
    require(all(isinstance(k, str) and k for k in c.mask_semantics), "mask codes must be explicit strings")
    require(isinstance(c.window, dict) and c.window.get("causal") is True, "causal window required")
    require(set(c.window) == {"length", "stride", "causal", "warmup", "gap_handling", "padding_policy"}, "incomplete window contract")
    require(all(type(c.window[k]) is int and c.window[k] > 0 for k in ("length", "stride")), "invalid test window size")
    require(c.window["warmup"] == "reject_incomplete" and c.window["gap_handling"] == "reject" and c.window["padding_policy"] == "none", "unsupported test window policy")
    require(c.label == {"kind": "TEST_ONLY.scalar_regression", "definition": "toy target; no project meaning"}, "unsupported/missing Label contract")
    require(c.normalization == {"implementation": "TEST_ONLY.identity", "fit_split": "train"}, "unsupported normalization contract")
    require(c.sampling_alignment == {"mode": "TEST_ONLY.prealigned", "dt": 1.0}, "unsupported alignment contract")
    require(c.synthetic_constraints == {"usage": "TEST_ONLY", "allowed_sources": ["SYNTHETIC"]}, "unsupported synthetic constraints")
    require(isinstance(c.metrics, tuple) and len(set(c.metrics)) == len(c.metrics)
            and all(isinstance(m, str) and m for m in c.metrics), "invalid metrics contract")
    require(not set(c.metrics) & {"epoch", "step", "train_loss"}, "metric name collides with training log fields")
    require(isinstance(c.split_manifest, SplitManifest), "missing Split Manifest")
    validate_no_group_leakage(c.split_manifest)
    canonical_bytes(c.to_dict())
    return c


def validate_no_group_leakage(manifest):
    require(isinstance(manifest, SplitManifest) and bool(manifest.assignments), "missing Split Manifest")
    require(bool(manifest.version) and bool(manifest.dataset_version), "missing split/dataset version")
    runs = {}
    groups = {}
    for item in manifest.assignments:
        require(bool(item.run_id) and item.split in ("train", "validation", "test"), "invalid split assignment")
        require(item.source_type in ("REAL", "SYNTHETIC"), "unknown source type")
        if item.run_id in runs:
            raise LeakageError("duplicate run in Split Manifest; assign every run exactly once before windowing")
        runs[item.run_id] = item
        if item.group_id is not None:
            if item.group_id in groups and groups[item.group_id] != item.split:
                raise LeakageError("group crosses splits; keep related runs in one split")
            groups[item.group_id] = item.split
    # Check every parent edge, including multi-generation ancestors. Requiring
    # source-only ancestors in the manifest prevents incomplete lineage bypasses.
    for item in manifest.assignments:
        seen = {item.run_id}
        parent = item.parent_run
        while parent is not None:
            if parent in seen:
                raise LeakageError("cyclic parent_run; correct source lineage before splitting")
            require(parent in runs, "parent_run absent from Split Manifest")
            ancestor = runs[parent]
            if ancestor.split != item.split:
                raise LeakageError("parent_run crosses splits; keep mother run and all descendants together")
            seen.add(parent)
            parent = ancestor.parent_run
    return runs


def load_training_contract(path, *, test_only=False):
    require(path is not None and Path(path).is_file(), "Training Contract file missing")
    raw = read_json(path)
    require(isinstance(raw, dict), "contract must be a JSON object")
    # Recognize the upstream draft without interpreting candidate features as
    # approved science. The B reader reports details; this execution gate stays shut.
    if raw.get("contract_id") == "B_FORMAL_TRAINING_CONTRACT":
        from .b_handoff import reject_formal_draft
        reject_formal_draft(raw)
    if raw.get("contract_id") == "B_RULE_DISTILLATION_CONTRACT":
        from ai_training.errors import FormalTrainingNotAllowedError
        raise FormalTrainingNotAllowedError(
            "This fixture is TEST_ONLY and cannot be used as formal project training data. "
            "Use BRuleFixtureReader for isolated artifact checks; do not coerce it into TEST_ONLY.v1.")
    require(not (set(raw) - {f.name for f in fields(TrainingContract)}), "unknown contract fields")
    try:
        split = raw.get("split_manifest")
        if isinstance(split, dict):
            raw["split_manifest"] = SplitManifest(split["version"], split["dataset_version"],
                                                  tuple(SplitAssignment(**a) for a in split["assignments"]))
        for name in ("ordered_features", "metrics", "declarations"):
            if raw.get(name) is not None:
                require(isinstance(raw[name], list), f"{name} must be an ordered list")
                raw[name] = tuple(raw[name])
        return validate_contract(TrainingContract(**raw), test_only=test_only)
    except (KeyError, TypeError) as exc:
        raise ContractNotReadyError("malformed contract structure; fix the external contract, do not infer defaults") from exc
