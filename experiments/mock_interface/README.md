# 三人 Mock 接口测试样例

日期：2026-10-03。对应 [MOCK_INTERFACE_PROTOCOL_v0.1](../../docs/protocols/MOCK_INTERFACE_PROTOCOL_v0.1.md)。当前只定义协议与静态样例，不生成 Producer，不执行三方 Pipeline。

用途：验证李青原 NODE-01 → 张鹏飞 Feature/Risk → 何宇轩 Schema Validator/Edge Intake 的接口一致性。

流程：Mock Producer → Schema Validation / 来源检查 / 身份去重门禁 → Feature/Risk Processing → Result Recording。

上述是未来流程，不是已运行服务；重复输入不能先进入 Risk。本目录独立于 docs/experiments 的真实实验/run 文档，只放 MOCK 样例，不新增 Real 实验或训练集。

```text
experiments/mock_interface/
├── README.md
├── cases/
│   ├── M01_NORMAL.json
│   ├── M02_MISSING_SENSOR.json
│   ├── M03_SENSOR_ERROR.json
│   ├── M03B_SINGLE_IMU_ERROR.json
│   ├── M04_DUPLICATE_MESSAGE.json
│   ├── M05_TIME_NOT_SYNCED.json
│   ├── M06_REBOOT_IDENTITY.json
│   ├── M07_RISK_NOT_CALIBRATED.json
│   └── M08_INVALID_SCHEMA.json
└── results/
    └── .gitkeep
```

| 文件 | 作用 |
|---|---|
| M01_NORMAL.json | 双 IMU/三 Soil 有效 Mock 值；NORMAL 不是风险等级 |
| M02_MISSING_SENSOR.json | middle_raw=null，附带快照 validity=Unavailable |
| M03_SENSOR_ERROR.json | middle_raw=null，附带快照 validity=Error；I2C_TIMEOUT 仅场景说明 |
| M04_DUPLICATE_MESSAGE.json | 基准、相同身份/相同 payload 的重复、相同身份/不同 payload 的冲突 |
| M03B_SINGLE_IMU_ERROR.json | TOP Valid、TOE Error；无效数组仅占位，payload 数值 null/valid=false；非双路 disagreement，保留 G02/G07/G09；剩余输入评分策略未定 |
| M05_TIME_NOT_SYNCED.json | 按协议定义，UTC 未同步本身预期不应成为拒绝原因；区分消息时间和逐路采样时间，保留 G04 |
| M06_REBOOT_IDENTITY.json | 两个 boot 相同 seq 属于不同身份；人工序号不证明分配器实现，去重/冲突统计也未实现，保留 G06/G08 |
| M07_RISK_NOT_CALIBRATED.json | 原始值全 Valid，但 Risk 未正式标定/无合法结果，保持 Risk 全 null、sensor_degraded=true；无直接关联 Gap，G09 不是其 null 原因 |
| M08_INVALID_SCHEMA.json | 四种格式负例：错误 schema、boot_id 类型错误、缺少 seq、middle_raw 类型错误；预期拒绝，保留 G08 |
| results/.gitkeep | 保留空目录，不是测试结果 |

每个文件和每条 message 都有 source=MOCK。**不是现场/真实硬件采集，不是训练数据，不是实验结论，也不是 Synthetic 物理仿真输出。** 不向真实设备入口发布，不混入 Real 目录。

purpose/scenario/expected_behavior/pass_criteria 仅是测试说明，计数是期望而非实际统计。正常 messages[].payload 保持 v2 字段；M08 则故意破坏既有字段值/类型或缺少 seq，未增加正式字段。invalid_reason/expected_rejection 仅为 M08 测试外层说明，INVALID_SCHEMA 不冻结生产错误码。sampling_snapshot 按 sampling.hpp 成员名作离线对照。拆分 message 必须保留 source；只取 payload 会丢失 Mock 来源。

本轮 UTC、Feature、百分比、Risk score/level/reason_mask 均空。System 沿用当前结构未就绪默认值；M01 原始输入 Valid 不意味着整机已标定、可评分或已连接。

保留协议中全部 INTERFACE_GAP：来源、三态 validity、逐样本时间、错误码、serializer/持久身份、去重/冲突记录、下游 adapter 均不能凭测试格式成为已实现正式接口。不修改 C++，不新增核心 schema/LoRa 帧。

