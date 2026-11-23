# 2026-11-21 项目状态与证据边界（C 平台侧）

项目：**智哨防灾——基于昇腾与边缘计算的地质灾害多模态早期预警系统**。分工：C 何宇轩负责平台、Atlas 和 Web，A 李青原负责固件和硬件，B 张鹏飞负责科学契约、校准和特征。最高依据为 [00_TEAM_SHARED_CONTRACT.pdf](../00_TEAM_SHARED_CONTRACT.pdf)（文档基线 1.0）；本文与其冲突时以 00 为准。

本文所有日期、时间均为 **Asia/Taipei（UTC+8）**。本文是 docs-only 状态更新，编写时只读核对了仓库内容，**没有运行测试，没有部署，也没有访问 Atlas、Broker、A 的电脑或任何设备**。2026-11-16 和 2026-11-19 两节转录自 C 的人工验收和预检结论；原始结果包由团队离线保存，不随仓库交付。编写本文时没有读取该结果包，因此本文不是自动测试日志。

## 怎么读本文：三层证据不可混用

| 层次 | 时点 | 含义 | 不能据此声称 |
| --- | --- | --- | --- |
| 仓库静态实现 | `main@0e6e552`（PR #18/#20 于 2026-11-13 合并） | 代码、测试和文档在仓库中存在 | 板端此刻正在运行这些代码，或任何科学/预警效果 |
| 板端实际验收 | 2026-11-16 当天 | C 在 Atlas 平台侧人工核对的测试遥测闭环 | 11-21 链路仍然可用、正式 NODE-01 已接入、传感器精度已验证 |
| 当前状态 | 2026-11-21 | **未复核**；没有 11-21 的新设备验证 | 任何服务、端口或连接器“今天在线” |

## 1. 仓库静态实现（截至 main `0e6e552`）

[PROJECT_STATUS_AND_READINESS.md](../../PROJECT_STATUS_AND_READINESS.md) 的分日增量写到 2026-10-20 为止，之后合并的 PR 在下表补索引。各项细节以对应 PR 和模块文档为准，本表不重复。

