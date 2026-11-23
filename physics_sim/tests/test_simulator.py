"""Requirements, causal alignment, numerical bounds, and artifact safety."""

from copy import deepcopy
import json
import math
from pathlib import Path
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest

from physics_sim import __version__
from physics_sim.simulator.config import ConfigError, STATES, load_config, parameter_hash, validate_config
from physics_sim.simulator.hydrology import update_moisture
from physics_sim.simulator.pipeline import (
    ARTIFACT_KIND, CONTRACT_STATUS, CSV_COLUMNS, LATENT_COLUMNS, LINEAGE_COLUMNS,
    OBSERVATION_COLUMNS, OBSERVATION_SCHEMA_VERSION, QUALITY_COLUMNS, observation_features,
    save_run, simulate, validate_output,
)
from physics_sim.simulator.sensor_model import SensorModel
from physics_sim.simulator.slope_state import PhysicsState, evaluate_state

ROOT = Path(__file__).resolve().parents[2]
CONFIGS = ROOT / "physics_sim" / "configs"


def config(name="heavy_rain_failure"):
    return load_config(CONFIGS / f"{name}.yaml")


@pytest.fixture(scope="module")
def scenarios():
    return {name: simulate(config(name)) for name in ("normal", "rain_no_failure", "heavy_rain_failure")}


def test_reproducibility():
    c = config()
    before = deepcopy(c)
    first, meta1 = simulate(c)
    second, meta2 = simulate(c)
    pd.testing.assert_frame_equal(first, second, check_exact=True)
    assert meta1 == meta2
    assert c == before


def test_no_rain_stable(scenarios):
    frame, meta = scenarios["normal"]
    assert set(frame.state) == {"NORMAL"}
    assert (frame.displacement_latent == 0).all()
    assert (frame.velocity_latent == 0).all()
    assert (np.diff(frame.moisture_latent) <= 0).all()
    assert meta["failure_time_s"] is None


@pytest.mark.parametrize("name", ["rain_no_failure", "heavy_rain_failure"])
def test_rain_increases_moisture(name, scenarios):
    frame, _ = scenarios[name]
    wet = frame.loc[frame.rain_intensity > 0, "moisture_latent"]
    assert wet.iloc[-1] > wet.iloc[0]
    assert (np.diff(wet) > 0).all()


def test_no_failure_scenario(scenarios):
    frame, meta = scenarios["rain_no_failure"]
    assert "FAILURE" not in set(frame.state)
    assert frame.state.drop_duplicates().tolist() == ["NORMAL", "SATURATION"]
    assert frame.moisture_latent.max() > frame.moisture_latent.iloc[0]
    assert meta["failure_time_s"] is None


def test_failure_scenario(scenarios):
    frame, meta = scenarios["heavy_rain_failure"]
    assert frame.state.drop_duplicates().tolist() == list(STATES)
    assert frame.state.iloc[-1] == "FAILURE"
    assert meta["failure_time_s"] == frame.loc[frame.state == "FAILURE", "time_s"].iloc[0]
    assert frame.displacement_latent.iloc[-1] > 0


@pytest.mark.parametrize("name", ["normal", "rain_no_failure", "heavy_rain_failure"])
def test_moisture_bounds(name, scenarios):
    frame, _ = scenarios[name]
    numeric = frame.select_dtypes(include="number").drop(columns=[f"imu_{site}_tilt_rate_dps" for site in ("top", "toe")])
    assert np.isfinite(numeric.to_numpy(dtype=float)).all()
    assert frame[[f"imu_{site}_tilt_rate_dps" for site in ("top", "toe")]].iloc[1:].apply(np.isfinite).all().all()
    for name in ("moisture_latent", "soil_top", "soil_middle", "soil_toe"):
        assert frame[name].between(0, 1).all()


def test_output_schema(scenarios, tmp_path):
    frame, metadata = scenarios["heavy_rain_failure"]
    run = save_run(frame, metadata, tmp_path)
    saved = pd.read_csv(run / "simulation.csv", float_precision="round_trip")
    assert tuple(saved.columns) == CSV_COLUMNS
    pd.testing.assert_frame_equal(frame, saved, check_exact=True, check_dtype=False)
    assert "failure_time_s" not in frame
    assert tuple(saved.columns[:len(LINEAGE_COLUMNS)]) == LINEAGE_COLUMNS
    assert tuple(saved.columns[-len(QUALITY_COLUMNS):]) == QUALITY_COLUMNS


