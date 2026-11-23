# MOCK_INTERFACE_PROTOCOL Review v0.2

日期：2026-10-03。仓库：`ict-2026`，分支：李青原。

本文件记录第二轮人工审查及修正后的定义核对，不是运行报告。人工审查完成依据为本轮团队提供的确认；当前文件内容已对照核查。

## 1. Review Scope

本轮审查范围：

- `docs/protocols/MOCK_INTERFACE_PROTOCOL_v0.1.md`：更新后的协议定义。
- `experiments/mock_interface/README.md`：测试清单、状态与执行边界。
- `experiments/mock_interface/cases/M03B_SINGLE_IMU_ERROR.json`
- `experiments/mock_interface/cases/M05_TIME_NOT_SYNCED.json`
- `experiments/mock_interface/cases/M06_REBOOT_IDENTITY.json`
- `experiments/mock_interface/cases/M07_RISK_NOT_CALIBRATED.json`
- `experiments/mock_interface/cases/M08_INVALID_SCHEMA.json`

M01_NORMAL、M02_MISSING_SENSOR、M03_SENSOR_ERROR、M04_DUPLICATE_MESSAGE 沿用 [Review v0.1](MOCK_INTERFACE_PROTOCOL_REVIEW_v0.1.md) 的历史审查结论，并保留此前已按人工意见完成的 M02 Missing Policy 措辞修正；本轮不重新修改这些用例，也不改写历史记录。

本轮写入前后对既有文件进行 SHA-256 对照，确认 M01～M08（含 M03B，共九个 JSON）、REVIEW_v0.1、Protocol、README、C++ 及其他既有项目文件均未修改。当前用例尚未被 Git 跟踪，因此不能只依赖 Git diff 判定其是否变化。仓库唯一新增文件为本 Review，`results/` 仍仅有 `.gitkeep`。

最高事实源仍为 `00_TEAM_SHARED_CONTRACT`；正式 Telemetry 仍为 `zhifang.telemetry.v2`，唯一身份仍为 `(device_id, boot_id, seq)`。本次不扩展正式字段，不生成 Producer、Validator、算法或执行结果。

## 2. Overall Conclusion

新增五个 Mock 用例定义已完成人工审查，本轮发现的语义问题已在此前按人工意见修正并完成内容核对：M03B 补充 G09，M05 明确预期语气，M06 补充 G08，M07 区分未标定与缺测策略，M08 明确结构校验优先顺序。

没有发现需要修改正式 C++ 或 v2 Schema 的新结论。G01～G09 全部保持开放，不新增 G10。定义审查完成不等于实现完成，也不等于三人联调完成。

全部用例仍属于 MOCK；本轮没有实际执行三人 Mock 联调，没有实际 PASS。文中的计数、拒绝处理与验收条件仅为预期，不能当作已发生的运行结果。

## 3. New Cases Review

### M03B_SINGLE_IMU_ERROR

- 单 IMU Error 与 dual IMU disagreement 区分正确：TOP Valid、TOE Error 不能被解释为两枚有效 IMU 的测量结果不一致。当前不新增 consensus 字段。
- TOE 快照中的非 optional 零初始化数组只是占位，不是有效零值观测，必须由 validity 门禁排除；payload 对应数值为 null、valid=false，采样时刻为 null。
- `interface_gaps=["G02","G07","G09"]`。G02 为三态到 bool 的信息损失；G07 为无效占位的映射/适配缺口；G09 为单 IMU 无效后剩余输入如何参与 Risk 的待定策略。
- Risk 策略未由 Mock 决定：不规定必须继续评分、必须停止评分或降低多少可信度，当前 Risk 三字段保持 null。G02/G07/G09 均未关闭。

### M05_TIME_NOT_SYNCED

- 按当前协议定义，`timestamp_ms=null` 与 `time_synced=false` 是合法的未同步时间表达，本身不应成为拒绝原因；其余来源、结构和身份检查通过后，预期允许进入后续流程。
- uptime_ms 为消息级启动后单调毫秒，不冒充 UTC；acquired_uptime_us 是各传感器自己的采样时刻，不等于消息时间，也不能证明各路同时采样。
- 不用电脑时间、服务器接收时间或 uptime 补造 UTC。G04 保持开放。
- Expected Behavior 与未来验收条件的措辞已明确；本轮未执行 Validator，不把预期允许进入流程写成实际通过。

### M06_REBOOT_IDENTITY

- 三元身份使用正确：`(NODE-01,1,1)` 与 `(NODE-01,2,1)` 因 boot_id 不同，不属于同一 identity。不能只用 device_id+seq 去重。
- `interface_gaps=["G06","G08"]`。G06 涉及人工 boot_id/seq 尚未被真实 IdentityAllocator、自动分配及跨启动唯一性证明；G08 涉及实际 duplicate/conflict 门禁与统计未实现。
- normal_processing_count=2、duplicate_count=0、conflict_count=0 均为 Expected Behavior，未产生实际统计。人工身份和时间值不代表真实设备已执行重启验证。
- G06/G08 保持开放；用例须在独立 Mock 去重上下文中执行，避免与其他用例的人工身份串扰。

### M07_RISK_NOT_CALIBRATED

