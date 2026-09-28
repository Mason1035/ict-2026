"""Offline diagnostic panels with categorical state trace and transition marks."""

import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from physics_sim.simulator.config import STATES
from physics_sim.simulator.pipeline import validate_output


def plot_run(csv_path, output_path):
    frame = pd.read_csv(csv_path, float_precision="round_trip")
    validate_output(frame)
    time = frame["time_s"]
    panels = (
        (("rain_intensity",), "Rain [mm/h]"),
        (("moisture_latent",), "Latent moisture\n[normalized]"),
        (("soil_top", "soil_middle", "soil_toe"), "Soil observations\n[normalized]"),
        (("displacement_latent",), "Latent D [m]"),
        (("velocity_latent",), "Latent v [m/s]"),
        (("imu_top_tilt_deg", "imu_toe_tilt_deg"), "Tilt [deg]"),
        (("imu_top_vibration_rms", "imu_toe_vibration_rms"), "RMS proxy [m/s²]"),
    )
    fig, axes = plt.subplots(len(panels) + 1, 1, figsize=(13, 19), sharex=True, constrained_layout=True)
    try:
        for ax, (columns, label) in zip(axes, panels):
            for column in columns:
                if column in ("rain_intensity", "velocity_latent"):
                    ax.step(time, frame[column], where="post", label=column)
                else:
                    ax.plot(time, frame[column], label=column)
            ax.set_ylabel(label)
            ax.legend(loc="upper left", fontsize="small")
            ax.grid(alpha=0.25)
        codes = frame["state"].map({name: index for index, name in enumerate(STATES)})
        axes[-1].step(time, codes, where="post", color="black")
        axes[-1].set_yticks(range(len(STATES)), STATES, fontsize="small")
        axes[-1].set_ylim(-0.2, len(STATES) - 0.8)
        axes[-1].set_ylabel("Synthetic state")
        axes[-1].set_xlabel("Time [s]")
        transitions = time[frame["state"].ne(frame["state"].shift())].iloc[1:]
        for ax in axes:
            for t in transitions:
                ax.axvline(t, color="grey", linestyle=":", alpha=0.6)
        fig.suptitle("Physics-inspired synthetic simulation\nNot real-world calibrated prediction", fontsize=15)
        path = Path(output_path)
        # Exclusive creation also protects previous user plots.
        with path.open("xb") as stream:
            fig.savefig(stream, format="png", dpi=140)
    finally:
        plt.close(fig)
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--output", type=Path, help="new PNG path; default: sibling diagnostic.png")
    args = parser.parse_args(argv)
    try:
        path = plot_run(args.csv, args.output or args.csv.with_name("diagnostic.png"))
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(path.resolve())


if __name__ == "__main__":
    main()
