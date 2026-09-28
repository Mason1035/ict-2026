"""Load -> validate -> simulate -> validate -> persist CSV and metadata."""

import argparse
import json
from pathlib import Path

from physics_sim.simulator.config import load_config
from physics_sim.simulator.pipeline import save_run, simulate


def main(argv=None):
    parser = argparse.ArgumentParser(description="Physics-inspired synthetic simulation (not calibrated prediction)")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parents[1] / "outputs")
    args = parser.parse_args(argv)
    try:
        frame, metadata = simulate(load_config(args.config))
        run_dir = save_run(frame, metadata, args.output_dir)
    except (ValueError, OSError, OverflowError) as exc:
        parser.error(str(exc))
    print(json.dumps({
        "run_dir": str(run_dir.resolve()), "run_id": metadata["run_id"],
        "observation_schema_version": metadata["observation_schema_version"],
        "contract_status": metadata["contract_status"],
        "final_state": frame["state"].iloc[-1],
        "max_moisture": float(frame["moisture_latent"].max()),
        "max_displacement_m": float(frame["displacement_latent"].max()),
        "failure_time_s": metadata["failure_time_s"], "parameter_hash": metadata["parameter_hash"],
    }, indent=2))


if __name__ == "__main__":
    main()