- 双 IMU、三 Soil 原始输入均 Valid，没有缺测或无效输入；原始输入有效不能自动产生正式 Risk 结果。
- risk.sensor_score、risk.level、risk.reason_mask 均保持 null 正确。没有合法结果不等于数值 0，也不等于 NORMAL；sensor_degraded 维持既有默认 true。
- `interface_gaps=[]`，已删除测试外层的 risk_policy_status。这里 null 的直接原因是 Risk 尚未正式标定/没有合法运行结果。
- G09 是项目仍开放的缺测/无效输入策略问题，不是“Risk 未标定”的直接原因。本用例不新增 Gap，不增改正式 Telemetry 字段，也不替张鹏飞决定评分规则。

### M08_INVALID_SCHEMA

四个故意非法的负例分别覆盖：

1. schema 名称为 `zhifang.telemetry.v999`。
2. boot_id 为字符串 `abc`。
3. 缺少必须身份字段 seq。
4. soil.middle_raw 为字符串 `hello`。

middle_raw=null 是合法缺测，不能仅因 null 判为 INVALID_SCHEMA；原 M02 保留为合法对照。invalid_reason 与 expected_rejection 仅为测试外层记录，不是正式字段或冻结的生产错误码。

预期执行顺序为：先校验 source / Schema / 类型 / 必须身份字段，非法则直接按 expected_rejection 拒绝；只有通过基本结构校验后，才进入 sampling_snapshot 与 payload 映射一致性检查。第 4 条必须先暴露类型错误，不能让快照映射不一致遮蔽此负例的目标；快照不得用于修复非法 payload。

未来 Validator 应在正常 Feature/Risk 之前拒绝非法消息。当前 validator_status=NOT_IMPLEMENTED、execution_status=BLOCKED，G08 保持开放；rejected_message_count=4 和 normal_processing_count=0 仍只是预期，未记录实际拒绝结果。

## 4. Open Interface Gaps

本表只汇总当前开放项，不重新设计解决方案。

| 编号 | 当前开放事项 |
|---|---|
| G01 | Mock 来源隔离；source=MOCK 仅属测试外层，裸 payload 不能据此辨识 Mock。 |
| G02 | IMU Valid/Unavailable/Error 三态到正式 bool valid 的信息损失。 |
| G03 | Soil 逐路 validity 无法由正式 raw integer/null 无损表达。 |
| G04 | 正式 Telemetry 缺少逐路采样时间；消息 uptime 不能替代采样时刻。 |
| G05 | Diagnostic Contract 尚未冻结。 |
| G06 | Serializer / IdentityAllocator 未实现，自动序号和持久跨启动身份未获实现证明。 |
| G07 | Invalid IMU 占位值到正式无效值的映射/适配尚未落实。 |
| G08 | 完整 Validator、去重、冲突留证/统计及下游接线未实现。 |
| G09 | Missing Policy / invalid-input Risk policy 待张鹏飞定义，包括 minimum valid inputs、degraded behavior、score 是否继续计算及 reason_mask。 |

G01～G09 全部保持开放。INTERFACE_GAP 不自动授权修改正式 v2；测试外层元数据与静态预期也不能自行成为正式接口。不新增 G10。

## 5. Status Matrix

状态针对当前本地工作区及本次三人 Mock 链路。CONFIRMED 仅表示定义审查事实已确认；MOCK 表示人工模拟数据，两者均不等于实际运行验收。

| 项目 | 当前状态 | 说明 |
|---|---|---|
| Mock Case Definitions | CONFIRMED (definition review only) / MOCK | 九例定义已完成人工审查；本 Review 新增覆盖五例。 |
| Producer | NOT_IMPLEMENTED | 完整 Mock 输入生产链路尚未落地。 |
| Serializer | NOT_IMPLEMENTED | 静态 JSON 不是实际序列化实现。 |
| IdentityAllocator | NOT_IMPLEMENTED | 人工 boot_id/seq 不是自动或持久分配证据。 |
| Executable Validator | NOT_IMPLEMENTED | 当前未完成本链路的可执行校验器接入。 |
| Feature/Risk Integration | NOT_IMPLEMENTED | 未执行三人 Feature/Risk 接收处理联调。 |
| Edge Intake Integration | NOT_IMPLEMENTED | 未执行本链路接入联调。 |
| Diagnostic Contract | NOT_IMPLEMENTED | 正式诊断契约尚未冻结。 |
| Risk Missing Policy | WAITING_RISK_POLICY | 张鹏飞负责缺测/无效输入策略；不作为 M07 未标定的直接原因。 |
| Real Hardware Data | TBD_HARDWARE_TEST | 本测试集不提供真实硬件采集证据。 |
| Three-Person Mock Integration PASS | NONE | 没有实际三人 Mock 联调结果。 |

## 6. Next Step

下一阶段不再继续扩展静态 Mock 设计，转入第一次三人 Mock 联调准备与实际执行。本轮仅收尾审查记录，不启动实现或执行。

| 负责人 | 下一阶段职责 |
|---|---|
| 李青原 | Mock Producer、Telemetry 输入准备、identity 与 Storage 边界。 |
| 张鹏飞 | Feature/Risk 接收，以及缺测/无效输入策略。 |
| 何宇轩 | Schema Validator 与 Edge Intake。 |

实际联调必须保留输入文件及 hash、实现版本/commit（未提交内容须记录可复现的版本依据）、操作步骤、预期结果、实际结果、PASS / FAIL / BLOCKED 判定，以及失败或阻塞证据。上述状态只能由真实执行证据支持，不能抄录 Expected Behavior 当实际结果。

只有实际执行后，才在 `experiments/mock_interface/results/` 写入实际记录。尚未实现的环节如实记录阻塞，不能算通过；Mock 联调结论也不替代真实硬件验证。