- **CONFIRMED**：已核对现有结构成员、枚举、单位和既有 v2 映射依据。
- **MOCK**：样例数字、身份、时间轴、有效性与错误场景。
- **NOT_IMPLEMENTED**：本次没有 Producer、执行器、三方 adapter、去重/冲突持久化或实际联调结果。
- **TBD_HARDWARE_TEST**：ICM、ADS、Soil、SD、LoRa/MQTT 真实接入与硬件能力。

下一步先由三方评审 INTERFACE_GAP 和来源传递，再接入执行器。实际执行后才在 results 记录输入 hash、版本、操作、预期/实际与失败/阻塞/通过证据。JSON 可解析不等于接口联调 PASS。

原 M01～M04 的历史审查结论见 [MOCK_INTERFACE_PROTOCOL_REVIEW_v0.1](../../docs/protocols/MOCK_INTERFACE_PROTOCOL_REVIEW_v0.1.md)。本轮 M01～M04 四个 JSON 保持原文（含此前已完成的 M02 Missing Policy 措辞修正），历史 Review 不代表新增五例已完成人工会签；静态字段/差异核对不代表联调执行，Real End-to-End PASS 为 NONE。

Producer 边界：Driver → SamplingTask → SensorSnapshot，由 RiskTask、StorageTask、Telemetry Producer 消费一致观测快照；Producer 再构造 TelemetryDraft → Serializer → MQTT。Producer 不直接读 ICM/ADS1115/SEN0193/I2C，不重新争抢 I2C Mutex 或等待 ADS 转换。该流程是职责约束，尚非已实现链路；一致快照不等于同时采样。

Validity 中 null 不自动等于 Error。Unavailable 表示未获得有效当前观测，Error 表示采集/设备/通信错误导致当前值不可用。正式 payload 仍不增加 Soil validity 或 error_code；I2C_TIMEOUT 本身不能区分 ADS1115、IMU_TOP、IMU_TOE，Diagnostic Contract 保持 INTERFACE_GAP / NOT_IMPLEMENTED。

G09：缺测/无效输入后的 Missing Policy、minimum valid inputs、degraded 行为、score 是否继续计算及 reason_mask 规则由张鹏飞定义，当前 INTERFACE_GAP / WAITING_RISK_POLICY。本轮 Risk 全 null，不补零或伪造 NORMAL，也不替未来策略作决定。同身份不同 payload 必须保留首次与冲突证据，不能当普通 duplicate、覆盖或静默选择一份，后续由 Edge/Storage/Diagnostic 策略处理。

本次测试清单共九例：M01 NORMAL、M02 MISSING_SENSOR、M03 SENSOR_ERROR、M03B SINGLE_IMU_ERROR、M04 DUPLICATE_MESSAGE、M05 TIME_NOT_SYNCED、M06 REBOOT_IDENTITY、M07 RISK_NOT_CALIBRATED、M08 INVALID_SCHEMA。全部属于 **MOCK TEST DEFINITION**，不是 **REAL HARDWARE DATA**，不是 **END-TO-END PASS**。

M03B 的无效 IMU 数组是与 C++ 非 optional 成员对应的占位，绝非真实零值观测；单路 Error 不等于双路测量不一致，不新增 consensus 字段。M06 必须隔离其他用例的去重上下文，身份仍仅为 (device_id, boot_id, seq)。M08 先做 source / Schema / 类型 / 必须身份字段校验，非法直接按 expected_rejection 拒绝；只有基本结构通过后才检查 sampling_snapshot 与 payload 映射一致性。第 4 条 hello 应先暴露类型错误，不能被映射不一致遮蔽，快照不得修复非法 payload。M02 的合法 null 不属于格式错误。所有计数、拒绝和 PASS Criteria 都是未来预期。

G01～G09 全部开放。Producer/Serializer/IdentityAllocator、完整 Validator 与下游接入为 NOT_IMPLEMENTED；M08 执行受此阻塞（BLOCKED），本轮未执行。张鹏飞正式策略为 WAITING_RISK_POLICY；真实 ICM/ADS/Soil 与通信验证仍为 TBD_HARDWARE_TEST。只进行新增文件解析、字段/场景和保护文件哈希核对，未执行三人联调，results 仍只占位。
