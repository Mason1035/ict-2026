from dataclasses import replace
import json
import pytest

from ai_training.contracts.schemas import TrainingContract
from ai_training.contracts.validation import validate_contract, load_training_contract
from ai_training.errors import ContractNotReadyError, IntegrityError
from ai_training.training.trainer import Trainer


def test_missing_contract_rejects_before_initialization(tmp_path):
    with pytest.raises(ContractNotReadyError, match="missing"):
        Trainer(None).run(None, None, model_factory=None, optimizer_factory=None, loss=None,
                          normalizer=None, metrics=None, best_policy=None, early_stopping=None,
                          output_root=tmp_path, created_by="TEST_ONLY")
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("field", ["ordered_features", "label", "split_manifest", "feature_version",
                                   "normalization", "metrics", "mask_semantics", "window"])
def test_required_contract_fields(case, field):
    with pytest.raises(ContractNotReadyError, match=field):
        validate_contract(replace(case[0], **{field: None}), test_only=True)


@pytest.mark.parametrize("changes", [
    {"schema_version": "unknown"}, {"contract_version": "unknown"},
    {"status": "APPROVED"}, {"approved_by": "B"}, {"declarations": ()},
    {"ordered_features": ("toy_a", "toy_a")}, {"metrics": ("epoch",)},
])
def test_unsupported_and_forged_contracts(case, changes):
    with pytest.raises(ContractNotReadyError):
        validate_contract(replace(case[0], **changes), test_only=True)


def test_test_only_is_never_formal(case):
    assert validate_contract(case[0], test_only=True) is case[0]
    with pytest.raises(ContractNotReadyError, match="formal training blocked"):
        validate_contract(case[0])
    assert TrainingContract().ordered_features is None


def test_loader_missing_unknown_and_duplicate_fields(tmp_path, case):
    with pytest.raises(ContractNotReadyError):
        load_training_contract(tmp_path / "absent.json")
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(case[0].to_dict() | {"guessed_feature": 1}))
    with pytest.raises(ContractNotReadyError, match="unknown contract fields"):
        load_training_contract(path, test_only=True)
    path.write_text('{"status":"TEST_ONLY", "status":"APPROVED"}')
    with pytest.raises(IntegrityError, match="duplicate"):
        load_training_contract(path, test_only=True)
