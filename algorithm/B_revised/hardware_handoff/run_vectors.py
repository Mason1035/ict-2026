"""运行 B→A 数学黄金向量；仅 TEST_ONLY，不启用实际 Risk 配置。"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
PACKAGE_ROOT = HERE if (HERE / "candidate_features").is_dir() else HERE.parent
sys.path.insert(0, str(PACKAGE_ROOT))

from candidate_features import reference, risk_math  # noqa: E402


FUNCTIONS = {
    name: getattr(module, name)
    for module, names in (
        (reference, (
            "gravity_tilt_change_deg", "causal_slope_per_second",
            "dynamic_accel_rms_mps2", "relative_wetness_index",
            "valid_probe_mean", "spatial_probe_spread",
            "dual_imu_tilt_difference_deg",
        )),
        (risk_math, ("sensor_score", "risk_level")),
    )
    for name in names
}


def equal(actual: object, expected: object) -> bool:
    if actual is None or expected is None:
        return actual is expected
    if isinstance(actual, (tuple, list)) and isinstance(expected, (tuple, list)):
        return len(actual) == len(expected) and all(equal(a, e) for a, e in zip(actual, expected))
    if isinstance(actual, bool) or isinstance(expected, bool):
        return actual is expected
    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        return math.isclose(actual, expected, rel_tol=0, abs_tol=1e-12)
    return actual == expected


def check_vectors(path: Path = HERE / "golden_vectors.TEST_ONLY.json") -> tuple[int, list[str]]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("status") != "TEST_ONLY_MATH_VECTORS_NOT_REAL_RISK":
        raise ValueError("拒绝非 TEST_ONLY 黄金向量文件")
    failures: list[str] = []
    vectors = document["vectors"]
    for vector in vectors:
        name = vector["name"]
        function = FUNCTIONS[vector["function"]]
        actual = function(*vector["args"])
        if not equal(actual, vector["expected"]):
            failures.append(f"{name}: actual={actual!r}, expected={vector['expected']!r}")
    return len(vectors), failures


if __name__ == "__main__":
    count, errors = check_vectors()
    for error in errors:
        print(error, file=sys.stderr)
    print(f"TEST_ONLY math vectors: {count - len(errors)}/{count} passed")
    raise SystemExit(1 if errors else 0)
