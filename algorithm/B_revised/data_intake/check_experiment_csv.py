"""检查团队 v2 实验 CSV；只报告事实，不自动清洗或填补缺测。"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path


HEADER = (
    "run_id", "timestamp_ms",
    "top_ax", "top_ay", "top_az", "top_gx", "top_gy", "top_gz",
    "toe_ax", "toe_ay", "toe_az", "toe_gx", "toe_gy", "toe_gz",
    "soil_top_raw", "soil_middle_raw", "soil_toe_raw",
    "flow_lpm", "rain_level", "label",
)
NUMERIC = set(HEADER) - {"run_id", "label"}
INTEGER = {"timestamp_ms", "soil_top_raw", "soil_middle_raw", "soil_toe_raw", "rain_level"}
LABELS = {"NORMAL", "RAIN", "SLIP"}
CHANNELS = tuple(name for name in HEADER if name not in {"run_id", "timestamp_ms", "label"})


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_csv(path: Path) -> dict:
    """返回可序列化报告。空单元格表示缺测，绝不按 0 处理。"""
    report = {
        "schema": "zhifang.experiment.csv.v2",
        "file": str(path.resolve()),
        "sha256": _sha256(path),
        "status": "INVALID",
        "row_count": 0,
        "runs": {},
        "missing_count": {name: 0 for name in HEADER},
        "issues": [],
        "notes": [
            "本报告仅为 CSV 初检；未验证校准、通道采样时刻、有效性标志或标签真实性。",
            "未自动插值、滤波、删行或生成模型特征；缺测不等于 0。",
        ],
    }

    def issue(code: str, line: int | None, detail: str) -> None:
        report["issues"].append({"code": code, "line": line, "detail": detail})

    try:
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.reader(stream, strict=True)
            try:
                actual_header = next(reader)
            except StopIteration:
                issue("EMPTY_FILE", None, "CSV 文件为空")
                return report
            if actual_header != list(HEADER):
                issue("HEADER_MISMATCH", 1, "必须严格使用团队契约的 20 列及固定顺序")
                report["actual_header"] = actual_header
                report["expected_header"] = list(HEADER)
                return report

            runs: dict[str, dict] = defaultdict(lambda: {
                "rows": 0, "first_timestamp_ms": None, "last_timestamp_ms": None,
                "time_reversals": 0, "duplicate_timestamps": 0,
                "median_positive_interval_ms": None, "largest_positive_gap_ms": None,
                "labels": Counter(),
                "channels": {name: {"observed": 0, "missing": 0, "min": None, "max": None}
                             for name in CHANNELS},
            })
            intervals: dict[str, list[int]] = defaultdict(list)
            last_ts: dict[str, int] = {}
            seen_ts: dict[str, set[int]] = defaultdict(set)
            for line, values in enumerate(reader, start=2):
                if not values or (len(values) == 1 and not values[0].strip()):
                    continue
                report["row_count"] += 1
                if len(values) != len(HEADER):
                    issue("COLUMN_COUNT", line, f"期望 20 列，实际 {len(values)} 列")
                    continue
                row = dict(zip(HEADER, values))
                run_id = row["run_id"].strip()
                if not run_id:
                    issue("MISSING_RUN_ID", line, "run_id 不可为空")
                else:
                    runs[run_id]["rows"] += 1

                for field in HEADER:
                    value = row[field].strip()
                    if not value:
                        report["missing_count"][field] += 1
                        if run_id and field in CHANNELS:
                            runs[run_id]["channels"][field]["missing"] += 1
                        continue
                    if field in NUMERIC:
                        try:
                            if field in INTEGER and not re.fullmatch(r"[+-]?\d+", value):
                                raise ValueError("not integer text")
                            number = float(value)
                            if not math.isfinite(number):
                                raise ValueError("non-finite")
                            if run_id and field in CHANNELS:
                                channel = runs[run_id]["channels"][field]
                                channel["observed"] += 1
                                channel["min"] = number if channel["min"] is None else min(channel["min"], number)
                                channel["max"] = number if channel["max"] is None else max(channel["max"], number)
                        except ValueError:
                            issue("INVALID_NUMBER", line, f"{field} 必须是有限数值；实际 {value!r}")
                    elif field == "label" and value not in LABELS:
                        issue("INVALID_LABEL", line, f"label 仅允许 NORMAL/RAIN/SLIP 或留空；实际 {value!r}")

                label = row["label"].strip()
                if run_id and label in LABELS:
                    runs[run_id]["labels"][label] += 1
                ts_text = row["timestamp_ms"].strip()
                if run_id and ts_text:
                    try:
                        timestamp = int(ts_text)
                    except ValueError:
                        continue  # 上方 INVALID_NUMBER 已记录；科学记数法亦不作为时间戳接受
                    state = runs[run_id]
                    if state["first_timestamp_ms"] is None:
                        state["first_timestamp_ms"] = timestamp
                    state["last_timestamp_ms"] = timestamp
                    if timestamp in seen_ts[run_id]:
                        state["duplicate_timestamps"] += 1
                        issue("DUPLICATE_TIMESTAMP", line, f"run_id={run_id} 的 timestamp_ms 重复")
                    seen_ts[run_id].add(timestamp)
                    if run_id in last_ts:
                        delta = timestamp - last_ts[run_id]
                        if delta < 0:
                            state["time_reversals"] += 1
                            issue("TIME_REVERSAL", line, f"run_id={run_id} 时间倒退 {abs(delta)} ms")
                        elif delta > 0:
                            intervals[run_id].append(delta)
                    last_ts[run_id] = timestamp

            if report["row_count"] == 0:
                issue("NO_DATA_ROWS", None, "CSV 没有数据行")
            for run_id, state in runs.items():
                if intervals[run_id]:
                    state["median_positive_interval_ms"] = statistics.median(intervals[run_id])
                    state["largest_positive_gap_ms"] = max(intervals[run_id])
                state["labels"] = dict(state["labels"])
                report["runs"][run_id] = state
            report["status"] = "CSV_CHECKED" if not report["issues"] else "REVIEW_REQUIRED"
            return report
    except (UnicodeError, csv.Error) as exc:
        issue("CSV_READ_ERROR", None, str(exc))
        return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="智哨防灾 v2 实验 CSV 初检；不生成训练就绪声明")
    parser.add_argument("csv_path", type=Path, help="队员 A 交付的原始实验 CSV")
    parser.add_argument("--output", type=Path, help="可选：将 JSON 报告另存到此路径；默认打印到终端")
    args = parser.parse_args(argv)
    try:
        report = inspect_csv(args.csv_path)
    except OSError as exc:
        parser.error(str(exc))
    output = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(output, encoding="utf-8")
        print(f"报告已写入：{args.output}")
    else:
        sys.stdout.write(output)
    return 0 if report["status"] == "CSV_CHECKED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
