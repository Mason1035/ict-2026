"""从当前 E 盘仓库构建队员 A 的可复现接口 ZIP，不修改源文件。"""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path


HERE = Path(__file__).resolve().parent
B_ROOT = HERE.parent
REPO = HERE.parents[2]
E_ROOT = REPO.parent
DEFAULT_OUTPUT = E_ROOT / "队员A_B算法接口交接_v0.2_2026-10-02.zip"


def sources() -> dict[str, Path]:
    mapping = {
        name: HERE / name for name in (
            "README_给队员A.md", "B_TO_A_INTERFACE_DRAFT.md", "A_TO_B_DATA_HANDOFF.md",
            "RISK_CONFIG_DRAFT_NOT_LOADABLE.json", "golden_vectors.TEST_ONLY.json", "run_vectors.py",
        )
    }
    for name in ("__init__.py", "reference.py", "risk_math.py", "causal_window.py",
                 "test_reference.py", "test_causal_window.py"):
        mapping[f"candidate_features/{name}"] = B_ROOT / "candidate_features" / name
    for name in ("__init__.py", "check_experiment_csv.py", "README.md"):
        mapping[f"data_intake/{name}"] = B_ROOT / "data_intake" / name
    mapping["00_TEAM_SHARED_CONTRACT.pdf"] = REPO / "00_TEAM_SHARED_CONTRACT.pdf"
    mapping["01_硬件嵌入式与系统负责人开发文档.pdf"] = E_ROOT / "01_硬件嵌入式与系统负责人开发文档.pdf"
    mapping["02_算法与数据负责人开发文档.pdf"] = REPO / "docs" / "reference" / "02_算法与数据负责人开发文档.pdf"
    mapping["B_CODE_USAGE_AUDIT_2026-10-02.md"] = B_ROOT / "docs" / "B_CODE_USAGE_AUDIT_2026-10-02.md"
    return mapping


def build(output: Path) -> None:
    files = sources()
    missing = [str(path) for path in files.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError("缺少来源文件，拒绝构建：" + ", ".join(missing))
    if output.exists():
        raise FileExistsError(f"目标已存在，拒绝覆盖：{output}")
    manifest = {
        "status": "INTERFACE_DRAFT_DO_NOT_DEPLOY",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "source_repo": str(REPO),
        "files": {},
    }
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, path in sorted(files.items()):
            data = path.read_bytes()
            archive.writestr(name, data)
            manifest["files"][name] = {
                "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)
            }
        archive.writestr("MANIFEST.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="构建 B→A 接口草案 ZIP；已存在目标不覆盖")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    build(args.output)
