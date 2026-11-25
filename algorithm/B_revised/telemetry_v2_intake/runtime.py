"""参数化因果 Feature → Contribution → Risk 参考内核。

原始高频观测从明确版本的内部批次输入，不把低频 Telemetry 快照当成 IMU 波形。
TEST_ONLY 能执行全链路；真实配置和元数据未批准时必须阻塞。
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from itertools import groupby
from collections.abc import Mapping

from candidate_features import reference, risk_math
from candidate_features.causal_window import CausalObservationBuffer
from telemetry_v2_intake.config import contribution, finite, integer, text, validate_config

IMUS = ("top", "toe")
PROBES = ("top", "middle", "toe")
NULL_RISK = {"sensor_score": None, "level": None, "reason_mask": None}


def fingerprint(value):
    return hashlib.sha256(json.dumps(plain(value), sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def plain(value):
    """支持上游只读 Mapping/tuple；深拷贝到内核，不改调用方对象。"""
    if isinstance(value, Mapping):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(v) for v in value]
    return copy.deepcopy(value)


class FeatureRiskRuntime:
    """每个节点独立状态；一次 evaluate 事务失败不污染历史。调用方需串行化。

    不管理 MQTT 回执、持久化去重或现场报警锁存，这些由 A/C 实现。
    """

    def __init__(self, config: dict):
        self._config = validate_config(config)
        self._states = {}

    @property
    def config(self):
        return copy.deepcopy(self._config)

    def reload_config(self, config: dict):
        candidate = validate_config(config)  # 原子校验；失败仍保留最后有效配置/历史
        if candidate["config_hash"] != self._config["config_hash"]:
            self._config = candidate
            self._states.clear()  # 不跨配置/校准版本拼接窗口

    def _buffer(self, name):
        w = self._config["windows"][name]
        return CausalObservationBuffer(lookback_ms=w["lookback_ms"],
                                       max_gap_ms=w["max_gap_ms"], max_age_ms=w["max_age_ms"])

    def _new_state(self, segment):
        return {"segment": segment, "last_seq": None, "last_end": None,
                "seen_boots": {segment[0]},
                "last_hash": None, "last_result": None,
                "imu": {p: {"last": None, "gravity": None, "start": None,
                             "tilt": self._buffer("tilt"),
                             "energy": self._buffer("vibration")} for p in IMUS},
                "soil": {p: None for p in PROBES}, "soil_tuple": None,
                "soil_growth": self._buffer("soil_growth")}

    def _validate_batch(self, payload, context):
        if not isinstance(context, Mapping) or not isinstance(context.get("runtime_input"), Mapping):
            raise ValueError("缺 B.observation_batch.v1 原始采样批次；快照不能代替波形")
        b = plain(context["runtime_input"])
        if b.get("schema") != "B.observation_batch.v1":
            raise ValueError("内部采样批次版本不匹配")
        expected_source = "TEST_ONLY" if self._config["mode"] == "TEST_ONLY" else "REAL"
        if b.get("source") != expected_source:
            raise ValueError("采样来源与配置模式不一致")
        for key in ("run_id", "frame_id", "calibration_version"):
            text(b.get(key), key)
        if b["run_id"] != payload["experiment"]["run_id"]:
            raise ValueError("run_id 与 Telemetry 不一致")
        if {k: payload[k] for k in ("site_id", "device_id")} != self._config["device_identity"]:
            raise ValueError("当前标定配置不属于该节点")
        for key in ("frame_id", "calibration_version", "odr_hz", "sensor_ids"):
            if b[key] != self._config[key]:
                raise ValueError(f"{key} 与当前配置不一致；须切换配置并重置窗口")
        if b.get("identity") != {k: payload[k] for k in ("site_id", "device_id", "boot_id")}:
            raise ValueError("采样批次不属于当前节点/boot")
        end = integer(payload["uptime_ms"], "uptime_ms")
        for group, positions in (("imu", IMUS), ("soil", PROBES)):
            if not isinstance(b.get(group), dict) or set(b[group]) != set(positions):
                raise ValueError(f"{group}: 路数或位置不匹配")
            for p in positions:
                rows = b[group][p]
                if not isinstance(rows, list):
                    raise ValueError("每路观测必须是有序列表")
                previous = -1
                for row in rows:
                    t = integer(row["uptime_ms"], "acquired_uptime_ms")
                    if t <= previous or t > end:
                        raise ValueError("批次时间重复/倒退/含未来观测")
                    previous = t
                    if type(row.get("valid")) is not bool:
                        raise ValueError("观测有效性必须显式为 bool")
                    if group == "imu":
                        vector = row.get("acceleration_mps2")
                        if row["valid"]:
                            if not isinstance(vector, list) or len(vector) != 3:
                                raise ValueError("有效 IMU 需要完整三轴加速度")
                            for v in vector:
                                finite(v, "acceleration_mps2")
                    else:
                        raw = row.get("raw")
                        if raw is not None and (type(raw) is not int or not -32768 <= raw <= 32767):
                            raise ValueError("Soil raw 应为 ADS1115 有符号原始码或 null")
                        if row["valid"] and raw is None:
                            raise ValueError("有效 Soil 不能缺少 raw")
        return b

    def evaluate(self, payload, *, context=None):
        if payload.get("schema") != "zhifang.telemetry.v2":
            raise ValueError("必须先通过上游 Telemetry v2 Validator")
        result = {"status": "REAL_CODE_REACHED",
                  "identity": {k: payload[k] for k in ("site_id", "device_id", "boot_id", "seq")},
                  "mode": self._config["mode"], "config_hash": self._config["config_hash"],
                  "feature_version": self._config["feature_version"],
                  "calibration_version": self._config["calibration_version"],
                  "input_risk": plain(payload["risk"]),
                  "risk": dict(NULL_RISK), "risk_execution": "RISK_EXECUTION_BLOCKED",
                  "feature_status": "BLOCKED", "blocked_reason": [],
                  "context_used_for_computation": True}
        try:
            batch = self._validate_batch(payload, context)
            device = (payload["site_id"], payload["device_id"])
            segment = (str(payload["boot_id"]), batch["run_id"], batch["frame_id"],
                       batch["calibration_version"], self._config["config_hash"])
            seq = integer(payload["seq"], "seq")
            end = payload["uptime_ms"]
            state = copy.deepcopy(self._states.get(device))
            if state is not None and state["segment"][0] == str(payload["boot_id"]):
                if seq < state["last_seq"] or end < state["last_end"]:
                    raise ValueError("同一 boot 的 seq/uptime 倒退；不可借 run 变更绕过")
                if state["segment"] != segment and seq == state["last_seq"]:
                    raise ValueError("同一 boot/seq 不能用于另一分段")
            changed = state is None or state["segment"] != segment
            if changed:
                seen = set() if state is None else state["seen_boots"]
                if state is not None and state["segment"][0] != segment[0] and segment[0] in seen:
                    raise ValueError("已结束 boot 的补传不能覆盖当前在线窗口")
                state = self._new_state(segment)
                state["seen_boots"].update(seen)
            message_hash = fingerprint({"payload": payload, "batch": batch})
            if state["last_seq"] == seq:
                if state["last_hash"] != message_hash:
                    raise ValueError("同一 device/boot/seq 的输入冲突")
                receipt = copy.deepcopy(state["last_result"])
                receipt["processing"] = "DUPLICATE_NO_RECOMPUTE"
                return receipt
            if state["last_seq"] is not None and (seq < state["last_seq"] or end < state["last_end"]):
                raise ValueError("乱序消息需离线按实际采样时序回放；不能回算当前在线状态")
            result["processing"] = "SEGMENT_RESET" if changed else "NEW_MESSAGE"
            self._ingest(state, batch)
            self._check_snapshot(state, payload)
            features, details, reasons = self._features(state, end)
            result.update(features=features, feature_details=details)
            values = {"tilt": max((features["imu"][p]["tilt_deg"] for p in IMUS), default=None),
                      "vibration": None, "moisture": features["soil"]["avg_pct"],
                      "growth": features["soil"]["growth_pct_min"]} if not reasons else {}
            if not reasons:
                values["vibration"] = max(features["imu"][p]["vibration_rms"] for p in IMUS)
                values["growth"] = max(0.0, values["growth"])  # 明确只将上升送入危险贡献曲线
                contributions = {name: contribution(value, self._config["curves"][name])
                                 for name, value in values.items()}
                tilts = [features["imu"][p]["tilt_deg"] for p in IMUS]
                cc = self._config["consensus"]
                consensus = (min(tilts) >= cc["tilt_threshold_deg"] and
                             abs(tilts[0] - tilts[1]) <= cc["max_tilt_difference_deg"])
                bonus = cc["bonus"] if consensus else 0
                score = risk_math.sensor_score(contributions, bonus)
                semantic = [name.upper() + "_CONTRIBUTION" for name, value in contributions.items() if value > 0]
                if bonus:
                    semantic.append("DUAL_IMU_CONSENSUS")
                risk = {"sensor_score": score, "level": risk_math.risk_level(score), "reason_mask": None}
                if self._config["mode"] == "CALIBRATED":
                    risk["reason_mask"] = sum(1 << self._config["reason_bits"][r] for r in semantic)
                result.update(feature_status="COMPLETE", contributions=contributions,
                              contribution_inputs=values, consensus_bonus=bonus, reasons=semantic,
                              risk=risk, risk_execution=("TEST_ONLY_RISK_COMPUTED" if
                              self._config["mode"] == "TEST_ONLY" else "CALIBRATED_RISK_COMPUTED"))
            else:
                result.update(feature_status="PARTIAL", blocked_reason=reasons,
                              contributions={name: None for name in risk_math.WEIGHTS})
            state.update(last_seq=seq, last_end=end, last_hash=message_hash,
                         last_result=copy.deepcopy(result))
            self._states[device] = state  # 前面任一步失败均不提交状态
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            result.update(feature_status="BLOCKED", risk=dict(NULL_RISK),
                          risk_execution="RISK_EXECUTION_BLOCKED", processing="INPUT_REJECTED_NO_STATE_CHANGE",
                          blocked_reason=[str(exc)])
        return result

    @staticmethod
    def _new_observation(last, row):
        if last is None or row["uptime_ms"] > last["uptime_ms"]:
            return True
        if row["uptime_ms"] == last["uptime_ms"] and row == last:
            return False  # 因果保持的旧观测不能当成新样本
        raise ValueError("观测时间倒退或同一采样时刻内容冲突")

    def _ingest(self, state, batch):
        c = self._config
        for p in IMUS:
            channel = state["imu"][p]
            for row in batch["imu"][p]:
                if not self._new_observation(channel["last"], row):
                    continue
                t = row["uptime_ms"]
                gap_limit = min(c["windows"][n]["max_gap_ms"] for n in ("tilt", "vibration"))
                reset = channel["last"] is None or t - channel["last"]["uptime_ms"] > gap_limit
                if reset or not row["valid"] or channel["gravity"] is None:
                    channel.update(gravity=None, start=None, tilt=self._buffer("tilt"),
                                   energy=self._buffer("vibration"))
                tilt = energy = None
                if row["valid"]:
                    raw = tuple(row["acceleration_mps2"])
                    if channel["gravity"] is None:
                        channel.update(gravity=raw, start=t)
                    else:
                        dt = t - channel["last"]["uptime_ms"]
                        alpha = -math.expm1(-dt / c["imu"]["gravity_tau_ms"])
                        channel["gravity"] = tuple(g + alpha * (a - g)
                                                   for a, g in zip(raw, channel["gravity"]))
                    if t - channel["start"] >= c["imu"]["warmup_ms"]:
                        tilt = reference.gravity_tilt_change_deg(
                            channel["gravity"], c["imu"]["baseline_gravity_mps2"][p])
                        energy = sum((a - g) ** 2 for a, g in zip(raw, channel["gravity"]))
                channel["tilt"].add(segment_key=state["segment"], uptime_ms=t,
                                    value=tilt, valid=tilt is not None)
                channel["energy"].add(segment_key=state["segment"], uptime_ms=t,
                                      value=energy, valid=energy is not None)
                channel["last"] = row
        # 合并真实 Soil 更新事件，禁止把保持值重新写入生长率窗口。
        events = sorted((r["uptime_ms"], p, r) for p in PROBES for r in batch["soil"][p])
        for t, grouped in groupby(events, key=lambda event: event[0]):
            updated = False
            for _, p, row in grouped:
                if self._new_observation(state["soil"][p], row):
                    state["soil"][p] = row
                    updated = True
            if not updated:
                continue
            mean, _, diagnostic = self._soil(state, t)
            stamp = tuple(state["soil"][p]["uptime_ms"] if state["soil"][p] else None for p in PROBES)
            # 三根探针均需取得新物理观测，避免逐根扫描产生伪增长率。
            # 扫描中混合的新旧时刻不清空窗口；明确故障/越界才立即重建。
            previous = state["soil_tuple"]
            fault = any(d["status"] in ("INVALID_OBSERVATION", "CALIBRATION_RANGE_EXCEEDED")
                        for d in diagnostic.values())
            if fault:
                state["soil_growth"] = self._buffer("soil_growth")
                state["soil_tuple"] = None
            elif mean is not None and (previous is None or all(a != b for a, b in zip(stamp, previous))):
                state["soil_growth"].add(segment_key=state["segment"], uptime_ms=t,
                                         value=mean, valid=True)
                state["soil_tuple"] = stamp

    @staticmethod
    def _check_snapshot(state, payload):
        """原始最新观测必须对应消息快照；不信任未经核对的 sidecar。"""
        for imu in payload["imu"]:
            row = state["imu"][imu["id"]]["last"]
            if row is None or row["valid"] != imu["valid"]:
                raise ValueError("IMU 快照与原始采样有效性不一致")
            if row["valid"] and row["acceleration_mps2"] != [imu[k] for k in ("ax", "ay", "az")]:
                raise ValueError("IMU 快照与原始三轴采样不一致")
        for p in PROBES:
            row = state["soil"][p]
            if row is None or row["raw"] != payload["soil"][f"{p}_raw"]:
                raise ValueError("Soil 快照与原始采样不一致")

    def _soil(self, state, end):
        values, diagnostic, times = {}, {}, []
        w = self._config["windows"]["soil_growth"]
        for p in PROBES:
            row = state["soil"][p]
            value, reason = None, "MISSING"
            if row is not None:
                times.append(row["uptime_ms"])
                if not row["valid"]:
                    reason = "INVALID_OBSERVATION"
                elif not 0 <= end - row["uptime_ms"] <= w["max_age_ms"]:
                    reason = "STALE_OR_FUTURE"
                else:
                    cal = self._config["soil"]["calibration"][p]
                    value = 100 * reference.relative_wetness_index(row["raw"], cal["dry_raw"], cal["wet_raw"])
                    reason = "VALID" if 0 <= value <= 100 else "CALIBRATION_RANGE_EXCEEDED"
            diagnostic[p] = {"unclipped_pct": value, "status": reason}
            values[p] = value if reason == "VALID" else None
        aligned = len(times) == 3 and max(times) - min(times) <= self._config["soil"]["alignment_ms"]
        mean = sum(values.values()) / 3 if aligned and all(v is not None for v in values.values()) else None
        return mean, values, diagnostic

    def _window(self, buffer, name, end):
        w = self._config["windows"][name]
        view = buffer.window(end_uptime_ms=end, min_valid_samples=w["min_samples"])
        status = view.status
        if status == "STRUCTURE_VALID_ONLY" and view.samples[-1][0] - view.samples[0][0] < w["min_span_ms"]:
            status = "INSUFFICIENT_TIME_COVERAGE"
        return view.samples if status == "STRUCTURE_VALID_ONLY" else None, {
            "status": status, "valid_count": len(view.samples),
            "start_uptime_ms": view.start_uptime_ms, "end_uptime_ms": end}

    def _features(self, state, end):
        features, details, reasons = {"imu": {}, "soil": {}}, {"imu": {}, "soil": {}}, []
        latest_times = []
        for p in IMUS:
            channel = state["imu"][p]
            ts, td = self._window(channel["tilt"], "tilt", end)
            es, ed = self._window(channel["energy"], "vibration", end)
            latest = channel["last"]
            latest_times.append(latest["uptime_ms"])
            tilt = ts[-1][1] if ts else None
            rate = reference.causal_slope_per_second(ts) if ts else None
            rms = math.sqrt(sum(v for _, v in es) / len(es)) if es else None
            if not latest["valid"]:
                tilt = rate = rms = None
            features["imu"][p] = {"tilt_deg": tilt, "tilt_rate_dps": rate, "vibration_rms": rms}
            details["imu"][p] = {"tilt_window": td, "vibration_window": ed,
                                  "latest_valid": latest["valid"]}
            if any(v is None for v in features["imu"][p].values()):
                reasons.append(f"IMU_{p.upper()}_INVALID_STALE_OR_WINDOW_NOT_READY")
        if max(latest_times) - min(latest_times) > self._config["imu"]["alignment_ms"]:
            reasons.append("DUAL_IMU_NOT_ALIGNED")
        avg, values, sd = self._soil(state, end)
        samples, wd = self._window(state["soil_growth"], "soil_growth", end)
        growth = reference.causal_slope_per_second(samples) * 60 if samples and avg is not None else None
        features["soil"] = {**{f"{p}_pct": v for p, v in values.items()},
                            "avg_pct": avg, "growth_pct_min": growth}
        features["dual_imu_tilt_difference_deg"] = reference.dual_imu_tilt_difference_deg(
            features["imu"]["top"]["tilt_deg"], features["imu"]["toe"]["tilt_deg"])
        details["soil"] = {"probes": sd, "growth_window": wd}
        if avg is None or growth is None:
            reasons.append("SOIL_INVALID_STALE_UNALIGNED_OR_WINDOW_NOT_READY")
        return features, details, reasons
