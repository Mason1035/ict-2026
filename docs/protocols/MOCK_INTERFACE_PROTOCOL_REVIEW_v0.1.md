# MOCK_INTERFACE_PROTOCOL Review v0.1

审查日期：2026-10-02。审查范围：本地 `ict-2026`，分支“李青原”，HEAD `3f45c84` 及当前未提交工作区。本文件固化人工审查结论和实际文件核对结果，不是联调测试报告，不冻结新接口。

## 1. Review Scope

实际读取并核对：

- `firmware/node01/components/node_contracts/include/node/sampling.hpp`
- `firmware/node01/components/node_contracts/include/node/protocol.hpp`
- `docs/protocols/MOCK_INTERFACE_PROTOCOL_v0.1.md`
- `experiments/mock_interface/README.md`
- `experiments/mock_interface/cases/M01_NORMAL.json`
- `experiments/mock_interface/cases/M02_MISSING_SENSOR.json`
- `experiments/mock_interface/cases/M03_SENSOR_ERROR.json`
- `experiments/mock_interface/cases/M04_DUPLICATE_MESSAGE.json`

辅助检查：本工作区源文件清单、`node_contracts/protocol.cpp`、`node_logic/logic.cpp`、`node_runtime/runtime.cpp` 与 `experiments/mock_interface/results/`。本地未发现可执行 v2 Schema Validator 或完整 Producer；Feature/Risk 的 evaluate 仍为占位实现。results 只有 `.gitkeep`，没有真实运行结果。本结论不推断其他成员未合并分支或仓库外服务的实现状态。

最高事实源为 `00_TEAM_SHARED_CONTRACT`。本地当前分支未含该 PDF，已核对的本地远程跟踪引用为 `origin/张鹏飞:00_TEAM_SHARED_CONTRACT.pdf` 与 `origin/何宇轩:docs/00_TEAM_SHARED_CONTRACT.pdf`；两者 Git blob 均为 `340f98c4eadae673f9c99367395d134d069ac221`。不声称本轮联网刷新了远端。正式 Telemetry 仍为 `zhifang.telemetry.v2`，唯一身份仍为 `(device_id, boot_id, seq)`；如其他材料冲突，以 00 为准。

本轮核对方法是源码/文档阅读、JSON 解析与静态字段及差异检查；没有执行 Producer → Validator → Feature/Risk → Edge Intake。一次性静态检查不构成项目可执行 Validator，也不构成端到端 PASS。

| 审查输入 | SHA-256（审查前后不变） |
|---|---|
| sampling.hpp | `5f06c07e1f6302c302071bf6b25cf907282294324dc6326a237b55c738594394` |
| protocol.hpp | `e2c1c1933fe8aa955e10585bd57dd9c0e301fa672512469145fe5b575baba9c3` |
| M01_NORMAL.json | `2ff9215cfe0f1f33df77e510b275c7eb7f621e04a987ffda966426850762121a` |
| M02_MISSING_SENSOR.json | `3a264e7d3be00e15dab448fabcc8c65557239396157c788c58e4f43c8341cf4c` |
| M03_SENSOR_ERROR.json | `b336f6cafad0d26e0a707ffafd55bdfef6678cf639e62d7f486ade0fa84371a5` |
| M04_DUPLICATE_MESSAGE.json | `c47da5969c7aec1d0487aaab87bd5a06bc372b198f2ca98166e1c307d96658fd` |

## 2. Overall Conclusion

四组 JSON 未发现违反本轮已确认 Mock 约束的问题，无需提出 JSON 修改；全部保留原文。协议定义与静态样例可作为三人评审基线，但正式接口的信息损失和执行能力缺口仍未关闭。协议定义标记 CONFIRMED 仅表示本次定义核对完成，不表示三方会签、正式接口修改获批或链路测试通过。

必要文档修正为：统一使用李青原、张鹏飞、何宇轩姓名；明确 Validity 含义及 null 不等于 Error；补充 Diagnostic 语义不足、冲突处理禁则、Producer 读取快照边界及 WAITING_RISK_POLICY。没有修改 C++、正式 Schema、四个 JSON、Risk、runtime、Producer 或 Validator。

## 3. Confirmed Correct Designs

