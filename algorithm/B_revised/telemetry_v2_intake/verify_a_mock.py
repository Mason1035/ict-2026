"""只读运行 A 分支的 TEST_ONLY Validator/cases，对照 B 的正式入口。

本脚本不把 TEST_ONLY Validator 当成生产实现，也不修改 A 分支或复制其代码。
需本地已有 origin/李青原（先 git fetch）；从仓库根目录运行本脚本。
"""

from __future__ import annotations

import json
import subprocess
import sys
import types
from pathlib import Path


B_ROOT = Path(__file__).resolve().parent.parent
REPO = B_ROOT.parent.parent
sys.path.insert(0, str(B_ROOT))

from telemetry_v2_intake import evaluate_telemetry_v2  # noqa: E402


REF = "origin/李青原"
BASE = "experiments/mock_interface"
CASES = ("M01_NORMAL", "M02_MISSING_SENSOR", "M07_RISK_NOT_CALIBRATED", "M08_INVALID_SCHEMA")


def git_show(path: str) -> bytes:
    result = subprocess.run(["git", "show", f"{REF}:{path}"], cwd=REPO,
                            capture_output=True, check=True)
    return result.stdout


def main() -> None:
    source = git_show(f"{BASE}/runner/mock_v2_validator.py").decode("utf-8")
    validator = types.ModuleType("a_test_only_mock_v2_validator")
    exec(compile(source, f"{REF}:{BASE}/runner/mock_v2_validator.py", "exec"),
         validator.__dict__)
    commit = subprocess.check_output(["git", "rev-parse", REF], cwd=REPO, text=True).strip()
    results = {}
    for case_id in CASES:
        case = json.loads(git_show(f"{BASE}/cases/{case_id}.json"))
        entry_calls = 0
        accepted = 0
        rejected = 0
        for message in case["messages"]:
            payload = message["payload"]
            decision = validator.validate(payload)
            if decision["status"] == "REJECT":
                rejected += 1
                continue
            accepted += 1
            entry_calls += 1
            result = evaluate_telemetry_v2(
                payload, context={"sampling_snapshot": message.get("sampling_snapshot")})
            assert result["status"] == "REAL_CODE_REACHED"
            assert result["risk_execution"] == "RISK_EXECUTION_BLOCKED"
            assert result["risk"] == payload["risk"]
            assert len(result["function_calls"]) == 4
            if case_id == "M02_MISSING_SENSOR":
                assert result["observations"]["soil"]["middle_raw"] is None
                assert result["feature_details"]["soil_relative_index"]["middle"] == (
                    "MISSING_OBSERVATION_CAUSE_UNKNOWN")
        if case_id == "M08_INVALID_SCHEMA":
            assert (accepted, rejected, entry_calls) == (0, 4, 0)
        else:
            assert (accepted, rejected, entry_calls) == (1, 0, 1)
        results[case_id] = {"accepted": accepted, "rejected": rejected,
                            "b_entry_calls": entry_calls}
    print(json.dumps({"status": "B_ENTRY_TEST_ONLY_MOCK_COMPATIBILITY_PASS",
                      "not_formal_risk_or_three_person_pass": True,
                      "a_ref": commit, "cases": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