def test_metadata(scenarios, tmp_path):
    frame, meta = scenarios["heavy_rain_failure"]
    run = save_run(frame, meta, tmp_path)
    saved = json.loads((run / "metadata.json").read_text())
    assert set(("run_id", "is_synthetic", "generator_version", "seed", "parent_run", "parameter_hash", "failure_time_s", "config", "created_by", "output_units", "runtime", "csv_sha256", "observation_schema_version", "contract_status", "artifact_kind")) <= saved.keys()
    assert saved["is_synthetic"] is True
    assert saved["generator_version"] == __version__
    assert saved["seed"] == config()["seed"]
    assert saved["parent_run"] is None
    assert saved["parameter_hash"] == parameter_hash(saved["config"])
    assert len(saved["parameter_hash"]) == 64
    assert set(saved["output_units"]) == set(CSV_COLUMNS)
    assert saved["observation_schema_version"] == OBSERVATION_SCHEMA_VERSION
    assert saved["contract_status"] == CONTRACT_STATUS
    assert saved["artifact_kind"] == ARTIFACT_KIND
    assert __version__ == "0.1.1"
    assert saved["observation_schema_version"] == "physics_sim.observation.v0.1.1"
    assert saved["contract_status"] == "PRE_B_TRAINING_CONTRACT"
    assert saved["run_id"] == frame["run_id"].iloc[0]


def test_hash_canonical_and_sensitive():
    original = config()
    reordered = dict(reversed(list(original.items())))
    reordered["simulation"] = {"dt_s": 1, "duration_s": 600.0}
    assert parameter_hash(original) == parameter_hash(reordered)
    changed = deepcopy(original)
    changed["seed"] += 1
    assert parameter_hash(original) != parameter_hash(changed)
    changed = deepcopy(original)
    changed["soil"]["drainage_rate"] *= 2
    assert parameter_hash(original) != parameter_hash(changed)


def test_sample_lineage_is_complete_and_reproducible(tmp_path):
    c = config()
    first, first_meta = simulate(c)
    second, second_meta = simulate(c)
    assert first_meta["run_id"] == second_meta["run_id"] == f"sim_{parameter_hash(c)}"
    pd.testing.assert_frame_equal(first[list(LINEAGE_COLUMNS)], second[list(LINEAGE_COLUMNS)], check_exact=True)
    assert first["row_index"].tolist() == list(range(len(first)))
    assert not first.duplicated(["run_id", "row_index"]).any()
    for column in ("run_id", "is_synthetic", "generator_version", "seed", "parameter_hash"):
        assert first[column].eq(first_meta[column]).all()
    assert first["parent_run"].isna().all() and first_meta["parent_run"] is None
    first_dir = save_run(first, first_meta, tmp_path)
    second_dir = save_run(second, second_meta, tmp_path)
    assert first_dir != second_dir
    assert (first_dir / "simulation.csv").read_bytes() == (second_dir / "simulation.csv").read_bytes()
    saved = pd.read_csv(first_dir / "simulation.csv")
    assert saved["run_id"].eq(first_meta["run_id"]).all()
    assert saved["row_index"].tolist() == list(range(len(saved)))


def test_lineage_validation_rejects_broken_identity(scenarios, tmp_path):
    frame, metadata = scenarios["normal"]
    broken = frame.copy()
    broken.loc[1, "row_index"] = 0
    with pytest.raises(ValueError, match="row_index"):
        validate_output(broken)
    broken = frame.copy()
    broken.loc[1, "run_id"] = "different"
    with pytest.raises(ValueError, match="run_id"):
        validate_output(broken)
    wrong_meta = dict(metadata, run_id="different")
    with pytest.raises(ValueError, match="metadata"):
        save_run(frame, wrong_meta, tmp_path)
    wrong_meta = dict(metadata, contract_status="training_ready")
    with pytest.raises(ValueError, match="metadata"):
        save_run(frame, wrong_meta, tmp_path)
    assert not list(tmp_path.iterdir())