1. M01–M04 为 MOCK。数字、时间轴和故障来自人工场景，不是真实硬件、训练数据或实验结论。样例存在与协议存在均不代表实现完成，pass_criteria 仅为未来条件。
2. M01_NORMAL 的 NORMAL 仅是用例名称。所有样例的 `risk.sensor_score/level/reason_mask` 均为 null；没有标定与正式运行结果，不从 raw 或 Mock IMU 推断风险 NORMAL。
3. 0 是合法数值；缺测使用 null，禁止补 0。M01 IMU 中的零值不能被误判成缺测。
4. Valid 表示当前观测可用；Unavailable 表示未获得有效观测（未采到或当前不可用）；Error 表示发生采集、设备或通信错误，当前值不可用。null 本身不能决定后两者。
5. Sampling 三态在附带 `sampling_snapshot` 保留；IMU bool 与 Soil raw/null 的正式投影不能无损传递三态，必须保持 G02/G03 开放。
6. `source:"MOCK"` 在外层 Case/Message 元数据，未进入 payload；`sampling_snapshot` 同样只是离线对照，不是第二套正式 Telemetry。
7. `I2C_TIMEOUT` 只在 M03 场景说明。未新增正式 error_code，未证明实际 I2C 故障或恢复。
8. 新原始消息的 seq 在同一 boot 内递增；重试、补传、转发保持原身份及原消息内容，不重新分配 seq。
9. 同身份同 payload 为 DUPLICATE_MESSAGE，业务仅处理一次，重复副本不得再次进入 Feature/Risk；duplicate_count 仅属测试/接入统计。
10. 同身份不同 payload 为 MESSAGE_CONFLICT，保留首次与冲突原文及事件。禁止覆盖首份、当普通 duplicate、静默选取任一份或改 seq 掩盖冲突；冲突副本不再次进入正常业务。后续由 Edge/Storage/Diagnostic 策略处理，不由此处宣布首份为最终真值。
11. M04 是“首次 → 重复 → 冲突”三条输入；第三条仅改变一个明确 payload 数据字段，不靠身份或时间差异制造冲突。
12. 缺测后的 minimum valid inputs、degraded 行为、是否继续计算 score 与 reason_mask 由张鹏飞后续定义。当前为 INTERFACE_GAP / WAITING_RISK_POLICY；本轮 null 不等于永久规定未来缺测只能返回 null。

## 4. Interface Gaps

保留原协议 G01–G08 编号，单列 G09，避免 Risk 决策被混在实现缺口内。以下均未关闭；INTERFACE_GAP 不自动意味着必须给 v2 增加字段。

| 编号 | 源码/样例证据及影响 | 分类与后续责任 |
|---|---|---|
| G01 | 当前 C++/v2 无 source/mock，裸 payload 无法识别 Mock 来源 | Mock 外层隔离与交接问题。李青原、张鹏飞、何宇轩确认测试入口保留元数据；不要求把 source 加入正式 v2。 |
| G02 | ImuSample.validity 三态，protocol::Imu.valid 仅 bool，Unavailable/Error 会丢失区分 | 真实接口表达缺口。李青原、张鹏飞、何宇轩评审正式承载方式；本轮不选定字段、格式或版本变更。 |
| G03 | 每路 SoilSample 有 validity，protocol::Soil 仅 raw integer/null，无逐路 validity；M02/M03 中间路均投影成 null | 真实接口表达缺口。三人评审下游需要的状态传递，附带快照不能充当生产解决方案；禁止私加 soil validity。 |
| G04 | acquired_uptime_us 在逐路 Sampling 中，Telemetry 无逐路采样时刻，也未规定 freshness/对齐策略 | 时间语义与接口评审事项。李青原、张鹏飞确认时间对齐与算法需求，何宇轩参与接入承载评审；消息 uptime 不可冒充采样时间。 |
| G05 | 两份结构不能正式表达 I2C_TIMEOUT，Diagnostic Contract 尚未冻结 | 诊断接口评审事项。ADS1115、IMU_TOP、IMU_TOE 都可能超时，错误类型本身不能定位组件。未来可能由独立 Diagnostic 表达“哪个组件/什么错误”；本轮不设计 component/error_type 或任何正式字段。李青原、何宇轩参与，张鹏飞确认消费需求。NOT_IMPLEMENTED。 |
| G06 | TelemetrySerializer / IdentityAllocator 只有抽象接口，人工 JSON/boot_id/seq 不是实际分配与编码 | 实现缺口。李青原后续实现并验证 serializer、原始消息身份与跨启动唯一性，不据此改正式 Schema。NOT_IMPLEMENTED。 |
| G07 | ImuSample 浮点数组非 optional，无效时可能保留零初始化占位 | 采样到 Telemetry 的适配缺口。李青原、张鹏飞确认 validity 门禁和无效值映射；不能误杀有效零值，不能把无效占位当观测；同时受 G02 约束。当前四例 IMU 都 Valid，未覆盖无效 IMU。 |
| G08 | 未见 Producer/可执行 Validator/完整下游接线，未实现 duplicate/conflict 门禁、统计、证据持久化及处理策略 | 实现与接入策略缺口。李青原负责固件/Storage 边界，张鹏飞负责 Feature/Risk 接入，何宇轩负责 Schema/Edge；统计和冲突证据不放入核心 Telemetry。NOT_IMPLEMENTED。 |
| G09 | 尚无正式 Missing Policy、minimum valid inputs、degraded 行为、缺测后 score 继续计算条件与 reason_mask 规则 | INTERFACE_GAP / WAITING_RISK_POLICY。张鹏飞负责定义，李青原、何宇轩对齐状态与消费语义。不能由 Mock 协议补公式、补零或宣称 NORMAL。策略定义本身不等于必须扩展 Schema。 |

