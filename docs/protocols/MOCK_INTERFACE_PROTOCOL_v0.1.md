# MOCK_INTERFACE_PROTOCOL_v0.1

日期：2026-10-03（扩充静态用例；保留 M01～M04 定义）。责任方：李青原（NODE-01）、张鹏飞（Feature/Risk）、何宇轩（Schema/Edge）。

状态：第一次 Mock 接口测试的文档与样例定义基线。不代表三方已会签或已执行联调，不新增系统 FROZEN 字段。INTERFACE_GAP 保持待评审；现有 00 和 C++ 结构不变。所有 PASS Criteria 仅为未来验收条件，没有实际 PASS。

# 1. Purpose

验证：李青原 NODE-01 Mock Producer → Telemetry Contract → 张鹏飞 Feature/Risk Pipeline → 何宇轩 Schema Validator / Edge Intake 之间的数据兼容性。

执行时，进入 Feature/Risk **之前**先做来源、结构、身份校验和去重，处理结果再交何宇轩负责的接入侧验证与记录。上述链路表示团队交接职责，不允许未校验或重复消息先进入 Risk。

范围是字段、类型、缺测、时间、身份、重复/冲突语义；不验证真实采集、阈值、预警效果或无线通信。当前测试集包含九组静态样例；本轮新增 M03B、M05～M08，不实现 Producer、可执行 validator、去重存储或三方 Pipeline 接线。

## 1.1 Producer Boundary

以下为职责边界，不表示链路已实现：

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

Telemetry Producer 只消费 SensorSnapshot，不直接读取 ICM、ADS1115、SEN0193 或 I2C Driver。Risk、Storage、Telemetry 应尽可能使用同一份一致观测快照，禁止 Producer 另采一次造成计算输入与发送数据不一致；Telemetry 不重新争抢 I2C Mutex 或等待 ADS 转换。快照内存一致不等于传感器同时采样，逐路时刻与 freshness 仍受 G04 约束。本图不冻结新队列、锁或调度参数；Producer/Serializer/MQTT 完整链路为 NOT_IMPLEMENTED，真实采样为 TBD_HARDWARE_TEST。

审查结论见 [MOCK_INTERFACE_PROTOCOL_REVIEW_v0.1](MOCK_INTERFACE_PROTOCOL_REVIEW_v0.1.md)。

# 2. Interface Source Mapping

唯一仓库：`C:\Users\LQY\Documents\GitHub\ict-2026`，分支“李青原”。HEAD 为 `3f45c84`，固件属于前轮保留的未提交工作区；因此记录实际源码 SHA-256，不以 HEAD 代替工作区内容。

| 来源 | SHA-256 |
|---|---|
| `firmware/node01/components/node_contracts/include/node/sampling.hpp` | `5f06c07e1f6302c302071bf6b25cf907282294324dc6326a237b55c738594394` |
| `firmware/node01/components/node_contracts/include/node/protocol.hpp` | `e2c1c1933fe8aa955e10585bd57dd9c0e301fa672512469145fe5b575baba9c3` |

本分支无 00 PDF；已核查的仓库来源为 `origin/张鹏飞:00_TEAM_SHARED_CONTRACT.pdf` 和 `origin/何宇轩:docs/00_TEAM_SHARED_CONTRACT.pdf`，blob 均为 `340f98c4eadae673f9c99367395d134d069ac221`。既有 JSON 的 schema、平铺身份和位置名称来自此 v2 契约，不是重新设计 C++ 成员。

## 2.1 sampling.hpp

| C++ 来源 | 测试快照位置 | Telemetry payload 映射 |
|---|---|---|
| ImuSample.acceleration_mps2[3] | sampling_snapshot.imu[i].acceleration_mps2 | imu[i].ax/ay/az；m/s²、含重力，x/y/z 分量；不推断安装坐标已校准 |
| ImuSample.angular_rate_dps[3] | 同名成员 | imu[i].gx/gy/gz；°/s |
| ImuSample.acquired_uptime_us | 同名成员 | 无逐样本对应字段，G04 |
| ImuSample.validity | 同名成员，使用枚举名称字符串 | Imu.valid 只有 bool，G02 |
| SoilSample.raw | sampling_snapshot.soil[i].raw | soil.top_raw/middle_raw/toe_raw；int16 或 null，不推断 PGA、电压、湿度 |
| SoilSample.acquired_uptime_us | 同名成员 | Telemetry 无对应字段，G04 |
| SoilSample.validity | 同名成员，使用枚举名称字符串 | Telemetry Soil 无逐路 validity，G03 |
| SensorSnapshot.imu[2] | sampling_snapshot.imu | 0=top、1=toe，与 ImuSite、TelemetryDraft 默认 id 对照 |
| SensorSnapshot.soil[3] | sampling_snapshot.soil | 0=top、1=middle、2=toe，与现有 board 通道定义对照 |

