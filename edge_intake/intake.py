"""Preserve validated v2 JSON and provenance in a detached, in-memory receipt.

Upstream validation is a precondition, not a capability established by this
function. The guards below protect this boundary; they are not a full NODE or
LoRa schema validator. Reception is not durable storage or an Atlas ACK.
"""

from collections.abc import Mapping
import hashlib
import json
import math
from typing import Any


TELEMETRY_SCHEMA = "zhifang.telemetry.v2"
INTAKE_VERSION = "0.1.0"


class EdgeIntakeError(ValueError):
    """Input cannot be preserved as validated Telemetry and JSON sidecar."""


def _snapshot(value: Any, path: str, active: set[int]) -> Any:
    """Copy JSON values, including the runner's MappingProxyType/tuple views."""
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise EdgeIntakeError(f"{path}: NaN/Inf cannot be retained; reject upstream")
        return value
    if not isinstance(value, (Mapping, list, tuple)):
        raise EdgeIntakeError(
            f"{path}: non-JSON {type(value).__name__}; supply validated JSON values"
        )
    if id(value) in active:
        raise EdgeIntakeError(f"{path}: cyclic data is not JSON; reject upstream")
    active.add(id(value))
    try:
        if isinstance(value, Mapping):
            result = {}
            for key, item in value.items():
                if type(key) is not str:
                    raise EdgeIntakeError(f"{path}: JSON keys must be strings; reject upstream")
                result[key] = _snapshot(item, f"{path}.{key}", active)
            return result
        # Frozen arrays are tuples in A's runner. Materialize JSON arrays without
        # retaining references: another consumer cannot change our received data.
        return [_snapshot(item, f"{path}[{i}]", active) for i, item in enumerate(value)]
    finally:
        active.remove(id(value))


def receive_validated_telemetry(
    payload: Mapping[str, Any], *, context: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Receive an upstream-validated v2 payload without interpreting sensor data.

    Returns a caller-owned snapshot, identity, provenance, deterministic payload
    hash and explicit downstream status. No mutation, deduplication, persistence,
    forwarding, risk computation or training conversion occurs here.
    """
    if not isinstance(payload, Mapping):
        raise EdgeIntakeError("payload: expected a validated JSON object; run the upstream validator")
    if context is not None and not isinstance(context, Mapping):
        raise EdgeIntakeError("context: expected a JSON sidecar object or None")
    try:
        received = _snapshot(payload, "payload", set())
        sidecar = _snapshot(context, "context", set())
    except RecursionError as exc:
        raise EdgeIntakeError("input: nesting exceeds JSON snapshot support; reject upstream") from exc

    # The SSOT identity belongs to A. Never allocate a replacement seq or coerce
    # strings/bools into IDs to make an invalid message look accepted.
    if received.get("schema") != TELEMETRY_SCHEMA:
        raise EdgeIntakeError(f"payload.schema: expected {TELEMETRY_SCHEMA}; reject upstream")
    device_id = received.get("device_id")
    if not isinstance(device_id, str) or not device_id.strip():
        raise EdgeIntakeError("payload.device_id: expected a nonempty string; reject upstream")
    for field in ("boot_id", "seq"):
        if type(received.get(field)) is not int or received[field] < 0:
            raise EdgeIntakeError(f"payload.{field}: expected a nonnegative integer; reject upstream")

    # Source and per-channel sampling evidence remain a sidecar. Null is unknown,
    # not REAL, zero, NORMAL or a repaired sensor value. No schema fields change.
    source = None if sidecar is None else sidecar.get("source")
    if source is not None and (not isinstance(source, str) or not source.strip()):
        raise EdgeIntakeError("context.source: expected a nonempty string or null; do not guess provenance")
    try:
        # This matches A's mock_loader.payload_hash. It hashes canonical JSON
        # content, not original wire bytes. Context and the invocation clock are
        # excluded; source timestamps inside the payload remain included.
        canonical = json.dumps(
            received, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
        # Check that the entire sidecar is JSON-serializable too, without hashing
        # it into the NODE payload identity or adding it to the v2 schema.
        json.dumps(sidecar, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise EdgeIntakeError("input: cannot encode finite UTF-8 JSON; reject upstream") from exc

    return {
        "status": "ACCEPTED_BY_EDGE_INTAKE",
        "identity": {field: received[field] for field in ("device_id", "boot_id", "seq")},
        "source": source,
        "payload": received,
        "context": sidecar,
        "payload_sha256": hashlib.sha256(canonical).hexdigest(),
        "intake_version": INTAKE_VERSION,
        "downstream": "NOT_IMPLEMENTED",
        "downstream_status": "DOWNSTREAM_NOT_IMPLEMENTED",
        # SSOT: only a reliable Atlas durable receipt permits NODE cleanup. This
        # in-memory acceptance grants no deletion authority and emits no such ACK.
        "durable": False,
    }