G01 以及用例名称、场景、附带快照、预期计数属于 Mock 组织/隔离层。G02/G03 是已确认的正式接口信息损失；G04/G05 涉及未来时间/诊断契约评审。是否修改 v2、采用其他已评审承载，必须由团队按 00 决策，本轮不预先批准。G06–G08 主要是实现/适配/接入缺口，G09 是张鹏飞待定的算法策略。

## 5. M01 Review

结论：未发现本轮检查项违规；状态 MOCK，无实际 PASS。

| 检查项 | 实际内容与结论 |
|---|---|
| Schema/身份 | schema=zhifang.telemetry.v2，device_id=NODE-01，boot_id=1，seq=1；平铺身份符合既有 v2，不新增 node_id/sequence。 |
| 时间 | uptime_ms=1000；timestamp_ms=null 与 time_synced=false 一致。 |
| IMU | top/toe；ax/ay/az 为数值，对照 acceleration_mps2，单位 m/s²、含重力；gx/gy/gz 对照 angular_rate_dps，单位 °/s。valid 为 bool true；派生角度/变化率/RMS 为 null，不推断标定。 |
| Soil | top/middle/toe raw=12000/13000/14000，均为 int16 范围内整数，与三路 Valid 快照一致；百分比及派生值 null。 |
| Risk/System | 三个 risk 字段全 null；未伪造 NORMAL。sensor_degraded=true 沿用结构未就绪默认值，不能因 Mock 原始值 Valid 就擅自改 false。 |
| 外层隔离 | source、sampling_snapshot 等不在 payload；未加 error_code 或 Soil validity。 |

未覆盖真实采样、传输、无效 IMU 映射或风险计算。无需修改 JSON。

## 6. M02 Review

结论：未发现违规；状态 MOCK。identity=(NODE-01,1,2)，uptime_ms=1500，UTC 未同步。

`payload.soil.middle_raw=null`；`sampling_snapshot.soil[1]` 的 raw 与 acquired_uptime_us 为 null、validity=Unavailable。没有填 0，没有新增正式 Soil validity，其余有效通道保留。Risk 三字段全 null，未指定缺测数学策略或 NORMAL。

G03 仍存在：裸 payload 无法告诉下游 null 是未获得观测还是采集失败。G09 等待张鹏飞 Missing Policy。无需修改 JSON；不能据此外层快照宣称生产链路三态传递已通过。

## 7. M03 Review

结论：未发现违规；状态 MOCK。identity=(NODE-01,1,3)，uptime_ms=2000，UTC 未同步。

中间 Soil raw 与 acquired_uptime_us 为 null、validity=Error；对应 `payload.soil.middle_raw=null`。与 M02 的差别在快照状态及场景语义，不能根据 payload null 单独判断 Error。

I2C_TIMEOUT 仅是 Mock 场景及预期说明，未进入正式 payload，未加 error_code。场景指定中间 Soil 采集失败，不意味着 ADS1115 已接入，也不意味着错误类型可以唯一定位 ADS1115；IMU_TOP/IMU_TOE 同样可能发生 I2C 超时。保留 G03/G05/G09，Diagnostic 为 NOT_IMPLEMENTED。无需修改 JSON。

## 8. M04 Review

结论：未发现违规；状态 MOCK，无实际去重/冲突执行记录。

| 输入 | 静态核对 | 预期（非实测结果） |
|---|---|---|
| Message 1 | 首次基准，identity=(NODE-01,1,4)，uptime_ms=2500 | 首次处理 |
| Message 2 | 与 Message 1 整条 message 相同，包含 identity 和完整 payload | DUPLICATE_MESSAGE，不重复进入 Feature/Risk |
| Message 3 | identity、uptime_ms、timestamp_ms、time_synced 均不变；payload 唯一差异为 soil.top_raw：12000 → 12001 | MESSAGE_CONFLICT，保存首次/冲突原文和事件，不静默选取或覆盖 |