快照 JSON 保留结构成员名，仅作人工/未来测试程序对照 C++ 的测试附带记录，不是已实现的序列化格式。Valid、Unavailable、Error 采用名称，不冻结整数编码。

## 2.2 protocol.hpp

| C++ 来源 | payload 字段 | 规则 |
|---|---|---|
| TelemetryDraft.schema_name / protocol::schema | schema | 严格 zhifang.telemetry.v2，沿用 00 wire 名称 |
| TelemetryDraft.site_id | site_id | MOCK-SITE-01，仅离线命名空间，不代表真实场地已注册 |
| TelemetryDraft.identity: optional<MessageIdentity> | device_id、boot_id、seq | identity 存在才可映射；样例人工指定，不代表 allocator 已完成 |
| TelemetryDraft.timestamp_ms | timestamp_ms | UTC Unix 毫秒或 null |
| TelemetryDraft.uptime_ms/time_synced | 同名字段 | 启动毫秒、可信 UTC 标志 |
| Imu.id/ax/ay/az/gx/gy/gz/valid | imu 中同名字段 | 人工 Mock 值；bool 不能表示三态 |
| Imu.tilt_deg/tilt_rate_dps/vibration_rms | 同名字段 | Feature/标定未就绪，全部 null |
| Soil.top_raw/middle_raw/toe_raw | soil 中同名字段 | int16 或 null，缺测不填 0 |
| Soil.top_pct/middle_pct/toe_pct/avg_pct/growth_pct_min | 同名字段 | 无校准依据，全部 null |
| Experiment.run_id/rain_level | experiment 中同名字段 | 全部 null，测试编号不充当真实 run_id |
| Risk.sensor_score/level/reason_mask | risk 中同名字段 | 全部 null；M01_NORMAL 不表示 Risk 为 NORMAL |
| System.wifi_up/mqtt_up/lora_ready/sd_ok/edge_online/sensor_degraded | system 中同名字段 | 沿用结构默认值：前五项 false，sensor_degraded=true；不声称真实链路或整机已就绪 |

## 2.3 INTERFACE_GAP

| 编号 | 当前缺口和本次处理 | 待团队评审 |
|---|---|---|
| G01 | C++ 无 source/mock；仅外层测试记录标 source=MOCK，不扩展 payload | 李青原、张鹏飞、何宇轩确认测试入口保留来源元数据；裸 Telemetry 不能辨认 Mock，不据此新增正式字段 |
| G02 | ImuSample.validity 三态，protocol::Imu.valid 只有 bool | 无法无损传递 Unavailable/Error；不擅加 IMU 字段 |
| G03 | SoilSample.validity 存在，但 protocol::Soil 无逐路 validity；M02/M03 都投影成 middle_raw=null | 下游不能凭 null 推断两种状态；附带快照不是生产传输解决方案 |
| G04 | 采样有 acquired_uptime_us；Telemetry 无逐样本时间、对齐/freshness 参数 | 不将消息时间等同采样时间，不自定最大年龄 |
| G05 | 两份结构均无错误码字段，Diagnostic Contract 尚未冻结，不能正式表达 I2C_TIMEOUT | 仅作 M03 场景说明；ADS1115、IMU_TOP、IMU_TOE 都可能超时，错误类型不足以定位组件。未来独立 Diagnostic 的组件/错误语义待评审，本轮不设计或新增正式字段；NOT_IMPLEMENTED |
| G06 | TelemetrySerializer / IdentityAllocator 只有抽象接口 | 静态 JSON 不证明 serializer、持久 boot/seq 或重启唯一性完成 |
| G07 | ImuSample 的 float 数组非 optional，invalid 时仍可能有零初始化占位 | 不能把占位 0 当观测；无效 IMU 到 JSON null 的 adapter 待确认；M03 使用 optional Soil raw，M03B 人工定义无效 IMU 映射，不代表 adapter 已实现 |
| G08 | 未实现 duplicate/conflict 门禁、统计、冲突证据存储和完整下游 adapter/接线 | 实现/接入策略缺口；这里只定义预期，统计与证据不新增为核心字段 |
| G09 | 缺测/无效输入后 Missing Policy、minimum valid inputs、degraded 行为、score 是否继续计算及 reason_mask 规则尚未定义 | INTERFACE_GAP / WAITING_RISK_POLICY；由张鹏飞定义，李青原、何宇轩对齐，Mock 协议不补数学策略 |

