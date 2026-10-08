"""Deterministic simulated fixtures, not real observations or validated thresholds."""
import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from risk_algorithm import evaluate


def make_history(tilts=None, moisture=None):
    tilts = tilts or [0.2] * 6
    moisture = moisture or [32.0] * 6
    if len(tilts) != len(moisture):
        raise ValueError("示例数组长度必须一致")
    start = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
    return [
        {
            "node_id": "SIM-ALGO-001",
            "timestamp": (start + timedelta(seconds=10 * index)).isoformat().replace("+00:00", "Z"),
            "soil_moisture_pct": moisture[index],
            "tilt_deg": tilts[index],
            "battery_pct": 85,
            "sequence": index + 1,
            "source": "simulated",
        }
        for index in range(len(tilts))
    ]


def scenarios():
    normal = make_history()
    abnormal = make_history(
        tilts=[0.2, 0.2, 0.2, 1.5, 1.6, 1.7],
        moisture=[32, 32, 32, 34, 37, 40],
    )
    missing = deepcopy(normal)
    missing[-1]["soil_moisture_pct"] = None
    return {"normal": normal, "abnormal": abnormal, "missing": missing}


if __name__ == "__main__":
    print("仅为模拟数据与演示规则；不用于真实灾害预测。")
    for name, history in scenarios().items():
        print(json.dumps({"scenario": name, "result": evaluate(history)}, ensure_ascii=False))
