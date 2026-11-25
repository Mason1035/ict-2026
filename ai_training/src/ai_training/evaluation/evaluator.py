"""Injected metrics only; sealed Test evaluation is a future B-reviewed workflow."""

from typing import Protocol
import math

from ai_training.contracts.validation import validate_contract, validate_no_group_leakage, require
from ai_training.errors import LeakageError
from ai_training.datasets.normalization import transform_checked
from ai_training.training.reproducibility import content_hash


class MetricProtocol(Protocol):
    implementation_id: str
    def __call__(self, targets, predictions) -> float: ...


class Evaluator:
    def evaluate(self, contract, samples, model, normalizer, metric_registry, *, test_only=False):
        validate_contract(contract, test_only=test_only)
        require(set(metric_registry) == set(contract.metrics), "Metrics Contract and implementations differ")
        require(all(m.implementation_id == name for name, m in metric_registry.items()), "metric implementation identity mismatch")
        samples = tuple(samples)
        require(bool(samples), "validation partition empty")
        assignments = validate_no_group_leakage(contract.split_manifest)
        predictions, targets, provenance = [], [], []
        for sample in samples:
            sample.validate(contract)
            p = sample.provenance
            if (p.split != "validation" or p.run_id not in assignments or assignments[p.run_id].split != "validation"
                    or (p.source_type, p.parent_run) != (assignments[p.run_id].source_type, assignments[p.run_id].parent_run)):
                raise LeakageError("evaluator accepts Validation only; Test remains sealed pending B final-evaluation protocol")
            X = transform_checked(normalizer, sample, contract)
            prediction = float(model.predict(X, sample.mask.copy()))
            require(math.isfinite(prediction), "non-finite model prediction")
            predictions.append(prediction)
            targets.append(sample.y)
            provenance.append(p.to_dict())
        metrics = {name: float(metric_registry[name](targets, predictions)) for name in contract.metrics}
        require(all(math.isfinite(v) for v in metrics.values()), "non-finite evaluation metric")
        return {"status": "TEST_ONLY_VALIDATION", "metrics": metrics, "split": "validation",
                "dataset_version": contract.split_manifest.dataset_version,
                "split_manifest_hash": content_hash(contract.split_manifest.to_dict()),
                "contract_hash": content_hash(contract.to_dict()), "model_state_hash": content_hash(model.state_dict()),
                "timestamp": None, "predictions": predictions, "prediction_provenance": provenance}
