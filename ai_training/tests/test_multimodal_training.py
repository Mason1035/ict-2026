"""Research pipeline regressions; fixtures here are synthetic software tests only."""

from copy import deepcopy
import json
from types import SimpleNamespace

import numpy as np
import pytest

from ai_training.multimodal.forecast import RidgeForecaster, build_windows, group_split, history_features
from ai_training.multimodal.pipeline import train_branch, run_training, source_summary


def series(index, *, group=None, modality="soil", offset=0):
    channels = 1 if modality == "soil" else 6
    values = np.arange(24*channels, dtype=float).reshape(24, channels)/100+offset
    return SimpleNamespace(source_id="TEST_ONLY", run_id=f"run{index}", group_id=group or f"group{index}",
                           modality=modality, values=values, times=np.arange(24, dtype=float),
                           channel_names=("vwc_centre",) if channels == 1 else tuple(f"imu{i}" for i in range(6)),
                           units=("1",) if channels == 1 else ("source_native",)*6,
                           time_unit="source_relative", provenance={"role": "TEST_ONLY"})


def config():
    return {"history_length": 4, "train_fraction": .6, "validation_fraction": .2,
            "ridge_alphas": [.001, .1], "allow_fit_without_holdout": False}


def test_windows_causal_and_do_not_cross_recordings():
    a, b = series(0), series(1, offset=100)
    batch = build_windows([a, b], 4)
    assert len(batch) == 40
    np.testing.assert_array_equal(batch.history[0], a.values[:4])
    np.testing.assert_array_equal(batch.target[0], a.values[4])
    np.testing.assert_array_equal(batch.history[20], b.values[:4])
    assert not np.any((batch.history.min(axis=(1, 2)) < 1) & (batch.history.max(axis=(1, 2)) > 100))
    assert history_features(batch.history).shape == (40, 4)


def test_group_allocation_is_disjoint_complete_and_deterministic():
    groups = [f"date{i}" for i in range(10)]*3
    result = group_split(groups, seed=12, train_fraction=.6, validation_fraction=.2)
    assert result == group_split(groups, seed=12, train_fraction=.6, validation_fraction=.2)
    assert set(result["train"]).isdisjoint(result["validation"])
    assert set(result["test"]).isdisjoint(result["train"] + result["validation"])
    assert set().union(*map(set, result.values())) == set(groups)


def test_scaler_alpha_and_weights_never_fit_on_held_out_targets():
    items = [series(i) for i in range(10)]
    model, report = train_branch(items, config(), modality="soil", seed=4, evaluate_test=False)
    changed = deepcopy(items)
    for item in changed:
        if item.group_id in report["split_groups"]["test"]:
            item.values += 10_000
    other, other_report = train_branch(changed, config(), modality="soil", seed=4, evaluate_test=False)
    assert model.to_dict() == other.to_dict()
    assert report["metrics"]["validation"] == other_report["metrics"]["validation"]
    assert report["metrics"]["test"] is None and report["test_status"] == "SEALED"


def test_single_experiment_motion_does_not_become_independent_test():
    items = [series(i, group="one_experiment", modality="motion") for i in range(4)]
    cfg = {"history_length": 8, "ridge_alphas": [.1], "allow_fit_without_holdout": True}
    model, report = train_branch(items, cfg, modality="motion", seed=1, evaluate_test=True)
    assert model.channels == 6
    assert report["evaluation_scope"] == "TRAIN_FIT_ONLY_NO_INDEPENDENT_HOLDOUT"
    assert report["metrics"]["validation"] is report["metrics"]["test"] is None
    assert report["split_groups"]["validation"] == report["split_groups"]["test"] == []
    assert report["disaster_classification_metrics"] is None
    cfg["ridge_alphas"] = [.1, 1.0]
    with pytest.raises(ValueError, match="one fixed alpha"):
        train_branch(items, cfg, modality="motion", seed=1, evaluate_test=True)


def fitted():
    batch = build_windows([series(0)], 4)
    return RidgeForecaster().fit(batch.history, batch.target, alpha=.1, modality="soil",
                                channel_names=("vwc",), units=("1",), time_unit="source_relative"), batch


def test_json_model_round_trip_and_no_overwrite(tmp_path):
    model, batch = fitted()
    path = tmp_path / "soil.json"
    model.save(path)
    restored = RidgeForecaster.load(path)
    args = {"channel_names": ("vwc",), "units": ("1",), "time_unit": "source_relative"}
    np.testing.assert_array_equal(model.predict(batch.history, **args), restored.predict(batch.history, **args))
    with pytest.raises(FileExistsError):
        model.save(path)
    raw = json.loads(path.read_text())
    assert raw["class_labels"] is raw["alarm_thresholds"] is None
    assert raw["deployment_ready"] is False


@pytest.mark.parametrize("changes", [
    {"units": ("ADS1115_raw",)}, {"channel_names": ("soil_top_raw",)}, {"time_unit": "UTC_ms"}
])
def test_prediction_rejects_unit_time_or_channel_substitution(changes):
    model, batch = fitted()
    args = {"channel_names": ("vwc",), "units": ("1",), "time_unit": "source_relative"} | changes
    with pytest.raises(ValueError, match="mismatch"):
        model.predict(batch.history, **args)


@pytest.mark.parametrize("change", [{"scale": [0, 0, 0, 0]}, {"coefficients": [[1]]},
                                   {"deployment_ready": True}, {"class_labels": ["SLIP"]}])
def test_model_load_rejects_corruption_or_promotion(tmp_path, change):
    model, _ = fitted()
    path = tmp_path / "model.json"
    path.write_text(json.dumps(model.to_dict() | change))
    with pytest.raises(ValueError):
        RidgeForecaster.load(path)


def test_nonfinite_values_and_nonmonotone_times_rejected():
    bad = series(0)
    bad.values[4, 0] = np.nan
    with pytest.raises(ValueError, match="finite"):
        build_windows([bad], 4)
    bad = series(0)
    bad.times[4] = bad.times[3]
    with pytest.raises(ValueError, match="increase"):
        build_windows([bad], 4)


def test_explicit_research_config_and_existing_output_rejected_before_read(tmp_path):
    with pytest.raises(ValueError, match="PUBLIC_DATA_RESEARCH"):
        run_training(tmp_path / "missing", tmp_path / "output", {})
    cfg = {"schema": "zhifang.multimodal-research-config.v1", "purpose": "PUBLIC_DATA_RESEARCH", "seed": 1}
    with pytest.raises(FileExistsError):
        run_training(tmp_path / "missing", tmp_path, cfg)


def test_grouped_test_is_evaluated_only_on_explicit_release():
    _, report = train_branch([series(i) for i in range(10)], config(), modality="soil", seed=5, evaluate_test=True)
    assert report["test_status"] == "EXPLORATORY_EVALUATION_FOR_THIS_RUN"
    assert report["metrics"]["test"]["windows"] > 0
    assert report["metrics"]["test"]["persistence_rmse_per_channel"] is not None


def test_provenance_summary_preserves_ranges_without_repeating_table_audits():
    a, b = series(0), series(1)
    for item in (a, b):
        item.provenance = {"source_file": "tdr.csv", "source_record_indices": [2, 3, 4, 8],
                           "table_exclusions": {"invalid": 1}, "event_metadata": {"future_failure": 123}}
    sequences, tables = source_summary([a, b])
    assert len(tables) == 1
    assert sequences[0]["source_record_ranges_in_time_order"] == [[2, 4], [8, 8]]
    assert "event_metadata" not in sequences[0]
    assert tables["TEST_ONLY:tdr.csv"]["table_exclusions"] == {"invalid": 1}