G01 是 Mock 隔离/交接约束；G02/G03 是正式接口信息损失；G04/G05 待时间/诊断契约评审；G06–G08 主要是实现与适配缺口；G09 是待定 Risk 策略。INTERFACE_GAP 不自动授权修改 v2。

外层测试格式不自动成为共享线协议，也不关闭这些缺口。未经评审与实现，不得声称生产接口已经无损兼容。

# 3. Mock Data Rules

1. 每个 JSON 文件与每条 messages[] 都必须有 `source: "MOCK"`。拆分 message 也必须保留来源，禁止裸 payload 混入真实入口。
2. payload 只包含既有 v2 字段，不加入 source/mock/case_id/validity/error_code/重复计数。
3. case_id、purpose、scenario、messages、sampling_snapshot、expected_behavior、pass_criteria 只是本次离线测试文件组织字段，不是扩展后的 C++ 接口。外层 source 是 G01 的隔离措施，不证明固件已经支持来源传递。
4. 所有数字是人工 Mock 值，不是现场采集、训练数据、Synthetic 物理仿真或实验结论，不能证明硬件精度、土壤含水率或预警效果。
5. risk.*、IMU 派生特征和 Soil 百分比全部 null，不猜阈值/窗口/缺测评分/reason_mask 位号。
6. System 沿用默认未就绪状态，不模拟连接成功。原始 Mock Valid 不意味着 sensor_degraded 必须自动 false；汇总策略不是当前结构提供的实现。
7. 每个用例在独立离线 Mock 上下文执行；重复执行须隔离历史去重状态，避免静态 ID 串扰。测试上下文不是新的消息身份。

M08 是显式的 Schema 负例：仅故意违反既有字段的值/类型或缺少 seq，不扩展正式字段；每条外层增加 invalid_reason、expected_rejection，说明预期在正常 Feature/Risk 前拒绝。INVALID_SCHEMA 是测试预期标签，不冻结正式错误码。M08 不适用下述合法身份约束的正例假设，也不能作为正常 v2 消息发布。

文件形状为 source + case_id + purpose + scenario + messages[] + expected_behavior + pass_criteria。每条正常 message 为 source + sampling_snapshot + payload；M08 另有上述两项测试外层拒绝说明。未来执行器先检查 source / Schema / 类型 / 必须身份字段，基本结构校验通过后才核对快照与 payload 映射一致性；M08 非法输入直接按 expected_rejection 拒绝，不能让映射不一致遮蔽类型错误，也不得借快照修复 payload。不得将整个外层文件作为 v2 发往生产入口。

# 4. Message Identity

唯一身份：**(device_id, boot_id, seq)**，来自 MessageIdentity。

- device_id：设备身份；NODE-01 只在隔离 Mock 上下文使用，不向真实设备入口发布。
- boot_id：一次启动周期；正常样例人工指定 1，M06 另指定 2 表示新的启动周期；不代表已通过掉电唯一性测试。
- seq：该启动周期内原始消息序号；M01/M02/M03/M04 分别 1/2/3/4，M04 各副本均 4；M03B/M05/M07 分别使用 5/6/7，M06 两个 boot 均从 1 开始。M08 故意破坏的身份见其用例定义。
- 新原始消息递增 seq，重试/转发/补传保持三元组不变。正式实现须跨需身份的消息类型统一分配；禁止另建 node_id + sequence。
- boot/seq/uptime 为非负整数，不超过 json_safe_integer_max=9007199254740991；uint64 只是当前内存类型，不是冻结 JSON/LoRa 位宽。

# 5. Duplicate Handling

先校验来源、结构、身份，再查重；去重门禁位于业务/Feature/Risk 前。实际执行器/存储为 NOT_IMPLEMENTED。

Payload 指完整的 messages[i].payload，不包括外层 source、快照、用例说明或预期结果。比较解析后的完整 JSON 字段和值：对象键顺序/空白不影响相等，数组顺序、null/字段缺失差异保留；不按容差忽略变化，不删除 uptime 等字段。这里不冻结 hash 或传输字节规范化。快照与 payload 映射不一致须另报输入不一致，不能由去重检查替代。

## 重复情况：Identity 相同，Payload 相同

