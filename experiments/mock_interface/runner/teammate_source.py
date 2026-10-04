"""TEST_ONLY / INTEGRATION_ADAPTER: execute reviewed, hash-pinned Git blobs unchanged.

No checkout, merge, source rewriting, network access or teammate package install.
Only the manifest's minimal source dependency closure is loaded into memory.
"""

from contextlib import contextmanager
from functools import lru_cache
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import threading
import types

from mock_loader import plain

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = Path(__file__).with_name("teammate_sources.json")
_IMPORT_LOCK = threading.RLock()


def source_spec(target):
    return json.loads(MANIFEST.read_text(encoding="utf-8"))["targets"][target]


def git(*args):
    return subprocess.check_output(
        ["git", "--no-optional-locks", "-c", "safe.directory=" + ROOT.as_posix(),
         "-C", str(ROOT), *args], stderr=subprocess.PIPE)


@lru_cache(maxsize=16)
def _read_source(commit, path, digest, blob):
    source = git("show", commit + ":" + path)
    actual_blob = hashlib.sha1(b"blob " + str(len(source)).encode("ascii") + b"\0" + source).hexdigest()
    if hashlib.sha256(source).hexdigest() != digest or actual_blob != blob:
        raise ValueError("Pinned teammate source hash mismatch: " + path)
    return source


@contextmanager
def target_modules(target):
    """Isolate original import names; refuse to reuse or overwrite other modules."""
    spec = source_spec(target)
    modules = spec["modules"]
    prefix = modules[0]["name"]
    with _IMPORT_LOCK:
        if any(name == prefix or name.startswith(prefix + ".") for name in sys.modules):
            raise RuntimeError("Refusing to shadow existing teammate namespace: " + prefix)
        loaded = {}
        try:
            for item in modules:
                source = _read_source(spec["source_commit"], item["path"], item["sha256"], item["git_blob"])
                origin = "git:" + spec["source_commit"] + ":" + item["path"]
                module = types.ModuleType(item["name"])
                module.__file__ = origin
                module.__package__ = item["name"] if item["package"] else item["name"].rpartition(".")[0]
                module.__spec__ = importlib.util.spec_from_loader(item["name"], loader=None, is_package=item["package"])
                if item["package"]:
                    module.__path__ = []
                sys.modules[item["name"]] = module
                parent, _, child = item["name"].rpartition(".")
                if parent in loaded:
                    setattr(loaded[parent], child, module)
                # Execute EXACT bytes from the pinned, verified teammate commit.
                exec(compile(source, origin, "exec"), module.__dict__)
                loaded[item["name"]] = module
            yield loaded
        finally:
            for name in list(sys.modules):
                if name == prefix or name.startswith(prefix + "."):
                    del sys.modules[name]


def invoke_real(target, module_name, function, *args, expected_exception=None, **kwargs):
    """Record actual entry into the pinned function frame, including expected blocks.

    Adapter execution or successful import alone NEVER establishes REAL_CODE_REACHED.
    """
    spec = source_spec(target)
    item = next(m for m in spec["modules"] if m["name"] == module_name)
    origin = "git:" + spec["source_commit"] + ":" + item["path"]
    code = function.__code__
    if code.co_filename != origin or function.__module__ != module_name:
        raise ValueError("Refusing an unpinned/replaced teammate function")
    entered = False
    previous = sys.getprofile()

    def observe(frame, event, arg):
        nonlocal entered
        if event == "call" and frame.f_code is code:
            entered = True
        if previous is not None:
            previous(frame, event, arg)

    record = {
        "integration_target": spec["integration_target"], "source_branch": spec["source_branch"],
        "source_commit": spec["source_commit"], "source_module": item["path"],
        "source_function": function.__qualname__, "source_sha256": item["sha256"],
        "source_git_blob": item["git_blob"], "source_line": code.co_firstlineno,
        "arguments": {"args": plain(args), "kwargs": plain(kwargs)},
        "real_code_called": False, "call_status": "NOT_CALLED",
    }
    try:
        sys.setprofile(observe)
        value = function(*args, **kwargs)
        record.update(call_status="RETURNED", returned=plain(value))
    except Exception as exc:
        expected = expected_exception is not None and isinstance(exc, expected_exception)
        record.update(call_status="EXPECTED_BLOCK" if expected else "FAIL",
                      exception_type=type(exc).__name__, exception_message=str(exc))
    finally:
        sys.setprofile(previous)
        record["real_code_called"] = entered
        record["reach_status"] = "REAL_CODE_REACHED" if entered else "NOT_CALLED"
    return record


def initial_result(target, payload_sha256):
    spec = source_spec(target)
    return {
        "scope": "TEST_ONLY / INTEGRATION_ADAPTER",
        "integration_target": spec["integration_target"], "source_branch": spec["source_branch"],
        "source_commit": spec["source_commit"], "payload_sha256": payload_sha256,
        "real_code_called": False, "reach_status": "NOT_CALLED", "calls": [],
        "adapter_status": "NOT_INTEGRATED", "execution_status": "BLOCKED",
    }
