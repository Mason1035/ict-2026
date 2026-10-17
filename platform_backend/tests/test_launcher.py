"""Exercise the real launcher against isolated tool shims, without starting services."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import time

import pytest


LAUNCHER = Path(__file__).resolve().parents[2] / "scripts" / "run-platform.sh"
TOOL = '''#!__PYTHON__
from pathlib import Path
import json, os, sys
args = sys.argv[1:]
name = Path(sys.argv[0]).name
with open(os.environ["PLATFORM_TEST_LOG"], "a") as log:
    log.write(json.dumps([name, *args]) + "\\n")
if name == "node":
    sys.exit(0)
if name == "npm":
    if args == ["ci"]:
        Path("node_modules").mkdir(exist_ok=True)
        sys.exit(1 if os.environ.get("PLATFORM_TEST_FAIL_NPM") else 0)
    if args == ["run", "build"]:
        Path("dist").mkdir(exist_ok=True)
        Path("dist/index.html").write_text(Path("src/main.ts").read_text())
        sys.exit(0)
    sys.exit(2)
if args[:2] == ["-m", "venv"]:
    target = Path(args[2]) / "bin/python"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(Path(__file__).read_text())
    target.chmod(0o755)
elif args[:2] == ["-m", "pip"]:
    sys.exit(1 if os.environ.get("PLATFORM_TEST_FAIL_PIP") else 0)
elif args[:2] == ["-m", "uvicorn"]:
    sys.exit(0)
elif args[:1] != ["-c"]:
    sys.exit(2)
'''


@pytest.fixture
def installation(tmp_path):
    repo = tmp_path / "repo with spaces"
    app = repo / "apps/geohazard-demo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "platform_backend").mkdir()
    shutil.copy2(LAUNCHER, repo / "scripts/run-platform.sh")
    (repo / "platform_backend/pyproject.toml").write_text("backend-v1")
    (app / "src").mkdir(parents=True)
    (app / "public").mkdir()
    for file in ("index.html", "package.json", "package-lock.json", "vite.config.ts", "tsconfig.json", "src/main.ts"):
        (app / file).write_text("initial")
    binaries = tmp_path / "bin"
    binaries.mkdir()
    for name in ("python3", "node", "npm"):
        path = binaries / name
        path.write_text(TOOL.replace("__PYTHON__", sys.executable))
        path.chmod(0o755)
    log = tmp_path / "commands.jsonl"
    env = {**os.environ, "PATH": str(binaries) + os.pathsep + os.environ["PATH"], "PLATFORM_TEST_LOG": str(log)}
    env.pop("GEOHAZARD_PYTHON", None)
    env.pop("GEOHAZARD_PORT", None)

    def run(**extra):
        return subprocess.run(["bash", "scripts/run-platform.sh"], cwd=repo,
                              env={**env, **extra}, capture_output=True, text=True, timeout=10)

    def commands():
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    return repo, app, run, commands


def count(commands, prefix):
    return sum(command[1:1 + len(prefix)] == prefix for command in commands)


def newer(path):
    # Explicit mtimes avoid sleeps and filesystem timestamp resolution races.
    stamp = time.time() + 3
    os.utime(path, (stamp, stamp))


def test_fresh_install_and_unchanged_restart_skip_reinstall(installation):
    repo, app, run, commands = installation
    first = run(GEOHAZARD_PORT="8001")
    assert first.returncode == 0, first.stderr
    assert "http://127.0.0.1:8001" in first.stdout
    assert (app / "dist/index.html").read_text() == "initial"
    assert count(commands(), ["-m", "pip"]) == 1
    assert count(commands(), ["ci"]) == 1
    assert count(commands(), ["run", "build"]) == 1
    assert run().returncode == 0
    assert count(commands(), ["-m", "pip"]) == 1
    assert count(commands(), ["ci"]) == 1
    assert count(commands(), ["run", "build"]) == 1
    assert count(commands(), ["-m", "uvicorn"]) == 2


def test_source_update_rebuilds_existing_page_without_reinstall(installation):
    _, app, run, commands = installation
    assert run().returncode == 0
    source = app / "src/main.ts"
    source.write_text("updated-page")
    newer(source)
    assert run().returncode == 0
    assert (app / "dist/index.html").read_text() == "updated-page"
    assert count(commands(), ["run", "build"]) == 2
    assert count(commands(), ["ci"]) == 1


def test_dependency_changes_refresh_only_affected_installation(installation):
    repo, app, run, commands = installation
    assert run().returncode == 0
    newer(repo / "platform_backend/pyproject.toml")
    newer(app / "package-lock.json")
    assert run().returncode == 0
    assert count(commands(), ["-m", "pip"]) == 2
    assert count(commands(), ["ci"]) == 2
    assert count(commands(), ["run", "build"]) == 2


def test_partial_backend_install_is_retried_next_launch(installation):
    repo, _, run, commands = installation
    assert run(PLATFORM_TEST_FAIL_PIP="1").returncode != 0
    assert (repo / "platform_backend/.venv/bin/python").exists()
    assert count(commands(), ["-m", "uvicorn"]) == 0
    assert run().returncode == 0
    assert count(commands(), ["-m", "pip"]) == 2


def test_partial_frontend_install_is_retried_next_launch(installation):
    _, app, run, commands = installation
    assert run(PLATFORM_TEST_FAIL_NPM="1").returncode != 0
    assert (app / "node_modules").is_dir()
    assert count(commands(), ["-m", "uvicorn"]) == 0
    assert run().returncode == 0
    assert count(commands(), ["ci"]) == 2
    assert count(commands(), ["-m", "pip"]) == 1


@pytest.mark.parametrize("port", ["0", "65536", "-1", "8000/path", "abc"])
def test_invalid_port_does_not_install_or_start_services(installation, port):
    _, _, run, commands = installation
    result = run(GEOHAZARD_PORT=port)
    assert result.returncode != 0
    assert "GEOHAZARD_PORT" in result.stderr
    assert commands() == []