结果：**DUPLICATE_MESSAGE**。

- 保留第一次消息；副本不重复执行业务，不重复进入 Feature/Risk。
- 保留重复统计，例如测试结果的 duplicate_count；不是 Telemetry 字段。
- 第一次输入不算 duplicate；M04 第二条才是重复副本。

## 冲突情况：Identity 相同，Payload 不同

结果：**MESSAGE_CONFLICT**。

- 必须保留第一次及第二次冲突消息的完整 payload，并记录关联三元身份和冲突事件。
- 禁止覆盖第一次消息、把冲突当普通 duplicate、静默选择其中一份、忽略冲突或自动改 seq 隐藏问题。
- 冲突副本隔离，不再次进入正常 Feature/Risk；第一次消息不被替换，但不因此宣布它是最终真值。未来由 Edge / Storage / Diagnostic 策略处理。
- 用于排查 seq 生成错误、缓存问题、网络重传异常、多任务竞争。保留/去重/存储能力不能由静态样例证明。

M04 顺序：第 1 条基准；第 2 条 payload 完全相同；第 3 条 identity 不变，仅将 payload.soil.top_raw 从 12000 改为 12001，快照对应 raw 同步变化，避免混入另一种映射错误。

# 6. Validity Rules

| 名称 | 含义 |
|---|---|
| Valid | 当前观测可用；本轮只代表 Mock 场景声明，不代表真实硬件校准或实测 |
| Unavailable | 当前没有获得有效观测，例如未采到、当前不可用 |
| Error | 发生采集、设备或通信错误，当前值不可用 |

null 不自动等于 Error，必须依据场景区分 Unavailable 与 Error。

禁止用 0 代表缺测；**0 可以是有效原始值**，不能全局禁止或自动转 null。

M02 正确表示：payload.soil.middle_raw=null；sampling_snapshot.soil[1].raw=null、validity="Unavailable"、acquired_uptime_us=null。不得 middle_raw=0 冒充缺测，不得向 protocol::Soil 擅加 validity。

M03 同一路 raw/time=null、validity=Error，没有成功采样时间。I2C_TIMEOUT 仅是外层场景，不是实际驱动报错。裸 Telemetry 无法区分 M02/M03 的中间 Soil 状态，必须保留 G03/G05。

原 M01～M04 的 IMU 均 Valid；新增 M03B 的 TOE 为 Error，快照数组保留非 optional C++ 零初始化占位并必须被忽略，采样时刻为 null。对应 payload 不可用数值均为 null、valid=false。这是人工样例的预期映射，G02 三态损失与 G07 adapter 实现仍未解决，不把占位零当观测。缺测/错误不补零进入算法；现阶段 Risk 保持 null，不映射 NORMAL；保留其他有效通道，不由本文制定降级评分规则。张鹏飞负责 G09 Missing Policy；本轮 Risk 为 null 不表示未来缺测永远只能返回 null。

# 7. Time Rules

- uptime_ms：ESP32 启动后的单调毫秒；本次为 Mock 启动时间轴，不是电脑当前时间。一个 boot 的新消息不倒退；重传保留原值。
- timestamp_ms：现实世界 UTC Unix 毫秒，必须有可信依据；允许 null，因为启动后未必立即拥有可信 UTC。
- 所有样例 timestamp_ms=null、time_synced=false，禁止用接收时间、编写日期或 uptime 冒充 UTC。
- acquired_uptime_us 是逐传感器采样微秒，不是 UTC 或消息级时间。本组样例非空值不晚于 uptime_ms*1000；仅检查样例一致性，不冻结未来组包策略。
- 不抹平各通道采样时刻，不新增最大年龄/对齐误差/窗口。Error 的失败尝试时刻没有既有字段，不冒充成功采样时刻。

# 8. Test Cases

共同前提：未来执行器具备离线 Mock 隔离、来源/结构校验和去重门禁。INTERFACE_GAP 导致不能验证时，实际结果记未实现/阻塞，不能算通过。以下仅为预期。

## M01_NORMAL

- **Purpose**：双 IMU/三 Soil 正常结构交接；NORMAL 是用例名，不是 Risk 等级或实验标签。
- **Input**：experiments/mock_interface/cases/M01_NORMAL.json；双 IMU Valid，三 Soil raw=12000/13000/14000、Valid；identity=(NODE-01,1,1)，uptime=1000，timestamp=null。
- **Expected Behavior**：保留 MOCK、分量/单位/位置与原始码；Feature/百分比/Risk 保持 null，不声称真实连接。
- **PASS Criteria**：未来证据证明李青原→张鹏飞→何宇轩交接字段一致、首次仅处理一次、未知 UTC 与 Risk 未补零/改 NORMAL、产物仍为 MOCK。不能执行的部分不填写通过。

