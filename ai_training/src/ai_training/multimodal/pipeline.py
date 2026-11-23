"""Two independently fitted public-data research branches, not a warning classifier."""

from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np

from .forecast import RidgeForecaster, build_windows, equal_group_weights, group_split, regression_metrics
from .public_data import load_lisa, load_smartstone


def _write(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def _canonical_units(series, modality):
    units = {tuple(item.units) for item in series}
    time_units = {item.time_unit for item in series}
    if len(units) != 1 or len(time_units) != 1 or any(item.modality != modality for item in series):
        raise ValueError("branch must use compatible native units and time semantics")
    if modality == "soil":
        if next(iter(units)) != ("1",) or any(len(item.channel_names) != 1 or not item.channel_names[0].startswith("vwc") for item in series):
            raise ValueError("soil branch requires documented VWC fraction, not ADC or percent aliases")
        names = ("vwc",)  # Same documented quantity, learned independently at each position.
    else:
        names = tuple(series[0].channel_names)
        if any(tuple(item.channel_names) != names for item in series):
            raise ValueError("motion channel ordering differs between series")
    return next(iter(units)), next(iter(time_units)), names


def source_summary(series):
    """Record lineage compactly; table-level exclusions are counted once."""
    sequences, tables = [], {}
    table_keys = ("doi", "url", "license", "dataset_role", "source_type", "ordering_policy",
                  "grouping_policy", "grouping_limit", "native_units_confirmed",
                  "source_time_unit_confirmed", "timecode_is_utc", "cross_probe_sync_confirmed",
                  "table_exclusions", "quarantined_sequences", "missing_source_tables")
    for item in series:
        p = item.provenance
        table_id = item.source_id + ":" + p.get("source_file", "unspecified")
        tables.setdefault(table_id, {key: p[key] for key in table_keys if key in p})
        ranges = []
        for row in p.get("source_record_indices", []):
            if ranges and row == ranges[-1][1] + 1:
                ranges[-1][1] = row
            else:
                ranges.append([row, row])
        sequences.append({"source_id": item.source_id, "run_id": item.run_id, "group_id": item.group_id,
                          "source_file": p.get("source_file"), "channel_names": list(item.channel_names),
                          "source_records": p.get("source_records"), "retained_records": len(item.values),
                          "source_record_ranges_in_time_order": ranges, "exclusions": p.get("exclusions", {}),
                          "label_status": p.get("label_status", "NOT_PROVIDED")})
    return sequences, tables


def train_branch(series, config, *, modality, seed, evaluate_test):
    units, time_unit, names = _canonical_units(series, modality)
    length = config["history_length"]
    usable = [item for item in series if len(item.values) > length]
    if not usable:
        raise ValueError(f"{modality}: no usable series")
    groups = sorted({item.group_id for item in usable})
    if len(groups) < 3:
        # Four stones in one experiment do not create independent experiments.
        if not config.get("allow_fit_without_holdout", False):
            raise ValueError(f"{modality}: insufficient independent groups")
        partitions = {"train": tuple(groups), "validation": (), "test": ()}
        evaluation_scope = "TRAIN_FIT_ONLY_NO_INDEPENDENT_HOLDOUT"
    else:
        partitions = group_split(groups, seed=seed, train_fraction=config["train_fraction"],
                                 validation_fraction=config["validation_fraction"])
        evaluation_scope = "GROUPED_PUBLIC_SOURCE_HOLDOUT_NOT_LOCAL_HARDWARE_VALIDATION"
    batches = {}
    # The group allocation precedes window extraction; windows never cross series.
    for name, selected in partitions.items():
        if selected:
            batches[name] = build_windows([item for item in usable if item.group_id in selected], length)
    train = batches["train"]
    weights = equal_group_weights(train.groups)
    alphas = config["ridge_alphas"]
    if not alphas or any(type(a) not in (int, float) or not np.isfinite(a) or a <= 0 for a in alphas):
        raise ValueError("explicit positive finite ridge_alphas required")
    if "validation" not in batches and len(alphas) != 1:
        raise ValueError("no validation groups: specify one fixed alpha, no selection on training loss")
    candidates = []
    for alpha in alphas:
        model = RidgeForecaster().fit(train.history, train.target, alpha=alpha, weights=weights,
                                     modality=modality, channel_names=names, units=units, time_unit=time_unit)
        if "validation" in batches:
            validation = batches["validation"]
            result = regression_metrics(validation, model.predict(validation.history, channel_names=names, units=units, time_unit=time_unit))
            score = float(np.mean(result["rmse_per_channel"]))
        else:
            result, score = None, 0.0
        candidates.append((score, float(alpha), model, result))
    _, alpha, model, validation_result = min(candidates, key=lambda row: (row[0], row[1]))
    train_result = regression_metrics(train, model.predict(train.history, channel_names=names, units=units, time_unit=time_unit))
    test_result = None
    if evaluate_test and "test" in batches:
        test = batches["test"]
        test_result = regression_metrics(test, model.predict(test.history, channel_names=names, units=units, time_unit=time_unit))
    sequences, tables = source_summary(series)
    report = {"modality": modality, "task": "next_recorded_observation_regression",
              "target_note": "next observed sample; variable native interval, not a fixed seconds-ahead forecast",
              "evaluation_scope": evaluation_scope, "selected_alpha": alpha,
              "selection": "validation only" if validation_result else "fixed before fit; no validation available",
              "units": list(units), "time_unit": time_unit,
              "metrics": {"train_descriptive": train_result, "validation": validation_result, "test": test_result},
              "test_status": "EXPLORATORY_EVALUATION_FOR_THIS_RUN" if test_result else ("SEALED" if "test" in batches else "UNAVAILABLE_ONLY_ONE_EXPERIMENT"),
              "input_series": len(series), "usable_series": len(usable),
              "excluded_short_series": len(series)-len(usable),
              "window_counts": {name: len(batch) for name, batch in batches.items()},
              "split_groups": {name: list(value) for name, value in partitions.items()},
              "source_run_ids": sorted({item.run_id for item in series}),
              "source_provenance": sequences, "source_table_audits": tables,
              "local_hardware_validated": False, "disaster_classification_metrics": None}
    return model, report


def run_training(data_root, output_dir, config, *, evaluate_test=False):
    if config.get("schema") != "zhifang.multimodal-research-config.v1" or config.get("purpose") != "PUBLIC_DATA_RESEARCH":
        raise ValueError("explicit PUBLIC_DATA_RESEARCH config required")
    if type(config.get("seed")) is not int or config["seed"] < 0:
        raise ValueError("nonnegative integer seed required")
    root, output = Path(data_root), Path(output_dir)
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing training run: {output}")
    soil = load_lisa(root / "lisa")
    motion = load_smartstone(root / "smartstone")
    soil_model, soil_report = train_branch(soil, config["soil"], modality="soil", seed=config["seed"], evaluate_test=evaluate_test)
    motion_model, motion_report = train_branch(motion, config["motion"], modality="motion", seed=config["seed"], evaluate_test=evaluate_test)
    # All data/model validation finishes before allocating a new output directory.
    output.mkdir(parents=True, exist_ok=False)
    soil_model.save(output / "soil_model.json")
    motion_model.save(output / "motion_model.json")
    summary = {"schema": "zhifang.multimodal-research-run.v1", "status": "PUBLIC_SENSOR_MODELS_TRAINED",
               "created_at": datetime.now(timezone.utc).isoformat(),
               "software": {"numpy": np.__version__}, "purpose": "PUBLIC_DATA_RESEARCH",
               "models": {"soil": soil_report, "motion": motion_report},
               "fusion": {"implementation": "ai_training.multimodal.fusion.fuse",
                          "status": "WAITING_FOR_LOCAL_CALIBRATION_AND_PAIRED_RUNS",
                          "trained_fusion_model": False, "thresholds": None},
               "project_class_labels": None, "production_model_replaced": False,
               "deployment_ready": False, "onnx_export": "NOT_RUN",
               "limitations": ["No local experimental CSV supplied.",
                               "Forecast regressors are not NORMAL/RAIN/SLIP classifiers or calibrated risk probabilities.",
                               "Native ADC, relative wetness and VWC are not interchangeable.",
                               "LISA date/continuation groups are conservative source groups, not proof of fully independent soil specimens.",
                               "Public holdout results are exploratory and were inspected during implementation; they are not a locked confirmatory local test.",
                               "Smartstone is one experiment: no independent validation/test or accuracy claim.",
                               "No fitted threshold or cross-source paired sensor sample was invented."]}
    _write(output / "training_config.json", config)
    _write(output / "report.json", summary)
    _write(output / "split_manifest.json", {name: summary["models"][name]["split_groups"] for name in ("soil", "motion")})
    return summary
