# B 维护的 Telemetry v2 最小算法入口

入口：`telemetry_v2_intake.evaluate_telemetry_v2(payload, *, context=None, runtime=None)`，源文件 `entry.py`。在 `algorithm/B_revised` 加入 Python 导入路径后使用；例如在仓库根目录执行 `python algorithm/B_revised/telemetry_v2_intake/verify_a_mock.py`。返回值是**算法接收审计结果**，不是新的 Telemetry 消息，也不改写原 payload。下面的最小入口说明适用于 `runtime=None`。

调用顺序必须为 `上游 v2 Validator ACCEPT → 本入口`。M08 四条非法输入由上游拒绝，本入口**零调用**；不能调用后再用 B 的返回值冒充 Schema 校验。本模块只断言 schema 版本前置条件，没有复制 A/C 的 Validator。A 的 `sampling_snapshot` 只能放在 `context` 供调用方留存 TEST_ONLY 证据，本入口不拿它补字段、不推断 null 是 Error、I2C 超时还是 Unavailable。

当前入口把 `device_id/boot_id/seq`、时间、两枚 IMU、三路 Soil、system、experiment 显式投影；逐探针真实调用 `candidate_features.reference.relative_wetness_index(raw, None, None)`，因为 B 没有干湿标定；双 IMU 调用 `dual_imu_tilt_difference_deg`，但无对齐/有效倾角时结果仍为 null。`function_calls` 列出每一次真实调用。若未来输入有 tilt_deg 数值，差值仍只是候选数学值，未核定对齐前不能用于正式评分。

输出的 `feature_status=BLOCKED/PARTIAL` 指候选特征可计算情况；`risk_execution=RISK_EXECUTION_BLOCKED` 表示本轮没有合法正式 Risk 执行。`risk` 是 payload 原三字段的副本，绝不填 0、NORMAL 或 reason_mask。`blocked_reason` 明确列出标定、滤波/基线/窗口/对齐、贡献映射、Missing Policy 与 reason_mask 缺口。状态 `REAL_CODE_REACHED` 只表示 B 的候选函数真的被调用，不表示地灾预测能力或三人联调 PASS。

只运行本轮相关验证：

```powershell
python -m unittest discover -s algorithm/B_revised/telemetry_v2_intake -t algorithm/B_revised -p 'test_*.py' -v
python algorithm/B_revised/telemetry_v2_intake/verify_a_mock.py
```

第二条只读使用本地 `origin/李青原` 的 M01/M02/M07/M08 fixture 和 TEST_ONLY Validator；先 `git fetch origin 李青原`。它不会复制、修改或提交 A 的 Runner。真实三人联调仍由 A 更新 Adapter，C 的 Edge Intake 单独验证。

## 2026-10-06 可选计算内核

默认入口和 A 已固定 commit 的联调行为保持兼容。新增 `runtime=` 注入参数，显式加载配置后才消费
`context.runtime_input` 的原始高频批次。运行 `demo_runtime.py` 可观察 TEST_ONLY 的正常、异常、缺测结果。
见 [计算链路与 A/B/C 交接说明](RUNTIME_HANDOFF.md)。正式配置模板 `RUNTIME_CONFIG_DRAFT.json` 不能加载。