## M02_MISSING_SENSOR

- **Purpose**：区分 middle Soil 缺测与有效零值。
- **Input**：M02_MISSING_SENSOR.json；identity=(NODE-01,1,2)，uptime=1500；middle_raw=null，快照中间通道 raw/time=null、validity=Unavailable，其余 Valid。
- **Expected Behavior**：保留 null/Unavailable，不补零、不丢其他通道，Risk 仍 null，记录 G03。
- **PASS Criteria**：未来交接可追溯三态附带记录，证明缺测未当有效输入；仅裸 Telemetry 导致状态丢失时须暴露 INTERFACE_GAP，不宣称整条兼容 PASS。

## M03_SENSOR_ERROR

- **Purpose**：区分采集失败 Error 与未采集 Unavailable。
- **Input**：M03_SENSOR_ERROR.json；identity=(NODE-01,1,3)，uptime=2000；中间 Soil raw/time=null、validity=Error；场景 I2C_TIMEOUT。
- **Expected Behavior**：保留 Error 与人工故障说明，不改 Unavailable/有效 0，不伪造驱动报错或恢复成功，记录 G03/G05。
- **PASS Criteria**：未来记录能区分 M02/M03 快照状态并保留 null；仅凭裸 payload 无法区分时须暴露缺口，不写错误上报已通过。

## M04_DUPLICATE_MESSAGE

- **Purpose**：重复抑制与冲突保留。
- **Input**：M04_DUPLICATE_MESSAGE.json；三条均 identity=(NODE-01,1,4)、uptime=2500；第 1/2 条 payload 相同，第 3 条改 top_raw=12001。
- **Expected Behavior**：第 1 条首次处理，第 2 条 DUPLICATE_MESSAGE，第 3 条 MESSAGE_CONFLICT；正常业务/Feature/Risk 处理次数=1、duplicate_count=1、conflict_count=1，保留基准与冲突原文。
- **PASS Criteria**：未来运行证据证明计数/顺序、不重复处理、冲突隔离、两份原文保留；覆盖、重复评分、虚构持久化均不通过。本次没有实际 PASS。

## M03B_SINGLE_IMU_ERROR

- **Purpose**：补充单 IMU 无效映射，区分单路 Error 与双 IMU 测量不一致。
- **Input**：M03B_SINGLE_IMU_ERROR.json；identity=(NODE-01,1,5)，uptime_ms=3000；TOP Valid、TOE Error、三 Soil Valid。TOE 快照数组为被忽略的零初始化占位、acquired_uptime_us=null；payload TOE valid=false，六轴与派生数值全 null。
- **Expected Behavior**：保留其他有效通道；无效数组不参与观测/特征/Risk；裸 bool 不能区分 Error/Unavailable，保留 G02/G07。单路无效不等于双路 disagreement，未来 consensus 如有也只能表达 unknown/unavailable 类语义；当前不新增 consensus。当前 Risk 全 null；G09 / WAITING_RISK_POLICY 同样相关，单 IMU Error 后剩余输入是否评分、minimum valid inputs、degraded behavior 由张鹏飞的 Missing Policy / invalid-input policy 决定；不规定必须继续/停止评分或降低多少可信度。
- **PASS Criteria**：未来执行证据证明无效占位未进入计算、payload null/false 与快照 Error 可追溯，且未伪造双路不一致；映射未实现或三态丢失必须记录缺口/阻塞，G02/G07/G09 保持开放，不写实际 PASS。

## M05_TIME_NOT_SYNCED

- **Purpose**：验证没有可信 UTC 的合法消息可以进入后续接口流程。
- **Input**：M05_TIME_NOT_SYNCED.json；identity=(NODE-01,1,6)，uptime_ms=3500、timestamp_ms=null、time_synced=false；各路 acquired_uptime_us 不同且不晚于消息时间。
- **Expected Behavior**：按当前协议定义，timestamp_ms=null 且 time_synced=false 本身不应成为拒绝原因；其余来源、结构和身份检查通过后，预期允许进入后续流程；不拿电脑时间、接收时间、uptime 或采样微秒补 UTC。uptime 是消息级启动毫秒，acquired_uptime_us 是逐路采样微秒，timestamp 是可信 UTC Unix 毫秒；G04 保持开放，消息时刻不表示各路同时采样。
- **PASS Criteria**：未来执行时应有校验/接入证据确认未仅因上述 UTC 状态拒绝，并保留 null/false 和各路时间语义，无伪造 UTC；本轮未执行 Validator，未实现时记 NOT_IMPLEMENTED，不写实际 PASS。