def test_parameter_hash_is_independent_of_wall_clock(monkeypatch):
    c = config()
    before = parameter_hash(c)
    monkeypatch.setattr("time.time", lambda: 1)
    assert parameter_hash(c) == before
    monkeypatch.setattr("time.time", lambda: 9999999999)
    assert parameter_hash(c) == before


def test_seed_changes_sensors_not_physics():
    c = config()
    first, _ = simulate(c)
    c["seed"] += 1
    second, _ = simulate(c)
    pd.testing.assert_frame_equal(first[list(LATENT_COLUMNS) + ["state"]], second[list(LATENT_COLUMNS) + ["state"]], check_exact=True)
    assert not observation_features(first).equals(observation_features(second))


def test_noise_does_not_control_physics():
    c = config()
    first, _ = simulate(c)
    c["sensor"]["soil_noise_std"] = 0.1
    c["sensor"]["imu_noise_std"] = 0.1
    second, _ = simulate(c)
    pd.testing.assert_frame_equal(first[list(LATENT_COLUMNS) + ["state"]], second[list(LATENT_COLUMNS) + ["state"]], check_exact=True)


def test_feature_allowlist_and_causal_future_rain():
    c = config()
    first, _ = simulate(c)
    c["rain"]["intensity"] *= 2
    second, _ = simulate(c)
    # Different future rainfall may change metadata and later states, never
    # observations at/before the beginning of the changed rain interval.
    before = first.time_s <= c["rain"]["start_s"]
    pd.testing.assert_frame_equal(observation_features(first[before]), observation_features(second[before]), check_exact=True)
    assert tuple(observation_features(first).columns) == OBSERVATION_COLUMNS
    assert not set(LINEAGE_COLUMNS + QUALITY_COLUMNS + LATENT_COLUMNS + ("state", "time_s", "rain_intensity", "failure_time_s")) & set(observation_features(first))


def test_extending_run_does_not_change_prefix():
    c = config("rain_no_failure")
    first, _ = simulate(c)
    c["simulation"]["duration_s"] += 100
    second, _ = simulate(c)
    # Full config changes its logical run identity; causal physics/observations
    # before the extension remain exactly the same.
    assert first["run_id"].iloc[0] != second["run_id"].iloc[0]
    unchanged = [column for column in CSV_COLUMNS if column not in ("run_id", "parameter_hash")]
    pd.testing.assert_frame_equal(first[unchanged], second.iloc[:len(first)][unchanged], check_exact=True)


def test_timeline_rain_boundary_and_left_integration(scenarios):
    frame, _ = scenarios["heavy_rain_failure"]
    c = config()
    dt = c["simulation"]["dt_s"]
    assert len(frame) == 601
    assert frame.time_s.iloc[-1] == 600
    assert frame.rain_intensity.iloc[29] == 0
    assert frame.rain_intensity.iloc[30] == 60
    assert frame.rain_intensity.iloc[-1] == 0
    assert frame.moisture_latent.iloc[30] < frame.moisture_latent.iloc[29]
    assert frame.moisture_latent.iloc[31] > frame.moisture_latent.iloc[30]
    expected = frame.displacement_latent.to_numpy()[:-1] + dt * frame.velocity_latent.to_numpy()[:-1]
    np.testing.assert_array_equal(frame.displacement_latent.to_numpy()[1:], expected)


def test_hydrology_closed_form_and_large_dt():
    assert update_moisture(0.5, 0, 10, 0.1, 0.02) == pytest.approx(0.5 * math.exp(-0.2))
    assert update_moisture(0.3, 0, 100, 0, 0) == 0.3
    assert update_moisture(0.3, 1000, 10000, 1, 0) == 1.0
    assert update_moisture(0.3, 0, 10000, 0, 1) == 0.0
    whole = update_moisture(0.2, 10, 10, 0.01, 0.02)
    half = update_moisture(0.2, 10, 5, 0.01, 0.02)
    assert update_moisture(half, 10, 5, 0.01, 0.02) == pytest.approx(whole)
    with pytest.raises(ValueError, match="overflow"):
        update_moisture(0.5, 1e308, 1, 1e308, 0)


