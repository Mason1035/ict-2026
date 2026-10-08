"""审计拟议 run/parent_run 划分，避免来源跨 Train/Validation/Test。

输入只是 B 的划分计划草案，不是正式 Training Contract 或模型训练入口。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path


SPLITS = {"train", "validation", "test"}
REQUIRED = {"run_id", "parent_run", "split", "is_synthetic"}


def audit_split_plan(entries: list[dict]) -> dict:
    issues: list[dict] = []
    counts = Counter()
    group_splits: dict[str, set[str]] = defaultdict(set)
    real_roots: dict[str, set[str]] = defaultdict(set)
    seen_runs: set[str] = set()
    synthetic_entries: list[tuple[int, str]] = []

    def fail(code: str, row: int, detail: str) -> None:
        issues.append({"code": code, "entry": row, "detail": detail})

    if not isinstance(entries, list):
        return {"status": "INVALID_PLAN", "issues": [{"code": "NOT_A_LIST", "entry": 0,
                 "detail": "entries 必须是列表"}], "counts": {}, "formal_training_ready": False}
    if not entries:
        fail("EMPTY_PLAN", 0, "划分计划没有 run；请等待真实 run 交接")

    for row_number, item in enumerate(entries, start=1):
        if not isinstance(item, dict) or not REQUIRED <= set(item):
            fail("MISSING_FIELDS", row_number, "每项必须包含 run_id、parent_run、split、is_synthetic")
            continue
        run_id, parent_run, split, synthetic = (item[name] for name in
                                               ("run_id", "parent_run", "split", "is_synthetic"))
        if not isinstance(run_id, str) or not run_id.strip():
            fail("INVALID_RUN_ID", row_number, "run_id 必须是非空字符串")
            continue
        if parent_run is not None and (not isinstance(parent_run, str) or not parent_run.strip()):
            fail("INVALID_PARENT_RUN", row_number, "parent_run 只能为非空字符串或 null")
            continue
        if not isinstance(split, str) or split not in SPLITS or type(synthetic) is not bool:
            fail("INVALID_SPLIT_OR_SOURCE", row_number, "split 为 train/validation/test，is_synthetic 为布尔值")
            continue
        if synthetic and parent_run is None:
            fail("SYNTHETIC_WITHOUT_PARENT", row_number, "合成数据必须给出真实母 run")
            continue
        root = parent_run if parent_run is not None else run_id
        if run_id in seen_runs:
            fail("DUPLICATE_RUN_ID", row_number, f"run_id={run_id} 重复；即使内容相同也须去重")
            continue
        seen_runs.add(run_id)
        counts[split] += 1
        group_splits[root].add(split)
        if synthetic:
            synthetic_entries.append((row_number, root))
            if split != "train":
                fail("SYNTHETIC_OUTSIDE_TRAIN", row_number, "合成数据只能属于 Train")
        else:
            real_roots[root].add(split)

    for root, assigned in group_splits.items():
        if len(assigned) > 1:
            fail("PARENT_GROUP_LEAKAGE", 0, f"母 run {root!r} 横跨 {sorted(assigned)}")
    for row_number, root in synthetic_entries:
        if real_roots.get(root) != {"train"}:
            fail("SYNTHETIC_PARENT_NOT_REAL_TRAIN", row_number,
                 f"合成记录的母 run {root!r} 必须对应本计划中的 Train 真实 run")

    real_test_groups = {root for root, assigned in real_roots.items() if assigned == {"test"}}
    notes = ["仅检查分组与来源；不验证真实标签、采样、校准、独立性或样本量。",
             "此结果不能把 DRAFT 契约提升为正式训练就绪。"]
    if not real_test_groups:
        notes.append("尚无独立 Real Test 组；不能报告真实泛化结论。")
    return {
        "status": "STRUCTURE_CHECKED_ONLY" if not issues else "REVIEW_REQUIRED",
        "formal_training_ready": False,
        "counts": dict(counts),
        "real_test_groups": sorted(real_test_groups),
        "issues": issues,
        "notes": notes,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="审计 B 的拟议 run 划分；永不声明正式训练就绪")
    parser.add_argument("plan_json", type=Path, help='JSON 文件：{"entries": [...]}')
    args = parser.parse_args(argv)
    try:
        document = json.loads(args.plan_json.read_text(encoding="utf-8"))
        entries = document["entries"] if isinstance(document, dict) else document
        result = audit_split_plan(entries)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "INVALID_PLAN", "reason": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "STRUCTURE_CHECKED_ONLY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
