"""Content identity and explicitly owned RNG; wall-clock metadata is separate."""

import hashlib
import json
import platform
from pathlib import Path
import subprocess
import inspect

import numpy as np

from ai_training.errors import IntegrityError


def canonical_bytes(value):
    # Strict JSON keeps unknown objects/non-finite numbers from silently changing
    # identities. List order (especially features) is significant; key order is not.
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def content_hash(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def seeded_rng(seed):
    if type(seed) is not int or seed < 0:
        raise ValueError("seed: require nonnegative integer; supply an explicit training seed")
    # No global NumPy/Python seed mutation. Components receive this Generator and
    # checkpoints retain its state. Future backends must declare determinism limits.
    return np.random.default_rng(seed)


def environment_identity():
    package = Path(__file__).resolve().parents[1]
    files = {str(p.relative_to(package)): file_hash(p) for p in sorted(package.rglob("*.py"))}
    try:
        revision = subprocess.run(["git", "-C", str(package), "rev-parse", "HEAD"],
                                  capture_output=True, text=True)
        revision_id = revision.stdout.strip() if revision.returncode == 0 else None
    except FileNotFoundError:
        revision_id = None  # Git is optional; the source content hash is not.
    return {
        "dependency_versions": {"python": platform.python_version(), "numpy": np.__version__},
        "platform": {"system": platform.system(), "machine": platform.machine()},
        "source_code_revision": revision_id,
        "source_tree_hash": content_hash(files),
    }


def implementation_hashes(components):
    """Include injected code outside this package in the experiment identity."""
    result = {}
    for name, component in components.items():
        if component is None:
            result[name] = None
            continue
        target = component if inspect.isclass(component) or inspect.isfunction(component) else type(component)
        try:
            path = inspect.getsourcefile(target)
        except (TypeError, OSError) as exc:
            raise IntegrityError(f"component {name} has no traceable Python source; supply an importable versioned implementation") from exc
        if path is None or not Path(path).is_file():
            raise IntegrityError(f"component {name} has no traceable Python source; provide a versioned implementation")
        result[name] = {"qualified_name": target.__qualname__, "source_file_hash": file_hash(path)}
    return result


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise IntegrityError(f"duplicate JSON key {key!r}; identity is ambiguous; fix the source file")
        result[key] = value
    return result


def read_json(path):
    def invalid(value):
        raise IntegrityError(f"non-finite JSON {value}; use explicit null only where allowed")
    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=_unique_object,
                      parse_constant=invalid)


def write_json_exclusive(path, value):
    data = canonical_bytes(value) + b"\n"
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # 'x' protects prior experiment evidence, including same-content replays.
    with path.open("xb") as stream:
        stream.write(data)
    return file_hash(path)
