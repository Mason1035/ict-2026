"""构建 B 的可独立回放软件交接包，不含环境/实测数据/队友代码。"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath

B_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(B_ROOT))


def source_files(root=B_ROOT):
    root = Path(root)
    names = {"run_independent.py", "RUN_LOCAL.cmd", "LOCAL_WORK_GUIDE.md", "LICENSE"}
    for package in ("candidate_features", "data_intake", "evaluation", "telemetry_v2_intake", "local_tools", "contracts"):
        for path in (root / package).iterdir():
            if path.is_file() and path.suffix in (".py", ".json", ".md"):
                names.add(path.relative_to(root).as_posix())
    for name in ("__init__.py", "test_handoff.py", "run_vectors.py", "golden_vectors.TEST_ONLY.json",
                 "RISK_CONFIG_DRAFT_NOT_LOADABLE.json"):
        names.add("hardware_handoff/" + name)
    files = {name: root / name for name in sorted(names)}
    if any(not p.is_file() for p in files.values()):
        raise FileNotFoundError("交接包来源不完整，拒绝构建")
    return files


def build(output, *, root=B_ROOT):
    output = Path(output)
    files = source_files(root)
    if output.exists():
        raise FileExistsError("ZIP 已存在，拒绝覆盖: " + str(output))
    manifest = {"schema": "B.software_package.v1", "scope": "TEST_ONLY_AND_UNCALIBRATED_TOOLS",
                "formal_training_ready": False, "calibrated_runtime_ready": False,
                "minimum_python": "3.11", "third_party_dependencies": [], "files": {}}
    try:
        repo = Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], cwd=root,
                                           text=True, stderr=subprocess.DEVNULL, timeout=5).strip())
        if (repo / "algorithm" / "B_revised").resolve() != Path(root).resolve():
            raise ValueError("解压后的工具目录不是原始 Git checkout")
        manifest["source_git_head"] = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True, stderr=subprocess.DEVNULL, timeout=5).strip()
    except (OSError, ValueError, subprocess.SubprocessError):
        manifest["source_git_head"] = None
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, path in files.items():
            data = path.read_bytes()
            archive.writestr(name, data)
            manifest["files"][name] = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
        archive.writestr("PACKAGE_MANIFEST.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    verify(output)
    return manifest


def verify(path):
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(set(names)) != len(names):
            raise ValueError("ZIP 含重复文件名")
        for name in names:
            p = PurePosixPath(name)
            if p.is_absolute() or ".." in p.parts or "\\" in name or ":" in name:
                raise ValueError("ZIP 路径不安全")
        manifest = json.loads(archive.read("PACKAGE_MANIFEST.json"))
        if manifest.get("schema") != "B.software_package.v1":
            raise ValueError("ZIP manifest 类型不匹配")
        if set(names) != set(manifest["files"]) | {"PACKAGE_MANIFEST.json"}:
            raise ValueError("ZIP 含未登记文件")
        for name, entry in manifest["files"].items():
            data = archive.read(name)
            if len(data) != entry["bytes"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
                raise ValueError("ZIP 文件哈希不一致: " + name)
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description="B 独立软件交接包；不包含真实数据、环境或完整团队工程")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args(argv)
    try:
        if bool(args.output) == bool(args.verify):
            parser.error("--output / --verify 二选一")
        result = verify(args.verify) if args.verify else build(args.output)
        print(json.dumps({"status": "SOFTWARE_PACKAGE_HASHES_VERIFIED_ONLY",
                          "files": len(result["files"]), "formal_training_ready": False}))
        return 0
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
