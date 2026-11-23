"""NumPy delta reference; preserve float64 math until the public float32 output."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MODEL_DIR = ROOT / "ai_training/pretrained/public_sensor_v1"
# Prevent importing the repository from creating files outside this experiment.
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "ai_training/src"))
try:
    from ai_training.multimodal.forecast import RidgeForecaster, history_features
except ModuleNotFoundError as exc:
    if exc.name not in {"ai_training", "ai_training.multimodal", "ai_training.multimodal.forecast"}:
        raise
    RidgeForecaster = None
    history_features = None


def load_model(path, *, use_repo=True):
    if use_repo and RidgeForecaster is not None:
        return RidgeForecaster.load(path)
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if (raw.get("schema") != "zhifang.public-sensor-forecaster.v1"
            or raw.get("purpose") != "PUBLIC_DATA_RESEARCH"
            or raw.get("deployment_ready") is not False
            or raw.get("class_labels") is not None
            or raw.get("alarm_thresholds") is not None):
        raise ValueError("expected an unpromoted public research forecaster")
    model = SimpleNamespace(**raw)
    t, c = model.history_length, model.channels
    if type(t) is not int or t < 2 or type(c) is not int or c < 1:
        raise ValueError("invalid history dimensions")
    for name, shape in (("mean", (t*c,)), ("scale", (t*c,)),
                        ("coefficients", (t*c, c)), ("delta_mean", (c,))):
        value = np.asarray(raw[name], dtype=np.float64)
        if value.shape != shape or not np.isfinite(value).all():
            raise ValueError(f"invalid {name}")
        setattr(model, name, value)
    if (np.any(model.scale <= 0) or not np.isfinite(model.alpha) or model.alpha <= 0
            or model.modality not in ("soil", "motion")
            or len(model.channel_names) != c or len(set(model.channel_names)) != c
            or len(model.units) != c or not model.time_unit):
        raise ValueError("invalid scales/metadata")
    return model


def predict_delta(model, history, *, use_repo=True, dtype=np.float32):
    h = np.asarray(history, dtype=np.float64)
    if h.ndim != 3 or h.shape[1:] != (model.history_length, model.channels) or not np.isfinite(h).all():
        raise ValueError("expected finite (N, history_length, channels) history")
    if use_repo and history_features is not None:
        features = history_features(h)
    else:
        features = np.concatenate((h[:, -1, :],
                                   (h[:, 1:, :] - h[:, :-1, :]).reshape(len(h), -1)), axis=1)
    delta = ((features - model.mean) / model.scale) @ model.coefficients + model.delta_mean
    if not np.isfinite(delta).all():
        raise ValueError("non-finite predicted delta")
    return delta.astype(dtype)