def test_state_boundaries_recovery_and_absorbing_failure():
    p = config()["state_model"]
    for key, name in zip(("saturation_threshold", "creep_threshold", "slip_threshold", "failure_threshold"), STATES[1:]):
        assert evaluate_state(p[key], 90, p).state == name
    saturation = evaluate_state(p["saturation_threshold"], 90, p)
    assert evaluate_state(0, 90, p, saturation, 1).state == "NORMAL"
    failure = evaluate_state(1, 90, p)
    after = evaluate_state(0, 90, p, failure, 1)
    assert after.state == "FAILURE"
    assert after.displacement == p["failure_rate"]
    assert evaluate_state(1, 0, p).state == "NORMAL"


def test_initial_failure_is_metadata_zero():
    c = config()
    c["soil"]["initial_moisture"] = 1
    frame, meta = simulate(c)
    assert meta["failure_time_s"] == 0.0
    assert frame.displacement_latent.iloc[0] == 0


def test_noiseless_sensor_mapping_delay_and_tilt_rate():
    c = config()
    p = c["sensor"]
    p["imu_noise_std"] = p["soil_noise_std"] = p["vibration_noise_std"] = 0
    sensors = SensorModel(p, 0.2, 1, np.random.default_rng(42))
    observations = []
    for i in range(47):
        state = PhysicsState(0.2 if i == 0 else 0.6, 0.1, i * 0.001, 0.001, "CREEP")
        observations.append(sensors.observe(state))
    assert observations[1]["soil_top"] == pytest.approx(0.6)
    assert observations[20]["soil_middle"] == pytest.approx(0.2)
    assert observations[21]["soil_middle"] == pytest.approx(0.2 + 0.85 * 0.4)
    assert observations[45]["soil_toe"] == pytest.approx(0.2)
    assert observations[46]["soil_toe"] == pytest.approx(0.2 + 0.7 * 0.4)
    assert observations[0]["imu_top_tilt_rate_dps"] is None
    assert observations[0]["imu_top_tilt_rate_valid"] is False
    assert observations[1]["imu_top_tilt_rate_valid"] is True
    assert observations[1]["imu_top_tilt_deg"] == pytest.approx(0.01)
    assert observations[1]["imu_top_tilt_rate_dps"] == pytest.approx(0.01)
    assert observations[1]["imu_toe_tilt_deg"] == pytest.approx(0.015)
    assert observations[1]["imu_top_vibration_rms"] == pytest.approx(0.022)


@pytest.mark.parametrize("path,value", [
    (("simulation", "dt_s"), 0), (("simulation", "dt_s"), -1),
    (("simulation", "duration_s"), 0), (("simulation", "duration_s"), 600.5),
    (("soil", "initial_moisture"), -0.1), (("soil", "initial_moisture"), 1.1),
    (("soil", "infiltration_rate"), -1), (("soil", "drainage_rate"), float("inf")),
    (("rain", "intensity"), -1), (("rain", "type"), "unknown"),
    (("rain", "start_s"), 30.5), (("rain", "end_s"), 900),
    (("state_model", "creep_threshold"), 0.1), (("state_model", "failure_threshold"), 1.1),
    (("state_model", "failure_rate"), 0.000001),
    (("sensor", "imu_noise_std"), -1), (("sensor", "soil_noise_std"), float("nan")),
    (("sensor", "vibration_noise_std"), True),
    (("sensor", "soil_sites", "middle", "delay_s"), 0.5),
    (("sensor", "soil_sites", "toe", "response_coefficient"), 2),
    (("seed",), -1), (("seed",), 1.5), (("simulator_version",), "0.2.0"),
])
def test_invalid_config(path, value):
    c = config()
    target = c
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ConfigError):
        validate_config(c)


def test_missing_unknown_duplicate_and_yaml_types(tmp_path):
    c = config()
    del c["sensor"]["soil_noise_std"]
    with pytest.raises(ConfigError, match="missing"):
        validate_config(c)
    c = config()
    c["soil"]["infiltration_typo"] = 1
    with pytest.raises(ConfigError, match="unknown"):
        validate_config(c)
    duplicate = tmp_path / "duplicate.yaml"
    duplicate.write_text("seed: 1\nseed: 2\n")
    with pytest.raises(ConfigError, match="duplicate"):
        load_config(duplicate)
    duplicate.write_text("[]")
    with pytest.raises(ConfigError, match="mapping"):
        load_config(duplicate)


