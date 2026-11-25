"""已验证 Telemetry v2 的算法接收边界，不充当 Schema Validator。

默认入口映射现有 v2 并调用真实候选函数，保留未标定 Risk。
显式传入 runtime 后才消费 B.observation_batch.v1 内部采样批次计算；
这不是新增 Telemetry 字段，已有 sampling_snapshot 不会自动启用评分。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from candidate_features import reference


def evaluate_telemetry_v2(
    payload: Mapping[str, Any], *, context: Mapping[str, Any] | None = None, runtime=None
) -> dict[str, Any]:
    """消费**上游已通过 v2 校验**的单条消息，返回审计结果而非改写消息。

    runtime 为可选的 FeatureRiskRuntime。省略时保留 A 已联调的默认行为。

    M08 等非法输入必须由上游 Validator 在调用本函数前拒绝。这里只做版本
    前置条件断言，不另建一套 Schema 校验器。直接绕过 Validator 调用的结果
    不构成正式接入证据。
    """
    if payload.get("schema") != "zhifang.telemetry.v2":
        raise ValueError("必须先由上游 Validator 接受 zhifang.telemetry.v2")

    # 显式注入已加载配置的有状态内核。默认路径不引入新依赖，保持 A 固定源码联调兼容。
    if runtime is not None:
        return runtime.evaluate(payload, context=context)

    top, toe = payload["imu"]
    soil = payload["soil"]
    identity = {key: payload[key] for key in ("site_id", "device_id", "boot_id", "seq")}
    observations = {
        "time": {key: payload[key] for key in ("timestamp_ms", "uptime_ms", "time_synced")},
        "imu": {
            position: {key: imu[key] for key in
                       ("valid", "ax", "ay", "az", "gx", "gy", "gz",
                        "tilt_deg", "tilt_rate_dps", "vibration_rms")}
            for position, imu in (("top", top), ("toe", toe))
        },
        "soil": {key: soil[key] for key in
                 ("top_raw", "middle_raw", "toe_raw", "top_pct", "middle_pct",
                  "toe_pct", "avg_pct", "growth_pct_min")},
        "system": dict(payload["system"]),
        "experiment": dict(payload["experiment"]),
    }

    features: dict[str, Any] = {"soil_relative_index": {}}
    feature_details: dict[str, Any] = {"soil_relative_index": {}}
    function_calls: list[dict[str, Any]] = []
    for position in ("top", "middle", "toe"):
        raw = soil[f"{position}_raw"]  # None 与整数 0 均原样送入；不从 sidecar 代填。
        value = reference.relative_wetness_index(raw, None, None)
        function_calls.append({"function": "candidate_features.reference.relative_wetness_index",
                               "channel": position, "returned": value})
        features["soil_relative_index"][position] = value
        feature_details["soil_relative_index"][position] = (
            "MISSING_OBSERVATION_CAUSE_UNKNOWN" if raw is None
            else "RAW_PRESENT_VALIDITY_UNRESOLVED_AND_CALIBRATION_MISSING"
        )

    # 已有 tilt_deg 是 v2 派生字段；无双 IMU 时间对齐证据时只给候选数学值。
    top_tilt = top["tilt_deg"] if top["valid"] else None
    toe_tilt = toe["tilt_deg"] if toe["valid"] else None
    difference = reference.dual_imu_tilt_difference_deg(top_tilt, toe_tilt)
    function_calls.append({"function": "candidate_features.reference.dual_imu_tilt_difference_deg",
                           "channel": "top_toe", "returned": difference})
    features["dual_imu_tilt_difference_deg"] = difference
    feature_details["dual_imu_tilt_difference_deg"] = (
        "MISSING_OR_INVALID_TILT" if difference is None else "CANDIDATE_ONLY_ALIGNMENT_UNVERIFIED"
    )

    return {
        "status": "REAL_CODE_REACHED",
        "identity": identity,
        "observations": observations,
        "feature_status": "PARTIAL" if difference is not None else "BLOCKED",
        "features": features,
        "feature_details": feature_details,
        "called_functions": [call["function"] for call in function_calls],
        "function_calls": function_calls,
        "risk_execution": "RISK_EXECUTION_BLOCKED",
        "risk": dict(payload["risk"]),
        "blocked_reason": [
            "NO_REVIEWED_PER_PROBE_CALIBRATION",
            "NO_VALIDATED_FILTER_BASELINE_WINDOW_AND_ALIGNMENT",
            "NO_CALIBRATED_CONTRIBUTION_MAPPING",
            "NO_FORMAL_MISSING_POLICY_OR_REASON_MASK",
        ],
        "context_used_for_computation": False,
    }
