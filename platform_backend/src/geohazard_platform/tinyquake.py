"""Experimental phase-classification sidecar; never writes telemetry or alarms."""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import json
import math
import re
from uuid import uuid4

from .database import utc_now
from .telemetry import IngestionError

MODEL_SHA256 = "0e1eb00a920ae3daaec7cf142ef8a54373fe1b93b472350e7048b8ae0c1ff1f1"
SCHEMA = "zhifang.tinyquake.result.v1"
CLASSES = ["P-wave", "S-wave", "Noise"]
FIELDS = {"schema", "site_id", "device_id", "sensor_id", "boot_id", "seq", "model_sha256",
          "input_source", "sample_rate_hz", "sample_count", "probabilities", "inference_us",
          "quality_valid", "quality_reason", "reference_index", "window_start_uptime_ms",
          "window_end_uptime_ms", "frame_id", "calibration_version", "preprocessing_id"}


def fail(message, status=422):
    raise IngestionError(status, {"message": message})


def validate(payload, source, topic=None):
    if not isinstance(payload, dict) or set(payload) != FIELDS:
        fail("TinyQuake 消息字段不符合独立 result.v1 协议")
    if payload["schema"] != SCHEMA or payload["model_sha256"] != MODEL_SHA256:
        fail("TinyQuake schema 或模型 SHA-256 与已评估 CNN17 不一致")
    for field in ("site_id", "device_id", "sensor_id"):
        if not isinstance(payload[field], str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", payload[field]):
            fail(f"{field} 必须是 ASCII 字母、数字、下划线或连字符")
    for field in ("boot_id", "seq", "inference_us"):
        if type(payload[field]) is not int or not 0 <= payload[field] <= 2**53 - 1:
            fail(f"{field} 必须是非负安全整数")
    if type(payload["sample_rate_hz"]) not in (float, int) or payload["sample_rate_hz"] != 40 or type(payload["sample_count"]) is not int or payload["sample_count"] != 80:
        fail("CNN17 要求 40 Hz / 80 样点 / 三分量输入")
    mode = payload["input_source"]
    if source not in {"MOCK", "REAL"} or not isinstance(mode, str) or mode not in {"REFERENCE", "SENSOR"}:
        fail("来源必须为 MOCK/REAL，输入类型必须为 REFERENCE/SENSOR")
    if mode == "REFERENCE" and source != "MOCK":
        fail("参考波形只能通过 MOCK 连接器接收，不能标为真实采集")
    if type(payload["quality_valid"]) is not bool:
        fail("quality_valid 必须是布尔值")
    for field in ("quality_reason", "preprocessing_id"):
        if not isinstance(payload[field], str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", payload[field]):
            fail(f"{field} 必须为非空可读标识")
    if mode == "REFERENCE":
        if type(payload["reference_index"]) is not int or payload["reference_index"] not in {0, 2, 3}:
            fail("reference_index 必须为已交付参考向量的 NPZ 行号 0/2/3")
        if any(payload[key] is not None for key in ("window_start_uptime_ms", "window_end_uptime_ms", "frame_id", "calibration_version")):
            fail("参考波形不应伪造采集时间、坐标或校准信息")
    else:
        if payload["reference_index"] is not None:
            fail("传感器数据不得带参考向量编号")
        start, end = payload["window_start_uptime_ms"], payload["window_end_uptime_ms"]
        if type(start) is not int or type(end) is not int or not 0 <= start < end <= 2**53 - 1:
            fail("SENSOR 必须提供有效、递增的采样窗 uptime")
        for field in ("frame_id", "calibration_version"):
            if payload[field] is not None and (not isinstance(payload[field], str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", payload[field])):
                fail(f"{field} 必须为标识或 null，不能编造校准值")
    values = payload["probabilities"]
    if payload["quality_valid"]:
        if not isinstance(values, list) or len(values) != 3 or any(type(n) not in (int, float) or not 0 <= n <= 1 or not math.isfinite(n) for n in values) or abs(sum(values) - 1) > .001:
            fail("有效输出必须是按 P/S/Noise 排列且和为 1 的三个有限分数")
    elif values is not None:
        fail("无效窗口必须使用 probabilities=null，不得输出可信分类")
    expected = f"zhifang/experimental/tinyquake/v1/{payload['site_id']}/{payload['device_id']}/{payload['sensor_id']}/result"
    if topic is not None and topic != expected:
        fail("TinyQuake Topic 与站点/设备/传感器身份不一致")


def ingest(db, payload, *, source, topic=None, connector_id=None, **_):
    validate(payload, source, topic)
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    identity = tuple(payload[k] for k in ("site_id", "device_id", "sensor_id", "boot_id", "seq"))
    with db.connection() as c:
        old = c.execute("SELECT * FROM tinyquake_results WHERE site_id=? AND device_id=? AND sensor_id=? AND boot_id=? AND seq=?", identity).fetchone()
        if old:
            if old["payload_json"] != raw or old["source"] != source:
                fail("TinyQuake 相同消息身份发生内容或来源冲突", 409)
            return {"id": old["id"], "status": "duplicate", "durable": True, "scope": "TEST_ONLY"}
        identifier = str(uuid4())
        c.execute("INSERT INTO tinyquake_results(id,site_id,device_id,sensor_id,boot_id,seq,source,input_source,received_at,payload_json,connector_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                  (identifier, *identity, source, payload["input_source"], utc_now(), raw, connector_id))
    return {"id": identifier, "status": "accepted", "durable": True, "scope": "TEST_ONLY"}


def project(row):
    result = dict(row)
    payload = json.loads(result.pop("payload_json"))
    age = max(0, (datetime.now(timezone.utc) - datetime.fromisoformat(result["received_at"].replace("Z", "+00:00"))).total_seconds())
    values = payload["probabilities"]
    result.update(payload=payload, scope="TEST_ONLY", age_seconds=round(age, 1), stale=age > 30,
                  prediction=CLASSES[max(range(3), key=lambda n: values[n])] if values is not None else None,
                  freshness_basis="arrival_only", scientifically_validated=False, risk_eligible=False)
    return result


def listing(db, *, site_id=None, device_id=None, sensor_id=None, source=None, limit=50, cursor=None):
    filters = [site_id, device_id, sensor_id, source]
    where, args = [], []
    for key, value in zip(("site_id", "device_id", "sensor_id", "source"), filters):
        if value is not None:
            where.append(f"{key}=?")
            args.append(value)
    if cursor is not None:
        try:
            if len(cursor) > 4096:
                raise ValueError
            stamp, identifier, saved = json.loads(base64.b64decode(cursor, altchars=b"-_", validate=True))
            if saved != filters or not isinstance(stamp, str) or not isinstance(identifier, str):
                raise ValueError
        except Exception:
            fail("无效或属于其他数据流的 TinyQuake 分页游标")
        where.append("(received_at<? OR (received_at=? AND id<?))")
        args.extend((stamp, stamp, identifier))
    with db.connection() as c:
        rows = c.execute("SELECT * FROM tinyquake_results" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY received_at DESC,id DESC LIMIT ?", (*args, limit+1)).fetchall()
    visible = rows[:limit]
    continuation = base64.urlsafe_b64encode(json.dumps([visible[-1]["received_at"], visible[-1]["id"], filters]).encode()).decode() if len(rows) > limit else None
    return {"items": [project(row) for row in visible], "next_cursor": continuation,
            "model_sha256": MODEL_SHA256, "classes": CLASSES, "scope": "TEST_ONLY"}


def streams(db):
    with db.connection() as c:
        rows = c.execute("SELECT * FROM (SELECT *,row_number() OVER(PARTITION BY site_id,device_id,sensor_id,source ORDER BY received_at DESC,id DESC) AS position FROM tinyquake_results) WHERE position=1 ORDER BY site_id,device_id,sensor_id,source").fetchall()
    return {"items": [project(row) for row in rows]}
