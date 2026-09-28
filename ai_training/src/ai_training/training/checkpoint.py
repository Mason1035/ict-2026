"""JSON checkpoints: no executable pickle; epoch-boundary resume only in V0.1."""

from ai_training.errors import IntegrityError
from .reproducibility import content_hash, file_hash, read_json, write_json_exclusive

SCHEMA = "ai_training.checkpoint.v0.1"


def save_checkpoint(path, identity, state, best_state=None):
    payload = {"schema": SCHEMA, "identity": identity, "state": state, "best_state": best_state}
    return write_json_exclusive(path, {"payload": payload, "content_hash": content_hash(payload)})


def load_checkpoint(path, expected_identity, *, expected_hash=None):
    if expected_hash is not None and file_hash(path) != expected_hash:
        raise IntegrityError("checkpoint file hash mismatch; restore the artifact referenced by the manifest")
    envelope = read_json(path)
    payload = envelope.get("payload")
    if not isinstance(payload, dict) or envelope.get("content_hash") != content_hash(payload):
        raise IntegrityError("checkpoint content hash mismatch; do not resume corrupted state")
    if payload.get("schema") != SCHEMA:
        raise IntegrityError("unsupported checkpoint schema; use its compatible framework")
    # Compare the entire content identity BEFORE touching a model/optimizer:
    # same version labels alone do not prove same dataset, contract or software.
    if content_hash(payload.get("identity")) != content_hash(expected_identity):
        raise IntegrityError("incompatible checkpoint identity (dataset/contract/split/config/environment); resume with original inputs or start a new run")
    required = {"model", "optimizer", "normalizer", "rng", "epoch", "step", "history", "metrics"}
    states = [payload.get("state")]
    if payload.get("best_state") is not None:
        states.append(payload["best_state"])
    for state in states:
        if not isinstance(state, dict) or set(state) != required:
            raise IntegrityError("checkpoint state incomplete; supply a complete epoch-boundary checkpoint")
        if any(type(state[k]) is not int or state[k] < 0 for k in ("epoch", "step")):
            raise IntegrityError("invalid checkpoint position; restore a valid checkpoint")
        if (not isinstance(state["history"], list) or len(state["history"]) != state["epoch"]
                or [r.get("epoch") for r in state["history"]] != list(range(1, state["epoch"] + 1))):
            raise IntegrityError("checkpoint epoch/history mismatch; restore complete training history")
    return payload
