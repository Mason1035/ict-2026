"""严格 JSON、文件哈希与不可覆盖输出的共用工具。"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"重复 JSON 字段: {key}")
        result[key] = value
    return result


def loads(text):
    def reject(value):
        raise ValueError(f"非法非有限 JSON 值: {value}")
    def number(text):
        value = float(text)
        if not math.isfinite(value):
            raise ValueError("JSON 数值超出有限浮点范围")
        return value
    return json.loads(text, object_pairs_hook=_object, parse_constant=reject, parse_float=number)


def load(path):
    return loads(Path(path).read_text(encoding="utf-8-sig"))


def dump(path, value):
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inside(root, relative):
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError("文件名必须是包内非空相对路径")
    root = Path(root).resolve()
    target = (root / relative).resolve()
    if not target.is_relative_to(root):
        raise ValueError("路径超出交接目录")
    return target


def verify_manifest(root):
    root = Path(root)
    manifest = load(root / "manifest.json")
    if manifest.get("schema") != "B.local_artifact_manifest.v1" or not manifest.get("files"):
        raise ValueError("manifest 类型不符或文件清单为空")
    for name, entry in manifest["files"].items():
        path = inside(root, name)
        if not path.is_file() or path.stat().st_size != entry["bytes"] or sha256(path) != entry["sha256"]:
            raise ValueError(f"产物缺失或哈希不一致: {name}")
    actual = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    if actual != set(manifest["files"]) | {"manifest.json"}:
        raise ValueError("目录包含未登记产物")
    return manifest
