from dataclasses import replace
import ast
from pathlib import Path
import numpy as np
import pytest

from ai_training.contracts.validation import validate_contract
from ai_training.errors import LeakageError, ContractNotReadyError
from ai_training.adapters.real import RealAdapter
from ai_training.adapters.synthetic import SyntheticAdapter


@pytest.mark.parametrize("name", ["failure_time", "failure_time_s", "seed", "parameter_hash", "run_id",
                                   "parent_run", "device_id", "boot_id", "seq", "row_index", "is_synthetic",
                                   "future_state", "future_moisture", "future_label", "displacement_latent"])
def test_provenance_and_future_features_rejected(case, name):
    with pytest.raises(LeakageError):
        validate_contract(replace(case[0], ordered_features=(name, "toy_b")), test_only=True)


def test_alias_and_positive_lookahead_rejected(case):
    c = case[0]
    with pytest.raises(LeakageError):
        validate_contract(replace(c, feature_sources={"toy_a": ["seed"], "toy_b": ["toy_b"]}), test_only=True)
    with pytest.raises(LeakageError):
        validate_contract(replace(c, feature_lookahead_s={"toy_a": 1, "toy_b": 0}), test_only=True)


def test_future_availability_and_time_rejected(case):
    c, d, _ = case
    s = d.samples[0]
    with pytest.raises(LeakageError, match="future"):
        replace(s, available_at=np.full(s.X.shape, s.decision_time + 1)).validate(c)
    with pytest.raises(LeakageError, match="future"):
        replace(s, decision_time=1.).validate(c)


def test_adapters_do_not_invent_features(case):
    for adapter in (RealAdapter(), SyntheticAdapter()):
        with pytest.raises(ContractNotReadyError, match="WAITING_FOR"):
            adapter.to_dataset(None, case[0])


def test_package_does_not_import_simulator_or_large_training_stack():
    root = Path(__file__).parents[1] / "src/ai_training"
    forbidden = {"physics_sim", "torch", "tensorflow", "jax", "onnxruntime"}
    for path in root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                assert not {n.name.split(".")[0] for n in node.names} & forbidden
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in forbidden
