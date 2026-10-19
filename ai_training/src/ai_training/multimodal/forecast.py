"""Small NumPy next-observation models; no invented disaster class labels."""

from dataclasses import dataclass
import json
from pathlib import Path

import numpy as np


def _finite_array(value, ndim):
    array = np.asarray(value, dtype=np.float64)
    if array.ndim != ndim or not np.isfinite(array).all():
        raise ValueError(f"expected finite rank-{ndim} numeric array")
    return array


def history_features(history):
    """Current level and past increments; no future times, IDs or labels in X."""
    history = _finite_array(history, 3)
    if history.shape[1] < 2 or history.shape[2] == 0:
        raise ValueError("need at least two past observations and one channel")
    return np.concatenate((history[:, -1], np.diff(history, axis=1).reshape(len(history), -1)), axis=1)


@dataclass(frozen=True)
class WindowBatch:
    history: np.ndarray
    target: np.ndarray
    groups: tuple[str, ...]
    runs: tuple[str, ...]
    source_ids: tuple[str, ...]
    target_times: np.ndarray

    def __len__(self):
        return len(self.target)

    def subset(self, indices):
        indices = np.asarray(indices, dtype=int)
        return WindowBatch(self.history[indices], self.target[indices],
                           tuple(self.groups[i] for i in indices),
                           tuple(self.runs[i] for i in indices),
                           tuple(self.source_ids[i] for i in indices), self.target_times[indices])


def build_windows(series, history_length):
    if type(history_length) is not int or history_length < 2:
        raise ValueError("history_length must be an integer >= 2")
    histories, targets, groups, runs, sources, times = [], [], [], [], [], []
    channel_count = None
    for item in series:
        values = _finite_array(item.values, 2)
        stamps = _finite_array(item.times, 1)
        if len(values) != len(stamps) or not np.all(np.diff(stamps) > 0):
            raise ValueError("series time must strictly increase")
        if channel_count is None:
            channel_count = values.shape[1]
        if channel_count != values.shape[1]:
            raise ValueError("cannot mix channel counts within a branch")
        for index in range(history_length, len(values)):
            histories.append(values[index-history_length:index])
            targets.append(values[index])
            groups.append(item.group_id)
            runs.append(item.run_id)
            sources.append(item.source_id)
            times.append(stamps[index])
    if not targets:
        raise ValueError("no complete causal windows; collect longer sequences")
    return WindowBatch(np.asarray(histories), np.asarray(targets), tuple(groups),
                       tuple(runs), tuple(sources), np.asarray(times))


def group_split(groups, *, seed, train_fraction, validation_fraction):
    """Split physical/date lineage groups before windows are constructed."""
    if not (0 < train_fraction < 1 and 0 < validation_fraction < 1
            and train_fraction + validation_fraction < 1):
        raise ValueError("train/validation fractions must leave a nonempty test share")
    unique = np.array(sorted(set(groups)), dtype=object)
    if len(unique) < 3:
        raise ValueError("at least three lineage groups required for grouped holdout")
    np.random.default_rng(seed).shuffle(unique)
    n_train = min(max(1, int(len(unique) * train_fraction)), len(unique)-2)
    n_validation = min(max(1, int(len(unique) * validation_fraction)), len(unique)-n_train-1)
    return {"train": tuple(sorted(unique[:n_train])),
            "validation": tuple(sorted(unique[n_train:n_train+n_validation])),
            "test": tuple(sorted(unique[n_train+n_validation:]))}


def equal_group_weights(groups):
    """Long recordings do not receive proportionally more influence."""
    counts = {group: groups.count(group) for group in set(groups)}
    return np.asarray([1.0 / counts[group] for group in groups])