第三条的 `sampling_snapshot.soil[0].raw` 同步改为 12001，是同一观测的外层对照，不是第二个 payload 差异。静态差异核对确认没有用身份或时间制造冲突。

expected_behavior 中 normal_processing_count=1、duplicate_count=1、conflict_count=1 及保留第 1/3 条均为预期。G08 尚未实现，不能把预期计数写作真实统计。无需修改 JSON。

## 9. Producer Boundary

以下固化已有职责边界，不是新模块实现或已运行链路：

```text
Driver
  ↓
SamplingTask
  ↓
SensorSnapshot
  ├── RiskTask
  ├── StorageTask
  └── Telemetry Producer
        ↓
      TelemetryDraft
        ↓
      Serializer
        ↓
      MQTT
```

Telemetry Producer 消费 SensorSnapshot，不直接读取 ICM、ADS1115、SEN0193 或 I2C Driver。Risk、Storage、Telemetry 应尽可能使用同一份一致观测快照；禁止 Risk 使用一次采样后 Producer 再读硬件，造成计算输入与发送数据不一致。Telemetry 不重新争抢 I2C Mutex，不等待 ADS 转换，不把采样等待引入组包任务。

快照内存一致性不等于传感器同时采样；逐路 acquired_uptime_us 仍须保留其自身语义，freshness 与对齐规则待 G04 评审。此图不冻结新的队列、锁、调度或时间窗口。Producer、Serializer、MQTT 的完整链路为 NOT_IMPLEMENTED，真实采样为 TBD_HARDWARE_TEST。

## 10. Status Matrix

本表只针对当前本地工作区和本次审查链路。CONFIRMED 为已核对事实，MOCK 为模拟场景，NOT_IMPLEMENTED 为该能力尚未在此链路落地，TBD_HARDWARE_TEST 为待真实硬件验证；PASS 只能基于实际执行证据。

| 项目 | 当前状态 | 依据/限制 |
|---|---|---|
| MOCK protocol definition | CONFIRMED | 定义和样例核对完成；G01–G09 保持开放，非三方会签/正式接口扩展获批。 |
| M01 | MOCK | 人工正常场景，Risk 未计算。 |
| M02 | MOCK | 人工 Unavailable 场景。 |
| M03 | MOCK | 人工 Error/I2C_TIMEOUT 场景。 |
| M04 | MOCK | 静态重复/冲突序列及预期计数。 |
| Producer | NOT_IMPLEMENTED | 当前无完整快照到 Telemetry 的 Producer 实现。 |
| Executable Validator | NOT_IMPLEMENTED | 本工作区未发现可执行 v2 Schema Validator；静态审查不计为该实现。 |
| Feature/Risk Integration | NOT_IMPLEMENTED | evaluate 占位和任务调用不等于三人正式算法联调。 |
| Edge Intake Integration | NOT_IMPLEMENTED | 未见本链路接入实现或执行证据。 |
| Diagnostic Contract/Integration | NOT_IMPLEMENTED | 正式诊断字段与承载尚未冻结。 |
| Risk Missing Policy | WAITING_RISK_POLICY | 张鹏飞待定义，G09 开放。 |
| Real Hardware Data | TBD_HARDWARE_TEST | 本样例不提供真实 ICM、ADS、Soil 或通信数据。 |
| Real End-to-End PASS | NONE | results 仅占位；没有本链路运行结果。 |

## 11. Next Step

1. 李青原、张鹏飞、何宇轩评审 G02/G03 信息损失及 G04 时间语义；以 00 为准确定承载边界，未经评审不得修改正式接口。G05 另行评审 Diagnostic，当前只记录需求。
2. 张鹏飞定义 G09 Missing Policy、minimum valid inputs、degraded 行为、score 继续计算条件与 reason_mask；李青原、何宇轩核对生产和消费语义。
3. 后续获准进入实现阶段时，李青原按快照边界接入 Producer/Serializer/身份分配，何宇轩接入 Validator/Edge 门禁，张鹏飞接入 Feature/Risk；明确 Storage/Diagnostic 冲突留证策略。此处为后续建议，本轮不实现。
4. 实际执行时使用隔离 Mock 入口，保留 source 和输入 hash、实现版本、步骤、预期/实际差异及失败/阻塞证据；有结果后才写入 results 并判定对应测试状态。Mock 联调通过也不等于真实硬件验证通过。

本轮仓库变更仅为新增本 Review，以及修正 `docs/protocols/MOCK_INTERFACE_PROTOCOL_v0.1.md`、`experiments/mock_interface/README.md`。四个 JSON、所有 C++ 与正式 Telemetry Schema 均未修改；未生成 Producer、Validator 或测试结果。