| PR | 内容 | 边界 |
| --- | --- | --- |
| [#8](https://github.com/Mason1035/ict-2026/pull/8) | 公开数据 soil/motion **研究预测模型**的 ONNX→ATC→OM→pyACL 板上数值对账，见[部署验证记录](../../experiments/atlas_public_sensor_v1/deployment_results_2026-10-20.md) | 下一观测增量预测，不是滑坡分类器或风险模型；`deployment_ready=false` |
| [#9](https://github.com/Mason1035/ict-2026/pull/9) | 研究模型推理接入平台运行时，`atlas_acl` 由真实推理状态驱动 | 合并时验证的是无 NPU 环境下的降级语义；板上运行由 2026-11-02 [交接日志](../codex-handover-log.md)按负责人口述记载，仓库内没有对应的自动化真机日志。输出不进风险融合 |
| [#10](https://github.com/Mason1035/ict-2026/pull/10)、[#11](https://github.com/Mason1035/ict-2026/pull/11) | 接手现状和 node01 集成评估文档 | 仅评估 |
| [#12](https://github.com/Mason1035/ict-2026/pull/12)–[#15](https://github.com/Mason1035/ict-2026/pull/15) | 阶段 I：source/scope 与生产告警隔离、SD 原始回放、R4 冻结研究规则、研究回放页面 | 研究结果为 RESEARCH，`production_alarm_eligible=false`；阈值 PROVISIONAL-v1 只来自 R4 单场 |
| [#16](https://github.com/Mason1035/ict-2026/pull/16)、[#17](https://github.com/Mason1035/ict-2026/pull/17) | B 的真实工程采集审计、探索分析与校准候选 | B 自己的文档说明候选不可加载为正式标定 |
| [#18](https://github.com/Mason1035/ict-2026/pull/18) | NODE01 诊断长表 → A→B 契约 CSV 转换器 | 转换工具，不是正式训练数据交付 |
| [#19](https://github.com/Mason1035/ict-2026/pull/19) | SD 真实数据 MQTT 回放（REAL/TEST_ONLY）与原始通道曲线 | 强制 TEST_ONLY，不推进正式 current 或告警 |
| [#20](https://github.com/Mason1035/ict-2026/pull/20) | 未标定 PROVISIONAL 实时风险、板端局域网部署与[现场手册](../BOARD_LIVE_DEMO.md) | `status=PROVISIONAL`、`calibration_version=null`、`fusion_eligible=false`，不写 alarms；序数分数不是概率 |

运行环境是 Atlas 200I DK A2 / Ascend 310B4 / Ubuntu 22.04 aarch64 / CANN 7.0.RC1。**这是平台运行环境，不代表项目算法已在 NPU 落地。** 仓库内可核验的 NPU 证据只有 PR #8 的研究模型数值对账；项目没有正式模型（`model_version=null`），也没有任何地灾预警模型的 NPU 推理证据。

前端在 2026-11-14 重建并部署到板端，具备回放和暂定风险展示。这一条来自 C 的部署记录，仓库只保存源码，没有部署日志。

## 2. 2026-11-16 板端实际验收：测试遥测闭环（C 人工验收记录）

**链路：** 备用 ESP32 → A 的电脑（Wi-Fi 接入与转发）→ Atlas Mosquitto → 平台 SQLite。

| 项目 | 记录值 |
| --- | --- |
| 首次尝试 | CONNACK 5（鉴权失败），0/10 发送成功；`boot_id=3` 已消耗 |
| 再次尝试 | 从原凭据重新输入后成功（凭据不在本文记录） |
| 成功 ClientID | `nl4-20261116-1956-443fc8` |
| 发送时间 | Windows 时间 20:07:14–20:07:24（UTC+8） |
| 设备身份 | `site_id=REPLAY-LAB`，`device_id=NODE-01-LAB` |
| Topic | `zhifang/v2/REPLAY-LAB/NODE-01-LAB/telemetry` |
| 消息身份 | `boot_id=4`，`seq=1`–`10`；QoS 1，`retain=false` |
| Broker 回执 | 10/10 PUBACK |
| 平台计数 | `messages_received=10`，`accepted=10`，`rejected=0`，`duplicates=0`，quarantine=0 |
| 落库核对 | 10 条 SQLite 规范化 payload 与发送包逐条一致 |
| 用途标注 | 全部 MOCK/TEST_ONLY，由 connector `cf81d273-b629-4974-83e3-f091d7647e02` 标注；原 payload 不含 source/scope 字段 |
| 告警 | 正式告警 0 条 |
| 暂定风险 | 生成 10 条 PROVISIONAL 记录，`level=null`、`score=null`，`production_alarm_eligible=false`，`uncalibrated, not a formal alarm` |
| 观测内容 | IMU top/toe 均 `valid=false`、数值全 null；soil 和 risk 为 null；`time_synced=false`，`timestamp_ms=null`，`sensor_degraded=true` |

### 这次验收证明了什么

- 当天“设备 → 转发 → Atlas Broker → 平台入库”的测试通路可走通。10 条测试消息被平台完整接收，没有被拒、重复或隔离，并且落库内容与发送一致。
- 用途隔离按设计生效：MOCK/TEST_ONLY 数据没有产生正式告警，暂定风险在观测全空时保持 null，没有编出等级。

### 这次验收不证明什么

- **不是传感器实测**：IMU 全无效、土壤为空，因此不涉及传感器精度、科学模型或预警效果验证。
- **不是正式 NODE-01 接入**：发送方是备用 ESP32 和实验身份 `NODE-01-LAB`。
- **不是契约 M2 完成**：00 §14 的 M2 还要求真实 NODE 链路以及重复注入、断网、断电、回放记录。
- **PUBACK 不等于可靠确认**：按 00 §7，PUBACK 只证明协议接收。平台落库一致是 C 另外做的核对，不构成给 NODE 的 durable receipt，也不授权清理 SD。
- **QoS 与契约不一致**：00 §8 冻结的 telemetry Topic 为 QoS 0。本次测试工具使用 QoS 1，仅是这次测试的参数；正式设备仍按契约执行，若要变更须团队评审并先修订 00。

### 身份与时间说明

| boot_id | 用途 | 规则 |
| --- | --- | --- |
| 1 | 2026-11-14 平台人工 TEST_ONLY 探针 | 不复用 |
| 3 | 11-16 首次鉴权失败尝试 | 已消耗，不复用 |
| 4 | 11-16 成功的 10 条测试 | 不复用 |

- 本记录没有提供 `boot_id=2` 的使用情况，本文不作推断。
- 正式板 Stage 2.2 握手不分配 boot_id，见第 3 节。
- 板载时钟有偏差。时间以 Windows UTC+8 时间和 ClientID 对齐为准，不把平台记录的板端 `received_at` 当作真实时刻。

### 验收后的网络变更（当天）

- 20:25:19 删除临时 SSH 2222 转发和 Atlas 上的 2222 防火墙规则；20:28 C 独立确认 2222 已关闭、1883 仍可连通。**之后不应恢复 2222。**
- 1883 长期链路当时保留，但这**不代表 2026-11-21 仍然可用**。
- 当时观察到无 retained 消息（`NO_RETAINED_OBSERVED`），该结论只适用于那次测试，不推广为“永久无 retained”。

## 3. 2026-11-19 正式 NODE-01 Stage 2.2 握手：已申请，未执行

**申请范围：** ClientID `n01-md-58e6c5747dcc`，只做 2.4 GHz Wi-Fi / TCP / MQTT 3.1.1 CONNACK。不分配 boot_id，不 subscribe，不 publish，不设 Last Will。

**当晚预检结果：** C 检查发现旧电脑转发入口的 1883 不可达，Atlas SSH 也没有可用的管理路径。因此这一轮：

- 没有发生 CONNECT；
- 没有创建握手专用账号；
- 没有开始 Broker 日志监控；
- 没有放行。

**权限前提（未满足）：**

- 现有 node01/platform 账号不能当作 CONNECT-only 账号使用。只限制 ClientID 不等于权限隔离。
- 原账号历史上没有设置 `acl_file`，所以文档里不能宣称“已最小授权”。00 §8 要求设备按 Topic 最小权限接入。
- 握手前需要：专用短期账号；Topic 全拒绝的 pub/sub/read 边界；明确的有效期和撤销责任人；Broker 配置变更事先审批。

**当前等待：** A 按已发送的只读核查提示词提供以下材料：同日 SSID 及 2.4 GHz 证据；电脑 WLAN 入口、路由和 1883 转发的防火墙情况；已有 SSH 路径报告。期间不得自动恢复 2222、切换网络、复位设备或发起握手。只有管理路径、账户权限和 Broker 实时日志基线全部就绪后，C 才会另行放行。

## 4. 2026-11-21 当前状态：未复核

截至 2026-11-21，**没有任何新的设备或板端验证**。下表的“最后已知”只是历史时点的事实，不能当作今天在线。

| 对象 | 最后已知（时点） | 2026-11-21 |
| --- | --- | --- |
| Atlas 平台服务和前端 | 11-14 重建部署；11-16 测试中平台正常入库 | 未复核 |
| Mosquitto 1883 | 11-16 20:28 可连通；11-19 经旧电脑转发入口不可达 | 未复核，不能声称可用 |
| SSH 2222 | 11-16 已删除并确认关闭 | 应保持关闭，不得恢复 |
| Atlas 管理路径 | 11-19 无可用路径 | 等 A 的只读核查报告 |
| 正式 NODE-01 MQTT | 从未连接（Stage 2.2 未执行） | 未接入 |
| TinyQuake（桥接 Broker 端口 18884）连接器 | 历史上仍有重连异常 | 未修改、未复核，不得声称所有数据源已上线 |
| 板端 Demo 流 | C 最近的记录显示仍在运行 | 不能声称已停止或已清理；2026-11-02 日志中“已暂停”只是当时的记载 |
| Atlas NPU 推理（研究模型） | 见第 1 节 PR #8/#9 | 未复核；11-16 验收不含 NPU 推理证据 |

## 5. 科学与数据边界（对照 00）

- **不得输出、展示或写入“滑坡概率”。** 暂定风险的序数分数不是概率，NORMAL 不证明安全。00 §1 规定示例分数不能表述为已证实的预警能力。
- **土壤**：`*_raw` 是 ADS1115 原始码；`*_pct` 是相对湿润度指数，未经土样标定不得称为体积含水率（00 §6）。目前只能使用未标定 ADC 和相对指标。
- **雨量**：水泵 PWM 不是雨量 mm。`rain_level` 只能取 0/1/2/3；流量系数、目标流量、PWM 关系属于 TBD-13 `TODO_CALIBRATION`。
- **阈值**：`provisional-v1-r4.json` 等只是静态参考数据（R4 雨后静置单场，不是干土基线），不是标定阈值。物理危险阈值属于 TBD-10，由 B 负责。
- **用途**：MOCK/TEST_ONLY 与 REAL/OPERATIONAL 严格区分。测试数据不形成正式告警，所有暂定结果都标注“未校准，不是正式预警”。
- **版本**：`model_version`、正式 `dataset_version`、`calibration_version` 均为 null。
- **数据入库**：原始真实、校准和降雨数据不提交到仓库。

## 6. 阻塞、下一步与验收标准

| 顺序 | 事项 | 主责 | 验收标准 |
| --- | --- | --- | --- |
| 1 | 只读核查报告：同日 SSID/2.4 GHz、电脑 WLAN 入口/路由/1883 转发防火墙、已有 SSH 路径 | A | 报告送达 C，不含任何凭据；C 审阅确认 |
| 2 | 恢复 Atlas 管理路径（不复活 2222） | C，A 协助 | C 能经批准的路径独立登录管理 |
| 3 | 握手专用账号：短期有效，Topic pub/sub/read 全拒绝，写明撤销人和有效期；Broker 变更先审批 | C | 审批记录和 ACL 配置经审阅；正式握手前负向测试确认无法 publish/subscribe |
| 4 | Broker 实时日志基线 | C | 握手前已开始记录，能对应到 ClientID |
| 5 | Stage 2.2 握手（C 另行放行后） | A 执行，C 监控 | 专用 ClientID 拿到 CONNACK 0；无 publish/subscribe；日志留存；结束后撤销账号 |
| 6 | 之后的正式遥测（A 分配 boot_id）、干土基线、B 正式科学契约与校准、正式传感器链路验证 | A/B/C | 分别提交可核验证据；在此之前保持“未校准、非正式预警”口径 |
| 7 | TinyQuake 重连异常、Demo 流去留 | C | 由 C 决定后再改动，并单独记录 |
| 8 | 仓库状态同步：[project_status.json](../../project_status.json) 仍是 2026-10-20 的快照 | C | 后续单独更新，本轮未改 |

## 7. 答辩与对外表述口径

| 可以说 | 不可以说 |
| --- | --- |
| 2026-11-16 在 Atlas 平台上实测走通了 10 条测试遥测的 MQTT 接入和入库闭环，数据为 MOCK/TEST_ONLY | 正式 NODE-01 已在线，或真实传感器数据已经实时上云/上边 |
| 平台的用途隔离生效：测试数据不产生正式告警，暂定风险为未标定结果 | 系统已能输出滑坡概率，或已具备预警效果 |
| 研究模型曾在 Ascend 310B4 上完成 ONNX→OM→ACL 数值对账（工程流水线） | 地灾预警模型已在 NPU 上推理，或算法已在昇腾落地 |
| 土壤为未标定的 ADC/相对指标，降雨由泵 PWM 档位控制 | 土壤含水率（%VWC）、降雨量（mm） |
| 正式握手已提出申请，正按最小授权补齐前提 | Broker 已最小授权，或握手已完成 |

## 8. 证据出处

- 仓库静态实现：本文第 1 节链接的 PR、模块 README/CHANGELOG 和实验记录，以 `main@0e6e552` 为准。
- 2026-11-16 验收、2026-11-19 预检、11-14 前端部署、TinyQuake 和 Demo 流状态：均为 C 何宇轩平台侧的人工记录或会话结论。原始结果包由团队离线保存，本文编写时未读取。
- 历史交接事实：[codex-handover-log.md](../codex-handover-log.md)、[BOARD_LIVE_DEMO.md](../BOARD_LIVE_DEMO.md)，按各自日期解释。
- 本文不包含密码、SSH key、token、IP、MAC 或个人机器的完整路径。
