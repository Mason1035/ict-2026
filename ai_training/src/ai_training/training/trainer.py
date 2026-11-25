"""Injected, epoch-boundary training workflow; V0.1 executes TEST_ONLY fixtures."""

from copy import deepcopy
from dataclasses import dataclass, asdict
from typing import Protocol
import csv
import math

from ai_training.artifacts.manifest import allocate_run, run_identity, make_manifest, save_manifest, utc_now
from ai_training.contracts.validation import validate_contract, require
from ai_training.datasets.normalization import fit_train_only, save_normalizer, transform_checked
from ai_training.evaluation.evaluator import Evaluator
from .checkpoint import save_checkpoint, load_checkpoint
from .reproducibility import seeded_rng, write_json_exclusive, file_hash, implementation_hashes


@dataclass(frozen=True)
class TrainingConfig:
    seed: int
    epochs: int
    model_config: dict
    optimizer_config: dict
    loss_id: str
    normalizer_id: str
    best_policy_id: str | None
    early_stopping_id: str | None
    experiment_mode: str


class BestCheckpointPolicy(Protocol):
    implementation_id: str
    def select(self, metrics: dict, best_metrics: dict | None) -> bool: ...


class EarlyStoppingPolicy(Protocol):
    implementation_id: str
    def should_stop(self, history: tuple[dict, ...]) -> bool: ...


