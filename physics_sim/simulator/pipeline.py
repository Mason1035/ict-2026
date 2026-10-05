"""Validated causal simulation, schema boundary, and non-overwriting persistence."""

import hashlib
import json
import platform
import re
from importlib.metadata import version
from pathlib import Path
import tempfile

import numpy as np
import pandas as pd

from physics_sim import __version__
from .config import STATES, grid_steps, parameter_hash, validate_config
from .hydrology import update_moisture
from .sensor_model import SensorModel
from .slope_state import evaluate_state

OBSERVATION_COLUMNS = (
    "soil_top", "soil_middle", "soil_toe",
    "imu_top_tilt_deg", "imu_top_tilt_rate_dps", "imu_top_vibration_rms",
    "imu_toe_tilt_deg", "imu_toe_tilt_rate_dps", "imu_toe_vibration_rms",
)
LINEAGE_COLUMNS = (
    "run_id", "row_index", "is_synthetic", "generator_version", "seed", "parameter_hash", "parent_run",
)
QUALITY_COLUMNS = ("observation_warmup", "imu_top_tilt_rate_valid", "imu_toe_tilt_rate_valid")
LATENT_COLUMNS = ("moisture_latent", "instability_drive", "displacement_latent", "velocity_latent")
CSV_COLUMNS = LINEAGE_COLUMNS + ("time_s", "rain_intensity", "state") + LATENT_COLUMNS + OBSERVATION_COLUMNS + QUALITY_COLUMNS
OBSERVATION_SCHEMA_VERSION = "physics_sim.observation.v0.1.1"
CONTRACT_STATUS = "PRE_B_TRAINING_CONTRACT"
ARTIFACT_KIND = "simulator_observation_csv"
OUTPUT_UNITS = {
    "run_id": "logical synthetic run identity", "row_index": "zero-based row identity",
    "is_synthetic": "boolean source flag", "generator_version": "version string",
    "seed": "numpy Generator seed", "parameter_hash": "SHA-256 of normalized config",
    "parent_run": "nullable source run identity",
    "time_s": "s", "rain_intensity": "mm/h", "state": "synthetic label",
    "moisture_latent": "normalized [0,1] (not VWC)", "instability_drive": "dimensionless",
    "displacement_latent": "m (synthetic latent)", "velocity_latent": "m/s (synthetic latent)",
    **{name: "normalized [0,1] (not VWC)" for name in OBSERVATION_COLUMNS if name.startswith("soil_")},
    **{name: ("deg/s" if name.endswith("_dps") else "deg" if name.endswith("_deg") else "m/s^2 (synthetic RMS proxy)")
       for name in OBSERVATION_COLUMNS if name.startswith("imu_")},
    "observation_warmup": "boolean; true only until prior tilt exists",
    "imu_top_tilt_rate_valid": "boolean", "imu_toe_tilt_rate_valid": "boolean",
}


def observation_features(frame):
    """Return only observation proxies; legacy name does not imply B feature approval.

    The allowlist excludes lineage, labels, rainfall and latent D. The first
    tilt rates remain null; callers must also inspect the validity columns.
    B owns any later feature/window/label contract and causal split policy.
    """
    return frame.loc[:, list(OBSERVATION_COLUMNS)].copy()