## M06_REBOOT_IDENTITY

- **Purpose**：验证跨启动周期相同 seq 不构成重复身份。
- **Input**：M06_REBOOT_IDENTITY.json；两条 identity 依次为 (NODE-01,1,1)、(NODE-01,2,1)，uptime_ms 依次为 5000、1000。单独隔离用例去重上下文，避免与 M01 的人工身份串扰。
- **Expected Behavior**：两个不同 identity 各作为首次输入；第二条既非 DUPLICATE_MESSAGE，也非 MESSAGE_CONFLICT；允许跨 boot 的 seq/uptime 重置，同 boot 规则保持不变。预期 normal_processing_count=2、duplicate_count=0、conflict_count=0；这些去重/冲突门禁和统计尚未实现，G08=NOT_IMPLEMENTED，计数不是实际结果。
- **PASS Criteria**：未来按完整三元身份处理两条输入，不能仅按 device_id+seq 去重；人工 boot/seq 不证明 IdentityAllocator、真实跨启动唯一性、自动序号或持久身份策略实现，G06/G08 均保持开放且相关能力为 NOT_IMPLEMENTED，不写实际 PASS。

## M07_RISK_NOT_CALIBRATED

- **Purpose**：防止有效原始输入被误解为已有合法 Risk 结果。
- **Input**：M07_RISK_NOT_CALIBRATED.json；identity=(NODE-01,1,7)，uptime_ms=4000；双 IMU/三 Soil Valid，risk.sensor_score/level/reason_mask 全 null，sensor_degraded=true。
- **Expected Behavior**：张鹏飞与何宇轩的下游不得默认填 0/NORMAL、猜 reason_mask 或根据 Mock raw 计算风险，也不得自动改 sensor_degraded=false。没有合法结果不等于零风险。本用例全部原始输入 Valid，risk=null 的直接原因是 Risk 尚未正式标定/没有合法运行结果；interface_gaps 为空，不设置 risk_policy_status。G09 仍是项目开放的缺测/无效输入策略问题，但不是本用例 null 的直接原因；不新增 Gap 或正式字段。
- **PASS Criteria**：未来交接记录中三个 Risk null 与 System 默认状态保留，无无依据评分；原始输入全 Valid 不等于 Risk 已正式就绪，未实现接入时如实记录 NOT_IMPLEMENTED，不写实际 PASS。

## M08_INVALID_SCHEMA

- **Purpose**：验证未来 Validator 在正常 Feature/Risk 前拒绝真正的 Schema/类型/身份错误。
- **Input**：M08_INVALID_SCHEMA.json，四条独立负例：schema=zhifang.telemetry.v999；boot_id=字符串 abc；缺少 seq；soil.middle_raw=字符串 hello。每条只注入一种格式错误，invalid_reason/expected_rejection 仅在 message 外层。附带快照是合法对照，不用于修复非法 payload。
- **Expected Behavior**：先执行 source / Schema / 类型 / 必须身份字段校验，四条非法输入均直接按外层 expected_rejection 拒绝，预期正常 Feature/Risk 调用次数=0；只有基本结构校验通过才进入快照映射一致性检查，第 4 条 hello 的类型错误不能被映射不一致遮蔽；不能自动改 schema、转换类型、补身份或从快照回填后放行。middle_raw=null 是合法缺测，以原 M02 为对照，不属于 INVALID_SCHEMA。
- **PASS Criteria**：未来执行证据逐条对应拒绝原因，证明基本结构校验先于映射一致性检查，在正常业务前拦截且合法 null 不被误拒绝。当前 Validator/门禁为 NOT_IMPLEMENTED / BLOCKED、G08 开放；JSON 可解析不等于 v2 合法，更不代表实际 PASS。

2026-10-03 扩充说明：新增五例均为 MOCK TEST DEFINITION。G01～G09 全部保持开放，无新增正式 G10；本轮不实现 Producer、Validator 或 Risk，不生成运行结果。

实际结果在执行后写 experiments/mock_interface/results/，记录输入 hash、实现版本、操作、预期/实际与来源；本轮该目录仅占位，没有测试结果。
