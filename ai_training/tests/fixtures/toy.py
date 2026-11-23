"""TEST_ONLY, NOT_REAL_DATA, NOT_PROJECT_TRAINING_DATA, NOT_PROJECT_MODEL.

Tiny functions exercise control flow/state/RNG only. They define no project
feature, label, performance metric or model choice. Never import in production.
"""

from pathlib import Path
import numpy as np

from ai_training.contracts.validation import load_training_contract
from ai_training.datasets.base import CanonicalDataset
from ai_training.datasets.sample import from_columns
from ai_training.datasets.provenance import Provenance
from ai_training.training.reproducibility import content_hash
from ai_training.training.trainer import Trainer, TrainingConfig


class TinyModel:
    implementation_id = "TEST_ONLY.TinyLinear"

    def __init__(self, rng, config):
        self.weights = rng.normal(size=config["input_features"])

    def predict(self, X, mask):
        if not (mask == "V").all():
            raise ValueError("TEST_ONLY model implements only all-valid fixture masks")
        return float(X[-1] @ self.weights)

    def state_dict(self):
        return {"weights": self.weights.tolist()}

    def load_state_dict(self, state):
        self.weights = np.array(state["weights"], dtype=float)


class ToyLoss:
    implementation_id = "TEST_ONLY.squared_error"

    def __call__(self, prediction, target):
        return float((prediction - target) ** 2)


class ToyOptimizer:
    implementation_id = "TEST_ONLY.SGD"

    def __init__(self, config):
        self.config = config
        self.steps = 0

    def step(self, model, X, mask, target, loss, rng):
        prediction = model.predict(X, mask)
        value = loss(prediction, target)
        # Explicit TEST_ONLY perturbation verifies checkpoint RNG restoration,
        # not scientific noise calibration or a recommended optimizer.
        gradient = 2 * (prediction - target) * X[-1]
        model.weights -= self.config["learning_rate"] * (gradient + rng.normal(0, self.config["test_noise"], size=gradient.shape))
        self.steps += 1
        return value

    def state_dict(self):
        return {"steps": self.steps, "config": self.config}

    def load_state_dict(self, state):
        self.steps, self.config = state["steps"], state["config"]


class IdentityNormalizer:
    implementation_id = "TEST_ONLY.identity"

    def __init__(self):
        self.fit_count = 0
        self.sample_count = 0

    def fit(self, inputs):
        self.fit_count += 1
        self.sample_count = len(inputs)

    def transform(self, X, mask):
        if self.fit_count != 1:
            raise ValueError("TEST_ONLY normalizer must be fitted once or restored")
        return X.copy()

    def state_dict(self):
        return {"fit_count": self.fit_count, "sample_count": self.sample_count}

    def load_state_dict(self, state):
        self.fit_count, self.sample_count = state["fit_count"], state["sample_count"]


class ToyMetric:
    implementation_id = "TEST_ONLY.mse"

    def __call__(self, targets, predictions):
        return float(np.mean((np.array(targets) - predictions) ** 2))


class ToyBestPolicy:
    implementation_id = "TEST_ONLY.minimum_mse"

    def select(self, metrics, best_metrics):
        return best_metrics is None or metrics["TEST_ONLY.mse"] < best_metrics["TEST_ONLY.mse"]


def make_case():
    contract = load_training_contract(Path(__file__).with_name("test_only_contract.json"), test_only=True)
    samples = []
    for run, split, offset in (("toy_train", "train", 0), ("toy_train", "train", 3),
                               ("toy_validation", "validation", 0), ("toy_test", "test", 0)):
        times = np.arange(offset, offset + contract.window["length"], dtype=float)
        columns = {"toy_a": times / 10, "toy_b": (times + 1) / 10,
                   "run_id": np.full(len(times), run), "seed": np.full(len(times), 17),
                   "failure_time_s": np.full(len(times), 999)}
        provenance = Provenance("SYNTHETIC", run, tuple(range(offset, offset + len(times))),
                                dataset_version="TEST_ONLY.dataset.v1", feature_version=contract.feature_version,
                                split=split, generator_version="TEST_ONLY.toy.v1", seed=17,
                                parameter_hash=content_hash({"purpose": "TEST_ONLY"}))
        sample = from_columns(columns, contract=contract, mask=np.full((len(times), 2), "V"),
                              y=float(times[-1] / 5), provenance=provenance, times=times,
                              available_at=np.repeat(times[:, None], 2, axis=1), decision_time=float(times[-1]))
        samples.append(sample)
    dataset = CanonicalDataset("TEST_ONLY.dataset.v1", tuple(samples),
                               ("TEST_ONLY", "NOT_REAL_DATA", "NOT_PROJECT_TRAINING_DATA"))
    config = TrainingConfig(seed=17, epochs=4,
                            model_config={"implementation": "TEST_ONLY.TinyLinear", "input_features": 2},
                            optimizer_config={"implementation": "TEST_ONLY.SGD", "learning_rate": 0.1, "test_noise": 0.01},
                            loss_id="TEST_ONLY.squared_error", normalizer_id="TEST_ONLY.identity",
                            best_policy_id="TEST_ONLY.minimum_mse", early_stopping_id=None, experiment_mode="TEST_ONLY")
    return contract, dataset, config


def run_case(root, *, case=None, early_stopping=None, **kwargs):
    contract, dataset, config = case or make_case()
    return Trainer(contract, test_only=True).run(
        dataset, config, model_factory=TinyModel, optimizer_factory=ToyOptimizer,
        loss=ToyLoss(), normalizer=IdentityNormalizer(), metrics={"TEST_ONLY.mse": ToyMetric()},
        best_policy=ToyBestPolicy(), early_stopping=early_stopping, output_root=root,
        created_by="TEST_ONLY.framework-validation", **kwargs)