class RidgeForecaster:
    """Predict the next recorded value using a learned increment over persistence."""

    schema = "zhifang.public-sensor-forecaster.v1"

    def fit(self, history, target, *, alpha, weights=None, modality, channel_names, units, time_unit):
        history = _finite_array(history, 3)
        target = _finite_array(target, 2)
        if target.shape != (len(history), history.shape[2]) or len(history) < 2:
            raise ValueError("history/target shape mismatch or insufficient training windows")
        if (modality not in ("soil", "motion") or len(units) != target.shape[1]
                or len(channel_names) != target.shape[1] or len(set(channel_names)) != len(channel_names)
                or not time_unit):
            raise ValueError("explicit modality, channel units and native time unit required")
        if not np.isfinite(alpha) or alpha <= 0:
            raise ValueError("ridge alpha must be finite and positive")
        weight = np.ones(len(history)) if weights is None else _finite_array(weights, 1)
        if weight.shape != (len(history),) or np.any(weight <= 0):
            raise ValueError("training weights must be positive and match windows")
        weight = weight / weight.sum()
        x = history_features(history)
        delta = target - history[:, -1]
        self.mean = np.average(x, axis=0, weights=weight)
        variance = np.average((x-self.mean)**2, axis=0, weights=weight)
        self.scale = np.sqrt(variance)
        self.scale[self.scale < 1e-12] = 1.0
        self.delta_mean = np.average(delta, axis=0, weights=weight)
        z = (x-self.mean)/self.scale
        # The weighted objective is a mean; alpha is independent of row count.
        gram = z.T @ (weight[:, None] * z) + alpha * np.eye(z.shape[1])
        rhs = z.T @ (weight[:, None] * (delta-self.delta_mean))
        self.coefficients = np.linalg.solve(gram, rhs)
        self.history_length = history.shape[1]
        self.channels = history.shape[2]
        self.alpha = float(alpha)
        self.modality, self.units, self.time_unit = modality, tuple(units), time_unit
        self.channel_names = tuple(channel_names)
        return self

    def predict(self, history, *, channel_names, units, time_unit):
        history = _finite_array(history, 3)
        if history.shape[1:] != (self.history_length, self.channels):
            raise ValueError("history window/channel order differs from trained model")
        if tuple(channel_names) != self.channel_names or tuple(units) != self.units or time_unit != self.time_unit:
            raise ValueError("channel order/unit/time mismatch; explicit calibrated adapter required")
        z = (history_features(history)-self.mean)/self.scale
        prediction = history[:, -1] + z @ self.coefficients + self.delta_mean
        if not np.isfinite(prediction).all():
            raise ValueError("non-finite prediction")
        return prediction

    def to_dict(self):
        return {"schema": self.schema, "purpose": "PUBLIC_DATA_RESEARCH",
                "task": "next_recorded_observation_regression", "modality": self.modality,
                "history_length": self.history_length, "channels": self.channels,
                "channel_names": list(self.channel_names), "units": list(self.units), "time_unit": self.time_unit, "alpha": self.alpha,
                "mean": self.mean.tolist(), "scale": self.scale.tolist(),
                "delta_mean": self.delta_mean.tolist(), "coefficients": self.coefficients.tolist(),
                "class_labels": None, "alarm_thresholds": None, "deployment_ready": False}

    def save(self, path):
        with Path(path).open("x", encoding="utf-8") as stream:
            json.dump(self.to_dict(), stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")

    @classmethod
    def load(cls, path):
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if raw.get("schema") != cls.schema or raw.get("purpose") != "PUBLIC_DATA_RESEARCH":
            raise ValueError("unsupported model schema/purpose")
        if (raw.get("class_labels") is not None or raw.get("alarm_thresholds") is not None
                or raw.get("deployment_ready") is not False):
            raise ValueError("research forecaster cannot be promoted to an alarm classifier")
        model = cls()
        model.history_length, model.channels = raw["history_length"], raw["channels"]
        if type(model.history_length) is not int or model.history_length < 2 or type(model.channels) is not int or model.channels < 1:
            raise ValueError("invalid model window/channels")
        model.modality, model.units, model.time_unit = raw["modality"], tuple(raw["units"]), raw["time_unit"]
        model.channel_names = tuple(raw["channel_names"])
        if (model.modality not in ("soil", "motion") or len(model.units) != model.channels
                or len(model.channel_names) != model.channels or len(set(model.channel_names)) != model.channels
                or not model.time_unit):
            raise ValueError("invalid model unit/modality metadata")
        model.alpha = float(raw["alpha"])
        model.mean, model.scale = _finite_array(raw["mean"], 1), _finite_array(raw["scale"], 1)
        model.delta_mean = _finite_array(raw["delta_mean"], 1)
        model.coefficients = _finite_array(raw["coefficients"], 2)
        width = model.history_length * model.channels
        if (model.mean.shape != (width,) or model.scale.shape != (width,)
                or model.delta_mean.shape != (model.channels,)
                or model.coefficients.shape != (width, model.channels)
                or np.any(model.scale <= 0) or not np.isfinite(model.alpha) or model.alpha <= 0):
            raise ValueError("invalid model dimensions/scales")
        return model


def regression_metrics(batch, prediction):
    """Equal-group metrics in each source's native units, versus last-value baseline."""
    prediction = _finite_array(prediction, 2)
    if prediction.shape != batch.target.shape:
        raise ValueError("prediction shape mismatch")
    weight = equal_group_weights(batch.groups)
    error = prediction-batch.target
    baseline = batch.history[:, -1]-batch.target
    return {"windows": len(batch), "groups": len(set(batch.groups)),
            "mae_per_channel": np.average(np.abs(error), axis=0, weights=weight).tolist(),
            "rmse_per_channel": np.sqrt(np.average(error**2, axis=0, weights=weight)).tolist(),
            "persistence_mae_per_channel": np.average(np.abs(baseline), axis=0, weights=weight).tolist(),
            "persistence_rmse_per_channel": np.sqrt(np.average(baseline**2, axis=0, weights=weight)).tolist()}
