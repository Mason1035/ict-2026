"""TEST_ONLY / MOCK_ONLY fixture loader and sidecar checks; no production wire format."""

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

SUPPORTED_CASES = (
    "M01_NORMAL", "M02_MISSING_SENSOR", "M07_RISK_NOT_CALIBRATED", "M08_INVALID_SCHEMA",
)


def freeze(value):
    """One shared recursively read-only payload for sibling consumers."""
    if isinstance(value, dict):
        return MappingProxyType({key: freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(freeze(item) for item in value)
    return value


def plain(value):
    if isinstance(value, Mapping):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(item) for item in value]
    return value


def payload_hash(payload):
    encoded = json.dumps(plain(payload), ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _reject_constant(value):
    raise ValueError("Non-JSON numeric constant: " + value)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key: " + key)
        result[key] = value
    return result


@dataclass(frozen=True)
class LoadedCase:
    path: Path
    input_bytes: bytes
    input_sha256: str
    document: dict


def load_case(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    doc = json.loads(raw.decode("utf-8-sig"), parse_constant=_reject_constant,
                     object_pairs_hook=_unique_object)
    if not isinstance(doc, dict) or doc.get("case_id") not in SUPPORTED_CASES:
        raise ValueError("Only M01/M02/M07/M08 are supported")
    if path.stem != doc["case_id"]:
        raise ValueError("case_id does not match filename")
    if not isinstance(doc.get("messages"), list) or not doc["messages"]:
        raise ValueError("messages must be a nonempty list")
    # Source is checked before each message validation, with rejection evidence.
    return LoadedCase(path, raw, hashlib.sha256(raw).hexdigest(), doc)


def check_snapshot(snapshot, payload):
    """TEST_ONLY consistency check, called ONLY after source and v2 validation.

    This does not restore missing validity/timestamps to the production payload.
    Invalid arrays are ignored, never interpreted as observations.
    """
    errors = []
    if not isinstance(snapshot, dict) or set(snapshot) != {"imu", "soil"}:
        return ["sampling_snapshot: expected imu and soil arrays"]
    for group, size in (("imu", 2), ("soil", 3)):
        samples = snapshot[group]
        if not isinstance(samples, list) or len(samples) != size:
            errors.append(group + ": incorrect snapshot size")
            continue
        for index, sample in enumerate(samples):
            loc = "sampling_snapshot.%s[%d]" % (group, index)
            keys = ({"raw", "validity", "acquired_uptime_us"} if group == "soil" else
                    {"acceleration_mps2", "angular_rate_dps", "validity", "acquired_uptime_us"})
            if not isinstance(sample, dict) or set(sample) != keys:
                errors.append(loc + ": incorrect sample fields")
                continue
            validity = sample["validity"]
            if validity not in ("Valid", "Unavailable", "Error"):
                errors.append(loc + ": unknown validity")
                continue
            stamp = sample["acquired_uptime_us"]
            if stamp is not None and (type(stamp) is not int or not 0 <= stamp <= payload["uptime_ms"] * 1000):
                errors.append(loc + ": invalid acquisition time")
            if group == "soil":
                raw = sample["raw"]
                if raw is not None and (type(raw) is not int or not -32768 <= raw <= 32767):
                    errors.append(loc + ": invalid raw type/range")
                if raw != payload["soil"][("top_raw", "middle_raw", "toe_raw")[index]]:
                    errors.append(loc + ": raw mapping mismatch")
                if (validity == "Valid" and raw is None) or (validity != "Valid" and raw is not None):
                    errors.append(loc + ": raw/validity mismatch")
            else:
                axes = []
                for key in ("acceleration_mps2", "angular_rate_dps"):
                    vector = sample[key]
                    if (not isinstance(vector, list) or len(vector) != 3 or
                            any(type(x) not in (int, float) or not math.isfinite(x) for x in vector)):
                        errors.append(loc + ": invalid numeric array")
                    else:
                        axes.extend(vector)
                imu = payload["imu"][index]
                if imu["valid"] != (validity == "Valid"):
                    errors.append(loc + ": validity projection mismatch (G02 remains OPEN)")
                values = [imu[key] for key in ("ax", "ay", "az", "gx", "gy", "gz")]
                if validity == "Valid" and values != axes:
                    errors.append(loc + ": IMU component mapping mismatch")
                if validity != "Valid" and any(value is not None for value in values):
                    errors.append(loc + ": invalid IMU placeholder leaked into payload")
    return errors
