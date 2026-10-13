"""独立软件回放场景；不产生物理训练集或现场报警。"""
import copy

from telemetry_v2_intake.demo_runtime import fixture


def record(**kwargs):
    payload, context = fixture(**kwargs)
    return {"payload": payload, "context": context}


def scenarios():
    normal = record()
    corrupt = record(start=3010, end=3500, seq=2)
    corrupt["context"]["runtime_input"]["imu"]["top"][-1]["uptime_ms"] += 1
    stale = copy.deepcopy(normal)
    stale["payload"].update(seq=2, uptime_ms=4000)
    b = stale["context"]["runtime_input"]
    b["imu"] = {p: [] for p in ("top", "toe")}
    b["soil"] = {p: [] for p in ("top", "middle", "toe")}
    return {
        "normal": [normal], "abnormal": [record(scenario="abnormal")],
        "missing": [record(scenario="missing")], "duplicate": [normal, copy.deepcopy(normal)],
        "recovery": [normal, record(start=3010, end=3500, seq=2, scenario="missing"),
                     record(start=3510, end=4000, seq=3), record(start=4010, end=4500, seq=4),
                     record(start=4510, end=5000, seq=5)],
        "reboot": [normal, record(end=100, boot=2), record(start=110, end=1100, boot=2, seq=2)],
        "future_rejection": [normal, corrupt, record(start=3010, end=3500, seq=2)],
        "stale": [normal, stale]}


def check_scenario(name, outputs):
    results = [o["result"] for o in outputs]
    null = lambda r: all(v is None for v in r["risk"].values())
    expected = {
        "normal": lambda: results[-1]["risk"]["sensor_score"] == 5 and results[-1]["risk"]["level"] == "NORMAL",
        "abnormal": lambda: abs(results[-1]["risk"]["sensor_score"] - 75.47803014177) < 1e-8,
        "missing": lambda: null(results[-1]),
        "duplicate": lambda: results[-1]["processing"] == "DUPLICATE_NO_RECOMPUTE" and results[0]["risk"] == results[1]["risk"],
        "recovery": lambda: all(null(r) for r in results[1:4]) and results[-1]["risk"]["sensor_score"] == 5,
        "reboot": lambda: null(results[1]) and results[1]["processing"] == "SEGMENT_RESET" and results[-1]["risk"]["sensor_score"] == 5,
        "future_rejection": lambda: results[1]["processing"] == "INPUT_REJECTED_NO_STATE_CHANGE" and results[2]["risk"]["sensor_score"] == 5,
        "stale": lambda: null(results[-1])}
    if name not in expected or not expected[name]():
        raise AssertionError(f"TEST_ONLY 软件场景不符合预期: {name}")
    if any(r["mode"] != "TEST_ONLY" for r in results):
        raise AssertionError("软件夹具不能冒充实测")
    return {"status": "TEST_ONLY_EXPECTATIONS_MET", "records": len(results)}