def validate_output(frame):
    if tuple(frame.columns) != CSV_COLUMNS or frame.empty:
        raise ValueError("output: invalid schema or empty run")
    # The sole nullable observations are the first tilt-rate values. CSV uses
    # empty cells for these unknowns; all other numeric observations must be
    # finite, and infinity is invalid even where null is permitted.
    rate_columns = ("imu_top_tilt_rate_dps", "imu_toe_tilt_rate_dps")
    numeric_columns = ("row_index", "seed", "time_s", "rain_intensity") + LATENT_COLUMNS + OBSERVATION_COLUMNS
    try:
        numeric = frame[list(numeric_columns)].to_numpy(dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError("output: invalid numeric field") from exc
    if np.isinf(numeric).any():
        raise ValueError("output: NaN/Inf detected")
    for column in numeric_columns:
        if column not in rate_columns and not np.isfinite(frame[column].to_numpy(dtype=float)).all():
            raise ValueError(f"output: NaN/Inf detected in {column}")
    if not re.fullmatch(r"[0-9a-f]{64}", str(frame["parameter_hash"].iloc[0])):
        raise ValueError("output: invalid parameter_hash")
    param_hash = frame["parameter_hash"].iloc[0]
    if not frame["parameter_hash"].eq(param_hash).all() or not frame["run_id"].eq(f"sim_{param_hash}").all():
        raise ValueError("output: inconsistent run_id or parameter_hash")
    if not np.array_equal(frame["row_index"].to_numpy(), np.arange(len(frame))):
        raise ValueError("output: row_index must be consecutive from zero")
    if not frame["is_synthetic"].map(lambda value: type(value) in (bool, np.bool_) and value).all():
        raise ValueError("output: is_synthetic must be true")
    if not frame["generator_version"].eq(__version__).all() or not frame["parent_run"].isna().all():
        raise ValueError("output: generator_version or parent_run mismatch")
    seed = frame["seed"].iloc[0]
    if isinstance(seed, (bool, np.bool_)) or not isinstance(seed, (int, np.integer)) or seed < 0 or not frame["seed"].eq(seed).all():
        raise ValueError("output: invalid seed")
    for column in QUALITY_COLUMNS:
        if not frame[column].map(lambda value: type(value) in (bool, np.bool_)).all():
            raise ValueError(f"output: {column} must be boolean")
    expected_warmup = np.arange(len(frame)) == 0
    if not np.array_equal(frame["observation_warmup"].to_numpy(), expected_warmup):
        raise ValueError("output: invalid warmup sequence")
    for site, column in zip(("top", "toe"), rate_columns):
        valid = frame[f"imu_{site}_tilt_rate_valid"].to_numpy()
        if not np.array_equal(valid, ~expected_warmup):
            raise ValueError(f"output: invalid {site} tilt-rate validity")
        if not pd.isna(frame[column].iloc[0]) or not np.isfinite(frame[column].iloc[1:].to_numpy(dtype=float)).all():
            raise ValueError(f"output: {column} requires first-row null and finite later values")
    if not frame["state"].isin(STATES).all():
        raise ValueError("output: invalid state")
    if frame["time_s"].iloc[0] != 0 or (np.diff(frame["time_s"]) <= 0).any():
        raise ValueError("output: time must start at zero and increase")
    for column in ("moisture_latent", "soil_top", "soil_middle", "soil_toe", "instability_drive"):
        if not frame[column].between(0, 1).all():
            raise ValueError(f"output: {column} outside [0,1]")
    for column in ("rain_intensity", "displacement_latent", "velocity_latent", "imu_top_vibration_rms", "imu_toe_vibration_rms"):
        if (frame[column] < 0).any():
            raise ValueError(f"output: negative {column}")
    if (np.diff(frame["displacement_latent"]) < 0).any():
        raise ValueError("output: displacement must be nondecreasing")


def simulate(config):
    config = validate_config(config)
    config_hash = parameter_hash(config)
    # A repeat of the same effective config+seed is the same logical synthetic
    # run and has identical row identities. save_run allocates a separate
    # artifact directory for each execution; filesystem time never enters IDs.
    run_id = f"sim_{config_hash}"
    dt = config["simulation"]["dt_s"]
    steps = grid_steps(config["simulation"]["duration_s"], dt, "duration_s")
    time = np.arange(steps + 1, dtype=float) * dt
    rain = np.zeros(steps + 1)
    if config["rain"]["type"] == "constant":
        start = grid_steps(config["rain"]["start_s"], dt, "rain.start_s")
        end = grid_steps(config["rain"]["end_s"], dt, "rain.end_s")
        rain[start:end] = config["rain"]["intensity"]
    # One explicitly seeded generator shared by all sensor draws. Physics is
    # deterministic and independent of sensor RNG consumption. Bitwise numeric
    # replay is promised for this same software/runtime stack, not all versions.
    rng = np.random.default_rng(config["seed"])
    sensors = SensorModel(config["sensor"], config["soil"]["initial_moisture"], dt, rng)
    physics = evaluate_state(config["soil"]["initial_moisture"], config["slope"]["theta_deg"], config["state_model"])
    rows = []
    failure_time = None
    for index, t in enumerate(time):
        if index:
            # R_(n-1) is applied on [t_(n-1), t_n); row n is the state AT t_n.
            # A rainfall event at t_n cannot affect M_n before that interval.
            moisture = update_moisture(physics.moisture, rain[index - 1], dt,
                                       config["soil"]["infiltration_rate"], config["soil"]["drainage_rate"])
            physics = evaluate_state(moisture, config["slope"]["theta_deg"], config["state_model"], physics, dt)
        rows.append({
            "run_id": run_id, "row_index": index, "is_synthetic": True,
            "generator_version": __version__, "seed": config["seed"],
            "parameter_hash": config_hash, "parent_run": None,
            "time_s": float(t), "rain_intensity": float(rain[index]), "state": physics.state,
            "moisture_latent": physics.moisture, "instability_drive": physics.instability_drive,
            "displacement_latent": physics.displacement, "velocity_latent": physics.velocity,
            **sensors.observe(physics),
            "observation_warmup": index == 0,
        })
        # First OBSERVED failure on the sampled grid, including t=0 if already
        # above the threshold. Ground truth only; never passed into sensors.
        if failure_time is None and physics.state == "FAILURE":
            failure_time = float(t)
    frame = pd.DataFrame(rows, columns=CSV_COLUMNS)
    validate_output(frame)
    metadata = {
        "run_id": run_id, "artifact_kind": ARTIFACT_KIND,
        "observation_schema_version": OBSERVATION_SCHEMA_VERSION,
        "contract_status": CONTRACT_STATUS,
        "is_synthetic": True, "generator_version": __version__, "seed": config["seed"],
        "parent_run": None, "parameter_hash": config_hash,
        "failure_time_s": failure_time, "config": config,
        "created_by": "physics_sim.scripts.run_sim", "generator": "Physics-inspired Simulation",
        "scientific_status": "SIMULATION_ONLY; NOT REAL-WORLD HAZARD THRESHOLDS; TODO_CALIBRATION",
        "row_count": len(frame), "output_units": OUTPUT_UNITS,
        "observation_columns": list(OBSERVATION_COLUMNS),
        "runtime": {"python": platform.python_version(), **{name: version(name) for name in ("numpy", "pandas", "PyYAML", "matplotlib", "pytest")}},
    }
    return frame, metadata


def save_run(frame, metadata, output_dir):
    validate_output(frame)
    # Refuse a mismatched or incomplete sidecar before creating a run folder.
    # This keeps row lineage verifiable after CSV slicing or later aggregation.
    if (metadata.get("run_id") != frame["run_id"].iloc[0]
            or metadata.get("parameter_hash") != frame["parameter_hash"].iloc[0]
            or metadata.get("seed") != frame["seed"].iloc[0]
            or metadata.get("generator_version") != __version__
            or metadata.get("is_synthetic") is not True
            or metadata.get("parent_run") is not None
            or metadata.get("row_count") != len(frame)
            or metadata.get("observation_schema_version") != OBSERVATION_SCHEMA_VERSION
            or metadata.get("contract_status") != CONTRACT_STATUS
            or metadata.get("artifact_kind") != ARTIFACT_KIND
            or metadata.get("parameter_hash") != parameter_hash(metadata.get("config"))):
        raise ValueError("metadata: inconsistent synthetic run lineage or schema")
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    # Atomic directory allocation prevents overwrites and races. This unique
    # artifact suffix is NOT a simulation RNG and does not affect numeric data
    # or parameter_hash. Existing experiments are never deleted or overwritten.
    run_dir = Path(tempfile.mkdtemp(prefix=f"run_{metadata['parameter_hash'][:12]}_", dir=root))
    csv_path = run_dir / "simulation.csv"
    with csv_path.open("x", encoding="utf-8", newline="") as stream:
        frame.to_csv(stream, index=False, float_format="%.17g", lineterminator="\n")
    saved_metadata = dict(metadata, csv_sha256=hashlib.sha256(csv_path.read_bytes()).hexdigest())
    with (run_dir / "metadata.json").open("x", encoding="utf-8") as stream:
        json.dump(saved_metadata, stream, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    return run_dir
