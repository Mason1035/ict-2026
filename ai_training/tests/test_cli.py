import json
import os
from pathlib import Path
import subprocess
import sys


def command(*args):
    root = Path(__file__).parents[1]
    env = dict(os.environ, PYTHONPATH=str(root / "src"), PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run([sys.executable, str(root / "scripts/validate_framework.py"), *map(str, args)],
                          env=env, text=True, capture_output=True)


def test_cli_self_test(tmp_path):
    result = command("--self-test", "--output-root", tmp_path)
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert all(summary["checks"].values())
    assert summary["onnx_export"] == "NOT_RUN"
    assert (Path(summary["evidence_directory"]) / "validation_summary.json").is_file()


def test_cli_missing_or_toy_contract_is_blocked(tmp_path):
    for args in ([], ["--contract", Path(__file__).parent / "fixtures/test_only_contract.json"]):
        result = command(*args, "--output-root", tmp_path)
        assert result.returncode == 2
        assert json.loads(result.stderr)["status"] == "BLOCKED_OR_FAILED"
        assert list(tmp_path.iterdir()) == []