class Trainer:
    def __init__(self, contract, *, test_only=False):
        self.contract = contract
        self.test_only = test_only

    def run(self, dataset, config, *, model_factory, optimizer_factory, loss, normalizer,
            metrics, best_policy, early_stopping, output_root, created_by,
            resume=None, resume_hash=None, stop_after_epoch=None):
        # Validate before model construction or artifact allocation. A toy
        # contract cannot be made official by changing a status field or flag.
        c = validate_contract(self.contract, test_only=self.test_only)
        dataset.validate(c, test_only=self.test_only)
        require(type(config.epochs) is int and config.epochs > 0, "epochs must be explicitly positive")
        require(config.experiment_mode == "TEST_ONLY", "REAL_ONLY / REAL_PLUS_SYNTHETIC execution WAITING_FOR_A/B")
        require(bool(created_by), "training operator identity missing")
        require(config.loss_id == loss.implementation_id, "loss configuration/implementation mismatch")
        require(config.normalizer_id == normalizer.implementation_id == c.normalization["implementation"], "normalizer mismatch")
        require(config.best_policy_id == getattr(best_policy, "implementation_id", None), "best checkpoint policy mismatch")
        require(config.early_stopping_id == getattr(early_stopping, "implementation_id", None), "early stopping policy mismatch")
        if stop_after_epoch is not None:
            require(type(stop_after_epoch) is int and 0 < stop_after_epoch <= config.epochs, "invalid interruption epoch")
        train = dataset.training_partition("train")
        validation = dataset.training_partition("validation")
        require(bool(train) and bool(validation), "Train/Validation partition missing")
        identity = run_identity(config, c, dataset)
        identity["implementation_hashes"] = implementation_hashes({
            "model": model_factory, "optimizer": optimizer_factory, "loss": loss,
            "normalizer": normalizer, "best_policy": best_policy, "early_stopping": early_stopping,
            **{f"metric:{name}": metric for name, metric in metrics.items()}})
        restored = load_checkpoint(resume, identity, expected_hash=resume_hash) if resume else None
        rng = seeded_rng(config.seed)
        model = model_factory(rng, deepcopy(config.model_config))
        optimizer = optimizer_factory(deepcopy(config.optimizer_config))
        require(model.implementation_id == config.model_config.get("implementation"), "model implementation mismatch")
        require(optimizer.implementation_id == config.optimizer_config.get("implementation"), "optimizer implementation mismatch")
        start_epoch, step, history, best_state = 0, 0, [], None
        if restored is None:
            fit_train_only(normalizer, train, c)
        else:
            state = restored["state"]
            start_epoch, step = state["epoch"], state["step"]
            require(start_epoch < config.epochs, "checkpoint already at/after requested final epoch")
            require(stop_after_epoch is None or stop_after_epoch > start_epoch, "interruption epoch must follow resume epoch")
            model.load_state_dict(state["model"])
            optimizer.load_state_dict(state["optimizer"])
            normalizer.load_state_dict(state["normalizer"])
            rng.bit_generator.state = state["rng"]
            history, best_state = state["history"], restored["best_state"]
        directory = allocate_run(output_root, identity)
        started = utc_now()
        evaluator = Evaluator()
        state = None
        stop_reason = "EPOCH_LIMIT"
        for epoch in range(start_epoch + 1, config.epochs + 1):
            losses = []
            # Input order is the dataset order; no implicit random window split,
            # shuffle or default scientific policy is introduced by the trainer.
            for sample in train:
                X = transform_checked(normalizer, sample, c)
                value = float(optimizer.step(model, X, sample.mask.copy(), sample.y, loss, rng))
                require(math.isfinite(value), "non-finite train loss; fix model/config/input")
                losses.append(value)
                step += 1
            evaluation = evaluator.evaluate(c, validation, model, normalizer, metrics, test_only=self.test_only)
            history.append({"epoch": epoch, "step": step, "train_loss": sum(losses) / len(losses),
                            "validation_metrics": evaluation["metrics"]})
            # All stochastic/stateful components needed for deterministic resume
            # are saved. V0.1 explicitly does not support mid-batch checkpoints.
            state = deepcopy({"model": model.state_dict(), "optimizer": optimizer.state_dict(),
                              "normalizer": normalizer.state_dict(), "rng": rng.bit_generator.state,
                              "epoch": epoch, "step": step, "history": history, "metrics": evaluation["metrics"]})
            if best_policy is not None and best_policy.select(evaluation["metrics"], None if best_state is None else best_state["metrics"]):
                best_state = deepcopy(state)
            if early_stopping is not None and early_stopping.should_stop(tuple(deepcopy(history))):
                stop_reason = "INJECTED_EARLY_STOPPING"
                break
            if stop_after_epoch == epoch:
                stop_reason = "REQUESTED_EPOCH_INTERRUPTION"
                break
        require(state is not None, "no epoch executed; resume at an earlier epoch")
        hashes = {}
        hashes["training_config.json"] = write_json_exclusive(directory / "training_config.json", asdict(config))
        hashes["contract.json"] = write_json_exclusive(directory / "contract.json", c.to_dict())
        hashes["split_manifest.json"] = write_json_exclusive(directory / "split_manifest.json", c.split_manifest.to_dict())
        hashes["checkpoints/last.json"] = save_checkpoint(directory / "checkpoints/last.json", identity, state, best_state)
        if best_state is not None:
            hashes["checkpoints/best.json"] = save_checkpoint(directory / "checkpoints/best.json", identity, best_state, best_state)
        hashes["preprocessing/normalizer.json"] = save_normalizer(directory / "preprocessing/normalizer.json", normalizer, identity)
        hashes["evaluation/metrics.json"] = write_json_exclusive(directory / "evaluation/metrics.json", evaluation)
        with (directory / "training_log.csv").open("x", newline="", encoding="utf-8") as stream:
            columns = ["epoch", "step", "train_loss"] + list(c.metrics)
            writer = csv.DictWriter(stream, fieldnames=columns)
            writer.writeheader()
            for row in history:
                writer.writerow({k: row[k] for k in ("epoch", "step", "train_loss")} | row["validation_metrics"])
        hashes["training_log.csv"] = file_hash(directory / "training_log.csv")
        sources = [asdict(a) for a in c.split_manifest.assignments]
        manifest = make_manifest(identity, created_by=created_by, started_at=started, sources=sources,
                                 artifact_hashes=hashes, normalizer_version=normalizer.implementation_id,
                                 completed=state["epoch"] == config.epochs,
                                 resumed_from=file_hash(resume) if resume else None)
        manifest["stop_reason"] = stop_reason
        if stop_reason == "INJECTED_EARLY_STOPPING":
            manifest["execution_status"] = "TEST_ONLY_EARLY_STOPPED"
        save_manifest(directory, manifest)
        return directory
