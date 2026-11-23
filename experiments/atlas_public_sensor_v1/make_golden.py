"""Deterministic synthetic engineering fixtures, not calibrated field samples."""
import numpy as np
from reference import HERE, MODEL_DIR, load_model, predict_delta


def make_windows(t, c):
    rng = np.random.default_rng(20261020 + c)
    levels = np.linspace(0.1, 0.6, c)
    ramp = np.arange(t)[:, None] * np.linspace(0.01, 0.06, c)[None, :]
    return np.asarray([
        np.zeros((t, c)), np.full((t, c), 0.25),
        np.broadcast_to(levels, (t, c)), levels + ramp, levels - ramp,
        *rng.normal(0, 0.2, size=(5, t, c)),
    ], dtype=np.float32)


def main():
    (HERE / "golden").mkdir(exist_ok=True)
    for branch in ("soil", "motion"):
        model = load_model(MODEL_DIR / f"{branch}_model.json")
        inputs = make_windows(model.history_length, model.channels)
        output = HERE / "golden" / f"{branch}_golden.npz"
        np.savez(output, inputs=inputs, expected_delta=predict_delta(model, inputs))
        print(f"Wrote {output}: {len(inputs)} windows")


if __name__ == "__main__":
    main()
