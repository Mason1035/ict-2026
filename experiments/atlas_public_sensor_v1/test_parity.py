"""Run with pytest -s or python test_parity.py; missing dependencies fail."""
import argparse
import sys
import numpy as np
from reference import HERE, MODEL_DIR, RidgeForecaster, load_model, predict_delta


def check_branch(branch, *, reference_only=False):
    assert RidgeForecaster is not None, "repository predictor required to prove fallback equivalence"
    path = MODEL_DIR / f"{branch}_model.json"
    repo = RidgeForecaster.load(path)
    fallback = load_model(path, use_repo=False)
    with np.load(HERE / "golden" / f"{branch}_golden.npz", allow_pickle=False) as golden:
        inputs, expected = golden["inputs"], golden["expected_delta"]
    assert inputs.dtype == expected.dtype == np.float32
    assert inputs.shape == (10, repo.history_length, repo.channels)
    assert expected.shape == (len(inputs), repo.channels)
    ref64 = predict_delta(repo, inputs, dtype=np.float64)
    fallback64 = predict_delta(fallback, inputs, use_repo=False, dtype=np.float64)
    # The repository returns next level, so subtract the SAME float64 last level.
    repo_delta64 = repo.predict(inputs, channel_names=repo.channel_names,
                               units=repo.units, time_unit=repo.time_unit) - inputs.astype(np.float64)[:, -1]
    ref_diff = float(np.max(np.abs(ref64 - repo_delta64)))
    fallback_diff = float(np.max(np.abs(fallback64 - repo_delta64)))
    cast_diff = float(np.max(np.abs(ref64.astype(np.float32) - repo_delta64.astype(np.float32))))
    assert np.array_equal(expected, ref64.astype(np.float32)), "stale golden vectors"
    print(f"{branch}: reference/repo={ref_diff:.12g}; fallback/repo={fallback_diff:.12g}; "
          f"after float32 cast={cast_diff:.12g}")
    assert max(ref_diff, fallback_diff, cast_diff) < 1e-9
    if reference_only:
        print(f"PASS {branch} reference checks (ONNX NOT RUN)")
        return
    import onnx
    import onnxruntime as ort
    model_path = HERE / f"{branch}_forecaster.onnx"
    onnx.checker.check_model(str(model_path), full_check=True)
    session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
    assert session.get_inputs()[0].shape == [1, repo.history_length, repo.channels]
    actual = np.concatenate([session.run(["predicted_delta"], {"history": window[None]})[0]
                             for window in inputs])
    assert actual.shape == expected.shape and actual.dtype == np.float32
    ort_diff = float(np.max(np.abs(actual.astype(np.float64) - ref64)))
    assert np.isfinite(actual).all()
    print(f"{branch}: reference/repo={ref_diff:.12g}; fallback/repo={fallback_diff:.12g}; "
          f"after float32 cast={cast_diff:.12g}; ONNX/reference={ort_diff:.12g}")
    assert max(ref_diff, fallback_diff, cast_diff) < 1e-9
    assert ort_diff <= 1e-5
    print(f"PASS {branch}")


def test_soil():
    check_branch("soil")


def test_motion():
    check_branch("motion")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-only", action="store_true",
                        help="diagnostic subset; does NOT certify ONNX parity")
    args = parser.parse_args()
    try:
        for branch in ("soil", "motion"):
            check_branch(branch, reference_only=args.reference_only)
    except Exception:
        print("FAIL parity", file=sys.stderr)
        raise
    print("PASS reference subset; ONNX NOT RUN" if args.reference_only else "PASS all parity checks")