def test_output_nonfinite_rejected(scenarios):
    frame = scenarios["normal"][0].copy()
    frame.loc[0, "soil_top"] = float("inf")
    with pytest.raises(ValueError, match="NaN/Inf"):
        validate_output(frame)


def test_tilt_rate_warmup_and_nullable_csv(scenarios, tmp_path):
    frame, metadata = scenarios["normal"]
    assert frame["observation_warmup"].tolist() == [True] + [False] * (len(frame) - 1)
    for site in ("top", "toe"):
        rate = f"imu_{site}_tilt_rate_dps"
        valid = f"imu_{site}_tilt_rate_valid"
        assert pd.isna(frame[rate].iloc[0])
        assert frame[valid].tolist() == [False] + [True] * (len(frame) - 1)
        assert np.isfinite(frame[rate].iloc[1:].to_numpy(dtype=float)).all()
    run = save_run(frame, metadata, tmp_path)
    saved = pd.read_csv(run / "simulation.csv")
    validate_output(saved)
    assert pd.isna(saved["imu_top_tilt_rate_dps"].iloc[0])
    broken = frame.copy()
    broken.loc[0, "imu_top_tilt_rate_dps"] = 0
    with pytest.raises(ValueError, match="first-row null"):
        validate_output(broken)
    broken = frame.copy()
    broken.loc[1, "imu_top_tilt_rate_dps"] = float("inf")
    with pytest.raises(ValueError, match="NaN/Inf"):
        validate_output(broken)


def test_outputs_never_overwrite(scenarios, tmp_path):
    frame, metadata = scenarios["normal"]
    first = save_run(frame, metadata, tmp_path)
    before = (first / "simulation.csv").read_bytes()
    second = save_run(frame, metadata, tmp_path)
    assert first != second
    assert before == (first / "simulation.csv").read_bytes() == (second / "simulation.csv").read_bytes()


def test_nonunit_dt_preserves_rate_units_and_integration():
    c = config()
    c["simulation"]["dt_s"] = 0.5
    c["sensor"]["imu_noise_std"] = 0
    frame, _ = simulate(c)
    assert len(frame) == 1201
    assert frame.time_s.iloc[-1] == 600
    previous_v = frame.velocity_latent.to_numpy()[:-1]
    expected_d = frame.displacement_latent.to_numpy()[:-1] + previous_v * 0.5
    np.testing.assert_array_equal(frame.displacement_latent.to_numpy()[1:], expected_d)
    for site in ("top", "toe"):
        gain = c["sensor"]["imu_sites"][site]["tilt_gain_deg_per_m"]
        # Analytic noiseless rate = gain*v, independent of sampling interval.
        np.testing.assert_allclose(frame[f"imu_{site}_tilt_rate_dps"].to_numpy()[1:], gain * previous_v, rtol=1e-9, atol=1e-12)


def test_invalid_cli_creates_no_run(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text((CONFIGS / "normal.yaml").read_text().replace("dt_s: 1", "dt_s: 0"))
    output = tmp_path / "runs"
    result = subprocess.run([sys.executable, "-m", "physics_sim.scripts.run_sim", "--config", str(bad), "--output-dir", str(output)], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode != 0
    assert "simulation.dt_s: must be > 0" in result.stderr
    assert not output.exists()


def test_cli_and_plot(tmp_path):
    run = subprocess.run([sys.executable, "-m", "physics_sim.scripts.run_sim", "--config", str(CONFIGS / "normal.yaml"), "--output-dir", str(tmp_path)], cwd=ROOT, capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    directory = Path(json.loads(run.stdout)["run_dir"])
    plot = subprocess.run([sys.executable, "-m", "physics_sim.scripts.plot_run", "--csv", str(directory / "simulation.csv")], cwd=ROOT, capture_output=True, text=True)
    assert plot.returncode == 0, plot.stderr
    png = directory / "diagnostic.png"
    assert png.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    before = png.read_bytes()
    again = subprocess.run([sys.executable, "-m", "physics_sim.scripts.plot_run", "--csv", str(directory / "simulation.csv")], cwd=ROOT, capture_output=True, text=True)
    assert again.returncode != 0
    assert png.read_bytes() == before
