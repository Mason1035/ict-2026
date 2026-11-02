# node01 集成可行性评估与接口对齐（2026-11-02）

状态：**评估待审阅；工程诊断数据已交付并独立回读；未开始施工。**

- 负责人：何宇轩；node01 采集与固件资料提供方：李青原；标定、特征及模型口径由 B 会签。
- 平台基线：`main` / PR #10 合并提交 `7f3ac3c38261e058062b5227684f16a566e15a9a`。已用 GitHub 连接器回读确认远端 main。
- 交付分支：`codex/node01-integration-assessment`，起点为上述 main。只新增本评估，并追加 [Codex 工程交接日志](../codex-handover-log.md)。文档已在本地准备；本轮连接器写入被审批策略拦截，尚未推送文档或创建 PR，详见第 11 节。
- 实物根目录：`~/Desktop/ICT-2026/数据/相同降雨量/`，位于仓库之外。本文只记录定位信息、文件元数据和核验统计，不嵌入原始 CSV 行、串口内容或图片；原始文件与其副本均不得提交或推送。
- 平台行为均为**静态结论，未运行复现**。本轮没有改平台/前端/固件/模型代码，没有合并李青原分支，没有运行平台服务、MQTT、串口、NPU、板上服务或硬件联调。

## 1. 结论与建议的评审范围

**A：离线 CSV 归档与分通道回放可行，数据已经在手边。** 本轮已完成输入完整性核验。下一轮可以在本机独立临时数据目录实现只读导入器，以 7 场干净记录做正向验收，2 场问题记录做隔离及缺测负例。原始长表可无损保留；它不是现有平台可以直接接收的 v2 消息。转换为完整 v2 快照还需解决离线派生身份、未知 system 状态和用途隔离，不能把通过 CSV 核验写成已接入平台。

**B：在线 MQTT v2 有可复用实现，但冻结采集模式尚不具备直接联调准入条件。** 李青原分支已有 serializer、NVS 身份分配、Wi-Fi/MQTT 代码；公开冻结配置关闭网络，本批数据没有正式 boot/seq，也没有 MQTT 接收证据。需要另立最小固件集成变更、平台 REAL/TEST_ONLY 入口与验收，不整支合并、不覆盖原冻结采集版本。

两条路径都必须保留工程诊断用途。进入真实数据的研究推理前，必须修正双 IMU 混入一个 motion 时间序列的问题；缺土壤标定时不构造 soil 模型输入。未标定输出只叫参考指标，不产生“滑坡概率”结论；MOCK/TEST_ONLY 不得形成生产告警。

## 2. 实物数据核验

### 2.1 方法与可复核范围

2026-11-02 在上述仓库外目录只读遍历，共 **70 个文件、67,446,450 字节**：9 组 BEG/CSV/END、9 组 session/events/device/serial、4 张 JPG、2 份 DOC、1 份 DOCX。具体大小和完整 SHA-256 见附录；没有将任何实物复制进仓库。

对 9 场全部独立回读，而非只相信 END 的 `csv_verified=true`：

1. 以二进制读取 CSV 至 EOF，对**完整原始字节（含注释、表头、原换行）**计算长度、`zlib.crc32(bytes) & 0xffffffff`、SHA-256；不先改编码或换行。
2. 验证第 1–9 行是注释、第 10 行为固定 22 列表头；用 CSV 解析器数第 11 行起的数据行，按 kind/channel/validity/error 统计，不把一行误作一个整帧。
3. 独立长度、数据行数、CRC32 分别与 END 的 `csv_bytes`、`verified_rows`、`csv_crc32` 做全等比较；9 场均相等。每场 `produced=enqueued=dequeued=accepted=verified_rows`；`queue_drop/internal_drop/errors/uncertain/replay` 均为 0。这里的 `errors` 是存储汇总字段，不是 `sensor_errors`。
4. 每场 TOP/TOE 和三路 soil 的 `Valid && error=0` 计数与 END 全等；Error 行数与 `sensor_errors` 全等。全部记录的 timestamp 为空、time_synced 为 false。全部 acquisition_index 在各文件中为 `0..行数-1`、无重复；这只证明本次记录链连续，不证明传感器每个硬件采样都被保留。
5. BEG/END 的 experiment_id 与 ELF 身份相符，END 的 `stop_us-start_us=actual_duration_us`；与 session 的场次、开始观测和设备终结结果对应。9 份 events.jsonl 全部逐行解析成功，均含开始观测和设备终结记录。
6. 独立计算 27 个 `serial.bin/device.txt/events.jsonl` 的大小和 SHA-256，全部与各 session 的 `evidence_files` 相等；session 本身及 BEG/END 另计算指纹。原 session 中 `HOST_FILES_NOT_VERIFIED` 等历史字段不改写，本次独立核验是新增结论。

### 2.2 9 场逐场结果

条件列是目录与交付说明的记录，未完成降雨量或安装条件的独立标定。时长来自 END，单位秒；有效数按 TOP/TOE、soil TOP/MIDDLE/TOE 排列；错误列为 **I2C / sensor**。CRC 列给出独立值，均与 END 匹配。

| 场次 | 条件 | 实际秒数 / 终止原因 | 数据行 | TOP / TOE 有效 | soil 三路有效 | I2C / sensor 错误 | CRC32 对 END | 分区 / 会话 |
| --- | --- | --- | ---: | --- | --- | --- | --- | --- |
| **N0000001** | 50 PWM 降雨 | 180.002658 / TIME_LIMIT | 36,979 | 17,998 / 17,901 | 360 / 360 / 360 | 0 / 0 | `55e4c7c7` **匹配** | 干净 / SUCCEEDED |
| **N0000002 ⚠** | 70 PWM 第 1 次（I2C错误） | 180.000272 / TIME_LIMIT | 36,020 | 17,465 / 17,330 | 166 / 145 / 143 | 527 / 771 | `311660b9` **匹配** | **问题场 / FAILED** |
| **N0000003** | 出错后 30s 沙盘外不下雨 | 30.000163 / TIME_LIMIT | 6,156 | 2,996 / 2,980 | 60 / 60 / 60 | 0 / 0 | `738d1e73` **匹配** | 干净 / SUCCEEDED |
| **N0000004** | 出错后 180s 沙盘外不下雨 | 180.002845 / TIME_LIMIT | 36,978 | 17,998 / 17,900 | 360 / 360 / 360 | 0 / 0 | `711957e5` **匹配** | 干净 / SUCCEEDED |
| **N0000005** | 出错后 180s 沙盘内不下雨 | 180.001202 / TIME_LIMIT | 36,977 | 17,996 / 17,901 | 360 / 360 / 360 | 0 / 0 | `e3e0ae23` **匹配** | 干净 / SUCCEEDED |
| **N0000006 ⚠** | 沙盘内不下雨、启动水泵（目录备注） | 46.157879 / USER_STOP | 9,414 | 4,574 / 4,553 | 0 / 0 / 0 | 72 / 287 | `4de89cf9` **匹配** | **问题场 / FAILED** |
| **N0000007** | 30 秒传感器检查；泵状态未独立确认 | 30.001126 / TIME_LIMIT | 6,159 | 2,998 / 2,981 | 60 / 60 / 60 | 0 / 0 | `0b436392` **匹配** | 干净 / SUCCEEDED |
| **N0000010** | 70 PWM 第 2 次降雨 | 180.002109 / TIME_LIMIT | 36,978 | 17,998 / 17,900 | 360 / 360 / 360 | 0 / 0 | `348d2ed5` **匹配** | 干净 / SUCCEEDED |
| **N0000011** | 100 PWM 降雨 | 180.000678 / TIME_LIMIT | 36,955 | 17,995 / 17,880 | 360 / 360 / 360 | 0 / 0 | `51f7f4f7` **匹配** | 干净 / SUCCEEDED |

“干净”仅表示本次文件完整、无已记录传感器错误。它不等于已标定、无采样抖动、长期稳定、掉电安全或正式实验验收。7 场干净记录共 197,182 数据行；全部 9 场共 242,616 行。场次编号不连续，不据此补造 N0000008/9。

### 2.3 问题场的独立处理

- **N0000002：70 PWM 第 1 次，问题场。** END 记录 I2C 527、sensor 771；其中 IMU Error 145 行、soil Error 626 行。soil 总记录各 360 行，但有效仅 166/145/143，其余载荷为空，不能把空载荷补零。session 为 FAILED、sensors_clean=0；文件字节/CRC/行数核验通过说明文件完整保存了错误，不代表传感器采集合格。整场从正向回放基线、条件比较与任何训练候选中排除，只进入故障隔离验收集。
- **N0000006：目录注明启动水泵，问题场。** 请求 180 秒，实际 `46.157879s`，END 为 USER_STOP；I2C 72、sensor 287，其中 IMU Error 8 行、soil Error 279 行。soil 三路各有 93 个尝试记录，但**有效 0/0/0，全部 acquired_uptime_us 和 soil_raw 为空**。session 为 FAILED、sensors_clean=0；不能当完整 180 秒对照，也不能把它解释成 0% 湿度。
- N0000005 同为沙盘内不下雨且无记录错误，N0000006 在“启动水泵”条件备注下出现错误，N0000007 短场恢复为无记录错误，构成**相关性线索**。现有记录没有与 MCU 时基对齐的水泵开关沿、供电波形、I2C 电气波形、重复随机化对照；安装、供电、线缆和初始土壤状态也没有被控制。不能断言“水泵启动导致 I2C 故障”，也不能从 N0000007 证明根因消失或传感器永久安全。
- 根因排查若另获授权，应由李青原补充泵事件时序、接线/供电/地线、总线与电源测量及重复对照，何宇轩组织验收。本轮不启泵、不重采、不做硬件故障注入。

### 2.4 身份、时间和条件的证据边界

9 场 BEG/END 与 CSV 头中的 ELF 声明均为 `288e76253c36efcc1939959443c2ae58c245eb2ea0f7ba667e950d9d2372119d`，与 `origin/李青原` 文档一致。**这是产物自述身份一致性；未取得 ELF/bin 本体重算，也未独立证明该分支当前源码可重建此产物。** 9 份 session 均为 `firmware_identity=NOT_OBSERVED / actual_device_elf=null`，不能改写成 PC 已完成独立身份确认。

CSV 自带 `NODE01_ENGINEERING_DIAGNOSTIC_V1; not experiment CSV; not training data; calibration=TODO_CALIBRATION`；BEG/END 的 REAL_SENSOR 和文件头的真实传感器来源证明用途为真实传感器工程诊断。session 的 `test_only=false` 是 PC 采集程序字段，不能覆盖文件头的工程诊断用途，也不意味着平台 OPERATIONAL 或允许生产告警。

根目录 `数据说明.doc` 仅说明截图两次记录分别对应正式降雨开始/结束。4 张 JPG 实际是秒表截图；本轮已查看，不能代替接线图、安装照片、逐行 UTC 或降雨量标定。子目录另有两份说明，含盒体/土壤可能移动、初始土壤状态不同的操作者解释；未获独立位移测量或标定支持，不据此生成 SLIP 真值或可比的降雨强度。

目录名“相同降雨量”及 50/70/100 PWM 只是条件记录，**不证明等总量、等强度或任何 mm、mm/h、L/min 数值**。截图与 PC BEGIN 观测之间缺少可核验同步关系，不能直接切成精确到 CSV 行的降雨区间。

### 2.5 与既有文档的时点差异

- 旧交接日志“本轮未取得原始文件/原始采集未交接”只适用于 PR #10 当时。本次已取得并核验上述 9 场，不能继续以数据未交付为阻塞理由；旧日志保留历史，本轮追加更新。
- `origin/李青原` 的 `docs/NODE01_SANDBOX_CAPTURE_V1.md`（本地 ref `ef13495b64c23d0982e3fc2698438bf0f1d4ecde`）记载的是另外的 30/120/300 秒及提前停止场次。本批是 7 场 180 秒请求、2 场 30 秒请求，其中一场提前停止；不能把其 300 秒 61,631 行成绩挪给本批，也不能因短文件名相同认定同一场，必须使用完整 experiment_id 和哈希。
- 分支的“稳定候选”没有覆盖本批两场 FAILED；本批发现的错误必须单列。反之，零传感器错误也不能改写其 `UNCALIBRATED / INTEGRATION_NOT_READY` 限制。
- 公开说明称完整冻结档案保留本地，本批实物中仍无 freeze-manifest 和固件本体，缺口未关闭。目录中的 9 个 `serial.bin` 是串口日志，**不是固件 bin**。

## 3. 平台契约与实际接收边界

契约依据为根目录 [00_TEAM_SHARED_CONTRACT.pdf](../../00_TEAM_SHARED_CONTRACT.pdf) 第 5–8、11 节（尤其 PDF 第 4–7、9 页）；本轮只读提取并核对相关完整页文本，不修改契约。主 README 的正式实验 CSV、工程诊断长表、完整 NODE v2 是三个不同产物，不能互相改名冒充。

静态代码定位均相对于 `7f3ac3c`：

| 边界 | 代码定位 | 对本次接入的含义（静态结论，未运行复现） |
| --- | --- | --- |
| 完整 v2 校验 | `platform_backend/src/geohazard_platform/telemetry.py:18–145`，`validate_telemetry()` | 顶层及各对象字段集合严格固定；缺字段或额外字段拒绝；不会接收 CSV 或自动修复它。imu 必须固定两项，依次 top/toe。 |
| 缺测/数值 | 同文件 `:95–138` | timestamp 可 null，未同步必须 null；invalid IMU 的 9 个数值必须全 null；raw soil 为有符号 16 位整数或 null；所有数字有限，不能传 NaN/Infinity/空字符串。完整 NODE 的 valid 与 6 个 system 标志必须是布尔。 |
| 可靠接收 | 同文件 `:165–226`，`ingest_telemetry()`；`edge_intake/intake.py` | 校验后调用 Edge Intake，再在 SQLite 事务保存 payload/context/接收路径；上游 source 只能 REAL/MOCK。单独 Edge Intake 是内存快照，不是持久化确认。 |
| 幂等与当前值 | 同文件 `:186–210`；`database.py:66–88` | 唯一键为 device_id/boot_id/seq；device_id 全局绑定 site/source。相同原文为 duplicate，冲突隔离。新见 boot 且无 UTC 可能被当当前，不能把首次历史导入自动当实时。 |
| HTTP 测试口 | `main.py:251–257` | 强制 MOCK/TEST_ONLY 且只接受 MOCK-/DEMO- 身份；不能将真实传感器 CSV 送这里再声称 REAL 接入。 |
| MQTT 来源/用途 | `connectors.py:255–289`，配置校验 `:78–143` | 普通 telemetry_v2 的 REAL 被自动置 OPERATIONAL；没有可配置的 REAL/TEST_ONLY。保留消息拒绝，Topic 与身份必须一致。诊断直连前需补用途边界。 |
| 研究推理挂接 | `main.py:87–94`；`inference.py:175–206` | accepted 且 current 后会 observe；无 UTC 时用当前 UTC 标窗口时间，两个 valid IMU 依次进入同一个 motion 缓冲。原样回放会误标时间/混通道。 |
| 告警 | `telemetry.py:214–219`；`database.py:92–99`；`main.py:289–292` | 风险升级条件未检查 source/scope；alarms 没有 scope，查询只按 source。当前诊断 risk 全 null 不触发该分支，但不能据此宣称平台已普遍隔离 TEST_ONLY。 |
| 时间/展示 | `dashboard.py:39–72` | 未同步数据只展示 arrival_only 新鲜度；received_at 是接收时间，不是采样时间。原始 soil raw 会保存在 payload，现有 moisture 卡片取 avg_pct，必须保持未知。 |

完整 NODE 校验还要求身份与 uptime/seq 是 JSON 安全整数 `0..9007199254740991`、不接受布尔冒充整数；site/device 是合法 MQTT 单段字符串。LoRa 部分投影在当前 validator 中未实现，不能借其未知状态可 null 的约定绕过离线 CSV 的 full-profile 缺口。

当前 duplicate 判定比较原文与 source，未比较 scope；同一消息身份不能通过另一次导入来重标用途。离线/在线、测试/生产各自注册与隔离是前置条件，不能仅靠传入不同 context 解决历史归属。

### 3.1 实测 22 列逐项对照

以下“可原样接收”仅指解析出合法 JSON 数字后数值/单位无需再算；CSV 文本仍需适配组帧。所有源字段在仓库外原始归档中保留，未进入核心 payload 的信息放接入 context 或关联原始记录，不能擅加 v2 字段。

| # | CSV 列 | 平台对应/结论 | 规则与缺口责任 |
| --- | --- | --- | --- |
| 1 | kind | 必须转换：选择 imu/soil 载荷 | 只接受实测的 imu、soil；未知 kind 隔离，不能把五类记录当五个设备。导入器由何宇轩侧实现。 |
| 2 | channel | 必须转换：imu[].id / soil.*_raw 的键 | imu 0→top、1→toe；soil 0→top_raw、1→middle_raw、2→toe_raw。这是固件通道定义，实际安装位置仍需李青原确认。 |
| 3 | acquisition_index | 必须保留到 sidecar；不得原样充当 seq | 启动内分配顺序，跨两 IMU/三 soil 共用；不是时间戳、同帧号或正式消息身份。详见第 4 节。 |
| 4 | attempted_uptime_us | 必须保留并转换用于失败事件排序 | MCU 开始读取的启动内微秒；失败缺 acquired 时只能记尝试时间，不能伪造成功采样时间。不得直接用 CSV 行号推导。 |
| 5 | acquired_uptime_us | 必须保留；有条件换算/组帧 | 成功读取完成时的 MCU 单调微秒，非传感器同步时钟、非 PC 时间。帧 uptime 规则见第 4 节；失败空值不补 0。 |
| 6 | timestamp_ms | 必须转换为空：`timestamp_ms=null` | 本批全空；不可写主机 BEGIN、截图时刻或导入时刻冒充逐样本 UTC。可信 UTC 非只读回放前置，但在线启用 true 须李青原提供同步机制及误差证据。 |
| 7 | time_synced | 可原样接收为 JSON `false` | 文本 false 解析为布尔，不传字符串；与 timestamp=null 成对。 |
| 8 | validity | 必须转换为 imu[].valid / soil 缺测 | Valid 且 error=0、数值齐全有限、acquired 存在且未过期才可有效；其他状态失效。完整原枚举留 sidecar，soil 无 valid 字段，以 raw=null 表示缺测。 |
| 9 | error | 必须保留到 sidecar；错误使载荷失效 | 数字错误码不是风险分或 reason_mask。禁止把错误行的空载荷当观测 0。未发布的错误码解释由李青原补，不猜电气根因。 |
| 10 | ax_raw | 核心无对应：保留 sidecar | IMU 原始有符号码，不发送额外 imu.ax_raw，不直接改名 ax。 |
| 11 | ay_raw | 核心无对应：保留 sidecar | 同上，保留 Y 原始码及来源索引。 |
| 12 | az_raw | 核心无对应：保留 sidecar | 同上，保留 Z 原始码，不能用其充当去重力振动。 |
| 13 | gx_raw | 核心无对应：保留 sidecar | 原始角速度码；已有 gx_dps 时不二次换算。 |
| 14 | gy_raw | 核心无对应：保留 sidecar | 同上，保留 Y 原始码。 |
| 15 | gz_raw | 核心无对应：保留 sidecar | 同上，保留 Z 原始码。 |
| 16 | ax_mps2 | 可原样接收：imu[channel].ax | m/s²，含重力；只改键名，保留 sensor_axes_unmapped，不默认已对齐坡面或 ENZ。 |
| 17 | ay_mps2 | 可原样接收：imu[channel].ay | 同上，不再乘 9.80665。 |
| 18 | az_mps2 | 可原样接收：imu[channel].az | 同上；未标定不扣除人为估计的静态偏置。 |
| 19 | gx_dps | 可原样接收：imu[channel].gx | °/s；不转换为 rad/s，不再次除以 16.4。 |
| 20 | gy_dps | 可原样接收：imu[channel].gy | 同上，保留安装朝向未映射状态。 |
| 21 | gz_dps | 可原样接收：imu[channel].gz | 同上；六轴只在 IMU Valid 行有载荷。 |
| 22 | soil_raw | 可原样接收为相应 soil.*_raw 整数 | **单个 soil 行只有本通道这个原始值，12 个 IMU 载荷列为空**；不是一行三路 soil 数组。合法范围 -32768..32767，零也是合法读数；Error 行为 null。缺标定时五个百分比/增长字段全 null。 |

### 3.2 CSV 不含、完整 v2 又要求的字段

| 平台字段/元信息 | 结论 | 补齐方式与负责人 |
| --- | --- | --- |
| schema | 可设置契约常量 | 仅在候选快照真正满足完整消息时设置 zhifang.telemetry.v2；不把原始 CSV 本身宣称为该 schema。 |
| site_id、device_id | **原生接入阻塞缺失** | CSV 声明设备 NODE-01，但无已确认 site/全局注册。何宇轩确认注册；李青原确认物理设备对应关系。离线使用明确的派生回放身份，不能占用真实在线设备的当前态。 |
| boot_id、seq | **原生接入阻塞缺失** | CSV 头明示 boot_id=unavailable，experiment_id 中的 token 不是正式 boot。李青原提供持久 boot/统一原始消息 seq 机制与验收；离线派生身份另见第 4.3 节。 |
| uptime_ms | 必须转换 | 由已声明的 MCU 帧时基整除 1000，不从 PC 时间/行号生成；保留微秒与原始 source-row 映射。 |
| imu 两项、valid | 必须组装 | 始终 [top,toe]，缺通道仍保留 id、valid=false，9 个数值全 null。校验器虽允许 valid=true 的数值为 null，适配器仍要求六轴齐全，不能只按校验器最宽规则制造有效样本。 |
| tilt_deg、tilt_rate_dps、vibration_rms | 必须置 null | 不是 CSV 直接观测；缺安装坐标、偏置、去重力/滤波/特征窗口与缺测规则。由 B 定义、李青原提供安装/标定证据；不能用原始加速度模长充当 vibration_rms。 |
| soil.top_pct/middle_pct/toe_pct/avg_pct/growth_pct_min | 必须置 null | 三路标定及因果对齐规则缺失，由李青原交付原始标定、B 审定方法；不为驱动 soil OM 而填数。 |
| experiment.run_id | 可转换为完整诊断 experiment_id | 明确 diagnostic_run；不据此升级为正式实验 run。完整 ID 关联 BEG/END/session，避免不同启动复用 N0000011 等短文件名。 |
| experiment.rain_level | 必须置 null | 只有 PWM/目录条件，没有获批的 0/1/2/3 雨级映射和流量标定；不将 50/70/100 直接塞入 rain_level。 |
| risk.sensor_score / level / reason_mask | 必须全部 null | 无正式特征及标定依据；未知不补 0、NORMAL 或 0 位掩码。TinyQuake 分类概率也不能填入。 |
| system.wifi_up/mqtt_up/lora_ready/sd_ok/edge_online/sensor_degraded | **完整 NODE 离线转换的阻塞缺失** | 需要同一快照时刻的已观测布尔状态。END 文件完整不等于每帧 sd_ok=true；主机与串口连通不等于节点 Wi-Fi/MQTT/edge 在线。sensor_degraded 可按获批的缺测规则派生并声明，但其他状态不能批量补 false。李青原补可对应时基的状态证据；否则走第 7 节的原始离线记录旁路，不送完整 v2。 |
| source、scope、calibration、coordinate、量程/PGA、原文件定位/哈希 | 必须放接入元数据 | source=REAL、scope=TEST_ONLY；calibration=uncalibrated、coordinate=sensor_axes_unmapped。CSV 中声明的 ODR、±16g、±2000°/s、PGA ±4096mV、ADS 128SPS 作为声明元数据，不等于实测标定。何宇轩侧保留，不扩展核心字段。 |

## 4. 长表行到帧的组装规则（设计，未实施）

### 4.1 先保留事件，再生成低频快照

1. **原始层无损。** 以完整 experiment_id、CSV SHA-256 和 acquisition_index 唯一定位源行，保留 kind/channel、attempted/acquired 微秒、validity/error、单位和载荷。原始文件仍在仓库外；数据库/索引/派生回放也只放独立本地工作目录，不进入 git。重复导入同一源不得增加观测，冲突须隔离。
2. **按场次和通道拆流。** imu/0、imu/1、soil/0、soil/1、soil/2 各自一条时间序列；禁止用相同 acquisition_index 将 TOP/TOE 连接，因为索引全局分配，每条记录不同。该字段是启动内分配顺序，不保证传感器时间顺序；本批文件连续也不改变其语义。
3. **使用 MCU 单调时基。** 成功事件以 acquired_uptime_us 排序，acquisition_index 只作同值时的稳定定位。acquired 是 MCU 读取完成时间，含总线/调度延迟，不是 DRDY 边沿或传感器精确采样时刻。错误事件无 acquired 时保留 attempted 及“仅尝试时间”标记；保守地从该次失败尝试起使通道失效，不能沿用旧有效值掩盖失败。
4. **不隐去异常。** 缺/重复索引、未知通道、时间回跳、非法数字、错误行载荷与声明冲突均输出定位报告；不静默排序修复为“正常采样”。本批成功观测在各通道 acquired 上严格递增，不能外推下一批也如此。

### 4.2 候选 v2 快照的因果对齐

仅在第 3.2 节身份及 system 阻塞解除后启用下列转换；这不是将原始长表改造成正式实验宽表。

- 以 END 的 start_us 为场次锚点，设计默认输出 **1Hz 工程诊断快照**：`t_k=start_us+k*1,000,000`，`k>=1` 且 `t_k<=stop_us`。原始层仍保留起始段、全部中间观测及尾段，不补造尾帧。7 场正向输入按此计划应有 960 个候选快照；这是设计预期，不是已生成或已接受条数。
- 每个 tick 对每个通道只选**不晚于 tick 的最新源事件**；遇最新事件为 Error 则缺测，不回退到错误前值。不能取未来最近邻来制造同步。两个 IMU 和三个 soil 的各自源时刻、source index、年龄及通道间偏差进入 sidecar。
- 暂借分支 `make_draft()` 的驱动存活上限作为可评审工程配置：IMU 年龄 `<=30,000us`、soil `<=1,500,000us`，必须 acquired 存在且年龄非负。**这两个值不是 B 已标定的特征窗口或实验对齐容差**；B/何宇轩会签前不拿它们支撑科学比较或风险判断。错误、超龄或缺测置相应 IMU false/全 null、soil raw=null。
- `uptime_ms=floor(t_k/1000)`，保留启动绝对单调时基，不减 start_us 后冒充设备 uptime。µs→ms 丢失小于 1ms 的细节，原微秒留在 sidecar。5 个通道不是同时采集，不能把共同帧时间解释为每个传感器的真实采样时间。
- 一帧必须含全部 v2 键、固定两个 IMU 和完整 soil/risk/system/experiment 对象。六轴依规则取值，校准依赖量一律 null。重复引用同一个 source index 是“快照复用”，不是新观测；它不得再次推进研究模型窗口。
- 该快照只是低频状态投影，会舍弃许多 100Hz 观测，**不能代替原始信号用于波形/频谱分析或 TinyQuake**。原始回放按第 4.1 节进行，模型适配不能从 1Hz 快照反造 100Hz。

### 4.3 离线身份与平台时间约定

- 离线源的正式 boot/seq 已缺失，不允许“acquisition_index=seq”、截取 experiment token 当 boot、对哈希随意取模后声称设备身份。由导入器的持久注册表给每个 `(完整源身份、文件哈希、适配版本、组帧配置)` 分配**独立回放 device_id 与 JSON 安全整数 boot_id/seq**；回放设备与物理 NODE-01 名称不同，site 也使用经负责人确认的离线专用命名空间。明确 `generated_replay_identity=true`，原 boot 仍未知。
- 每个派生消息创建时 seq 递增；重试/重复导入保持相同派生身份和 payload。适配配置变化须新建版本/回放会话，不能以同一身份覆盖。该设计需实现冲突/幂等检查，不把派生身份追认为李青原设备发出的原始消息。
- 本批始终 `timestamp_ms=null / time_synced=false`。平台 `received_at` 使用**真实导入/接收 UTC**；host begin observation、截图时间只是独立证据，不回填采样 UTC。离线轴使用 `acquired_uptime_us-END.start_us`；失败用 attempted 相对时间并显式标识。不同启动之间不拼成连续时间线。
- 历史回放须留在隔离的数据库/回放视图，不进入生产设备的 is_current。当前新见 boot 的逻辑不会自动识别“历史”；context 标 TEST_ONLY 也不能自动解决此问题。现有 history/dashboard 按 received_at 排序/绘图，需单独的相对时间展示，不能把快速回放的接收间隔称为采样间隔。
- 研究窗口不能沿用 `inference.py` 在无 UTC 时逐次 `utc_now()` 的时间：应保存 boot/run 内的单调起止与 time_basis；若仍保留 UTC 字段，要与接收时间分开。原生在线身份与派生回放身份不能共用注册、当前态或告警通道。

## 5. 双 IMU、采样频率与模型窗口

### 5.1 TOP/TOE 窗口必须先拆开

当前 `InferenceService.observe()` 按 site/device 建缓冲；source/scope/boot 变化会重置，但没有 sensor_id。它把一条消息里两个 valid IMU 的六轴样本先后 append 到同一 `motion` deque。两条空间观测因而被当成同一传感器的连续时刻，一条消息还可能提交两次窗口；相同帧内两条使用同一 stamp。无 UTC 时 stamp 又是执行时刻，重复快照及采样缺口没有被识别。**这是静态结论，未运行复现；本轮不修改代码。**

真实数据研究推理的前置设计：

- 缓冲至少按 `(site_id,device_id,source,scope,boot/run,sensor_id)` 区分，motion_top、motion_toe 各收本通道独立的新观测；保留源 index/采样微秒。来源、用途、启动/场次、单位/适配版本变化均重置，禁止跨场续窗。
- 只在本通道出现新的有效六轴样本时推进；重复快照不追加。无效、回跳、超出获批采样间隔/容许缺口时清窗并报原因，不把跳过失败后的 8 点直接当无缺口连续窗口，不补零/复制/未来插值。
- 模型输入仍分别为 `(1,8,6)`，顺序 ax/ay/az/gx/gy/gz；可以复用同一研究 OM 分别执行，但不得把 TOP/TOE 交织成 8 点，亦不得自行拼成 12 通道喂既有 OM。双通道一致性或融合要另有 B 契约。
- `inference_results`、API 和页面需有可辨识的 sensor_id、run/boot、time_basis、单调窗口边界与适配版本；现表只有 model/site/device/UTC 起止，不能可靠区分两路。历史结果只标旧语义，不回填伪造传感器归属。
- 影响范围：`inference.py` 的缓冲/窗口和队列元信息，`main.py` 的 observe 挂接，`database.py` 迁移，推理结果查询与前端类型/展示，以及相应回归；ACL 单线程、有界队列、降级及接收先持久化的隔离仍须保留。拆通道可能增加推理调度量，需测吞吐/丢弃数，不能以打开双路为由宣称模型效果更好。
- 单纯原始归档可以不调用研究推理；若下一轮仅做 A 的归档验收，应明确关闭/绕开 observe。接入已有推理挂接的任一路径前，以上窗口边界必须完成并验收。

### 5.2 三种规格分别解释

| 规格 | 含义 | 不允许的推断 |
| --- | --- | --- |
| node01 IMU ODR 100Hz，每路 soil 约 2Hz | 来自本批文件头/BEG/END；IMU 走 DRDY 并保留显式 fallback，记录的 acquired 是读完成时间 | 长表总行率约 205 行/s 不是单 IMU 205Hz。7 场“干净”也有抖动/不等计数，不能认定严格等间隔或硬件零漏采。 |
| TinyQuake 40Hz、80 点、三轴 ENZ | 标称 2 秒窗口，输入 `(80,3)`；相邻点间隔 25ms，首末点相差 1.975s。固件归一化入口并不负责完整传感器预处理 | 不能取 node01 任意 80 行（80 个本通道 100Hz 样本首末仅 0.79s）就称为 TinyQuake 输入，也不能把六轴与 ENZ 混为一谈。 |
| 平台 motion `T=8,C=6` | `SHAPES['motion']=(8,6)`，8 个单传感器时间点，不是 8 秒/80 点/8 个传感器 | 若原始 100Hz，首末跨度约 70ms；若 1Hz 快照则约 7s，语义完全不同。形状相符不等于与训练频率/单位相符，B 未确认节拍前只存观测，不启用研究结论。 |
| 平台 soil `T=4,C=1` | 当前取 4 个 avg_pct/100 | raw soil 不是 avg_pct，更不是 VWC；本批缺标定，soil OM 应不收窗。 |

独立回读发现：7 场干净数据的 IMU 通道内读完成间隔中位数约 10.03–10.05ms，最大相邻间隔可达 22.537ms；三 soil 也非同时读出。它们支持“约 100Hz/2Hz 的工程采集”口径，不能用名义采样率抹掉时间差。

若另行评审 node01→TinyQuake 重采样：必须先分 TOP/TOE、确认坐标/朝向与量程标定、明确源时间抖动/缺测政策，再定义去趋势/高通等与模型匹配的预处理。**100→40Hz 下采样前须有明确的抗混叠低通**：目标 Nyquist 为 20Hz，需按所需通带、低于 20Hz 的过渡带和阻带衰减设计并验证，再做有理比 2/5 等适用重采样；不能隔点抽样或直接插值代替抗混叠。线上因果滤波要记录群延迟，离线非因果方法不可假装实时；滤波边界和长缺口不得跨越补造。

重采样会丢失高于目标通带的内容、削弱尖峰/改变相位或增加延迟，原始读完成时间也不等同传感器精密时钟。没有已验证的源带宽/抗混叠条件，不能承诺 40Hz 回放保留全部振动信息。保留原始 100Hz 通道及处理版本，TinyQuake 分类始终是独立 TEST_ONLY 参考，不进入 sensor_score/生产告警。

文件头的 factory_AAF / filter_not_calibrated 只是冻结寄存器配置声明，不是已经验证适用于 100→40Hz 的抗混叠滤波证据，也不能撤销源采样前已经发生的混叠。

研究成绩沿用既定历史口径：soil 最大绝对差 `1.03e-05`，在 `atol=5e-5` 下通过，略超默认 `1e-5`；motion 尺度相对误差 `3.2e-04`、相关性 `0.99999996` 通过。二者均研究模型、`deployment_ready=false / fusion_eligible=false`；数值对账不证明本批 node01 的模型适配或预警效果，本轮没有重跑这些成绩。

## 6. soil 原始值与标定前置

soil 行的有效载荷只在最后一列 soil_raw；三路由 channel 区分，错误行该列也为空。本批成功 raw 均在 ADS1115 有符号 16 位范围内，可保存原码；量程/PGA 和转换配置作为声明元数据保留。**原码不能改名为湿度百分比，不能仅按 ADC 满量程做 0–100 线性映射。**

标定前，平台只能存原始值并标 `uncalibrated`；top_pct/middle_pct/toe_pct/avg_pct/growth_pct_min 全 null，moisture 卡片显示未知，soil 推理不产窗。为便于核验若增加 raw 通道图，应标 raw code/未标定，不能让百分号 UI 自动套上。契约中的 pct 是相对湿润度指数，也不能未经土样证据称体积含水率；当前 avg_pct/100→VWC 的研究近似不适用于本批空标定数据。

前置材料由李青原采集、B 会签、何宇轩归档：三支探头与 ADS 通道/物理深度位置的对应；供电、PGA、接线、传感器型号与批次；与实际土样匹配的干/湿及中间点重复测量、稳定时间、温度/盐度/迟滞与不确定度；探头间一致性及异常/饱和/断线判定；版本化曲线、有效范围、日期与原始证据哈希。若要称 VWC，另需质量/体积或等效独立基准及密度等依据。均值/增长须定义多通道有效数、最大年龄、真实时间差及缺测规则，不能把长时间持有值当新采样计算增长。

降雨量标定是另一项：须有泵/喷头/供水条件、PWM→实测流量的重复标定、喷洒覆盖/空间均匀度、运行时间及体积/面积换算依据和误差，才能讨论实际降雨量/强度。它不由 soil 标定推出，当前一律只保留 PWM 条件。

## 7. 路径 A：离线 CSV 导入与回放

### 7.1 可立即开展的方案（本轮只设计）

原始数据交付已经核销；以下施工可从现有 9 场出发，无需上板、联网或重烧固件。但**本轮未实现或运行导入器**，当前完成的是第 2 节只读核验。

| 顺序 | 下一轮动作与产物 | 可检查结果 |
| --- | --- | --- |
| A1 | 从仓库外路径只读扫描，建立路径/大小/SHA/CRC/行数/完整 experiment_id 的导入清单；写入独立临时数据目录 | 与附录指纹一致才解析；任一 END 三项不等、元数据串场、EOF/字段形态异常则整场隔离。源文件保持只读，不扫描成待提交资产。 |
| A2 | 原始事件导入专用本地离线记录层，按 5 条通道重建时间轴和 validity/error；显示相对启动/场次时间 | 全部源行可追溯、无跨场拼接；重导同文件观测数不增加；合法 0 保留，空值保持空。原始层采用离线 DTO/表，不宣称是完整 NODE v2。 |
| A3 | 正向基线只选 N0000001/3/4/5/7/10/11，按降雨、对照、短场分别回放；不合并为同条件重复试验 | 197,182 行原始观测计数与通道计数对账；约束不是每路强行 100×时长，也不把 30 秒场拼成 180 秒。以 N0000001 为首个 180 秒回放，N0000003 为短场检查。 |
| A4 | N0000002/6 以显式 opt-in 负例回放，默认从正向集合剔除 | 报出 771/287 个错误记录；N6 soil 始终缺测。失败使通道失效，不前向填有效跨错误；不进入条件效果比较/训练集合。 |
| A5 | 输出回放审计：源行到通道/帧的映射、缺测/最大间隔、组帧复用数、隔离原因、处理版本 | 原始层 9 场总计 242,616 行可对账；正向/负向分区可追溯；无需运行 ACL 或板上平台。 |
| A6 | 若审阅选择完整 v2 投影，再实施第 3.2、4 节的身份/system 解阻与 1Hz 组帧，在隔离 DB 调用 validator→ingest | 全键/时间/null/范围合法；预期正向候选 960 帧，但缺观测状态的帧必须阻塞，不能为了达到该数伪造布尔。保留原始层，v2 不承担无损存储。 |
| A7 | 对完成的适配器做有意义的拒收/幂等验收 | 改写副本字节使 CRC 不符则拒收；重复导入不新增业务消息；同派生身份不同 payload 隔离；未知通道/回跳/缺测保持可见；TEST_ONLY 无生产告警/当前态污染。异常副本与审计只在临时目录，不改原件。 |

现有 `/ingest/test` 会改用 MOCK 语义；现有普通 REAL MQTT 会变 OPERATIONAL，均不能充当 A 的真实工程回放入口。建议首选**专用本地 CLI + 离线表/回放视图**，显式 REAL/TEST_ONLY；可调用已有纯校验/接收函数的部分能力，但不启动主应用和其 MQTT/demo/推理生命周期。若最终必须将候选帧写进现有 telemetry 表，只能在隔离 DB 且具备完整状态证据后执行；context 标签不会自动改变当前态、告警或推理逻辑。

### 7.2 改动、风险与工作量

| 归属 | 评估的后续改动 | 量级与风险 |
| --- | --- | --- |
| 平台侧 | 只读 CSV/sidecar 导入 CLI、离线事件 DTO/存储、5 通道回放与相对时间展示、指纹/幂等/隔离审计、REAL/TEST_ONLY 用途约束 | 原始归档/回放约 2–4 人日（含针对性验收）；不含完整 v2 状态缺口的取证等待。最大风险是把归档成功误当在线接入、时间/身份被洗白或污染生产当前态。 |
| 平台侧，可选 v2/研究阶段 | 完整帧映射、派生身份注册、状态缺失阻塞、用途/告警边界；双 IMU 窗口和结果通道区分 | 完整 v2 适配约另 2–4 人日；研究窗口改造约另 2–3 人日，可与路径 B 共用而非重复计费。采样节拍/训练单位未确认时只存储，不开放推理解释。 |
| 固件侧 | 纯离线归档不要求固件改动；李青原补身份、状态及安装/冻结资料 | 0 个固件代码变更是原始回放的可行前提；不是已解决在线固件验收。缺失的历史 boot/seq/状态无法仅靠新固件倒补。 |

以上是按静态范围估算的工程量，不是已执行耗时或交付承诺；标定、资料补交与硬件问题另计。路径 A 的原始归档可先于标定推进，完整 v2 与研究解释分别设门槛。

## 8. 路径 B：在线 MQTT v2 直连

### 8.1 可复用能力与仍缺的部分

只读抽查 `origin/李青原@ef13495` 的 `node_comm/telemetry.cpp`、`network.cpp`、`identity.cpp` 和冻结配置摘录：

- serializer 已有完整两 IMU/三 soil 结构，单位 m/s²、°/s，校准依赖量/UTC 默认 null，并按 30ms/1.5s 驱动存活界限取快照。存在 serializer 不等于本批已发 MQTT。
- Network 已有 NVS 配网、Topic 构造、TLS 校验、退避重连及 1Hz 诊断快照发送；Telemetry QoS=0、retained=false。它以本地 enqueue 计数，明确没有 durable queue/Atlas 持久化回执，edge_online 保持 false；不能据此清理 SD。
- DurableIdentity 已有 NVS boot 预留、提交后回读、seq 递增与安全整数边界；缺少已 provision 的计数器会阻塞，不自动初始化/清空 NVS。本批 boot_id=unavailable，不能推定这条代码在冻结采集中已工作。
- `config/sandbox-capture-v1.defaults` 明确 `CONFIG_NODE01_NETWORK_ENABLE` 未启用，且只是冻结设置摘录，不是完整可重现 sdkconfig。公开源码、固件本体和完整 freeze-manifest 的对应关系仍待核验。不能直接给当前冻结产物打开网络、继续沿用旧哈希身份或用“切分支重烧”代替评审。

### 8.2 时间与传输约定

1. 无可信 UTC 时在线也必须 `timestamp_ms=null / time_synced=false`，`uptime_ms=MCU当前单调微秒//1000`；网关/平台收到时刻只记 received_at。未来若增加同步，须定义可信来源、失锁行为和误差，时间校准不能使 uptime 回跳；不以 MQTT 连接成功代表 time_synced。
2. 原生 device/site 经全局注册；持久 boot 每次启动不同、seq 为统一原始消息序号，重试/补传不换身份。失败应阻止身份不可靠的消息，保留本地采集；不得清 NVS 作为联调快捷修复。
3. Topic 为 `zhifang/v2/{site_id}/{device_id}/telemetry`，与 payload 全等；保留完整键、null 和真实 system 观测。运行网络的新固件要有独立构建身份、配置与验收证据，不借用本批冻结产物身份。
4. MQTT v2 是低频快照，不持续发送两 IMU 全部 100Hz 行。契约 NORMAL 为 1Hz，WATCH 2Hz、WARNING/EMERGENCY 5Hz；当前未标定、risk=null 的工程流只评审诊断 1Hz，不假装已实现校准风险自适应频率。全速原始采样继续本地保留。
5. 本地 broker/连接器的 source=REAL 与 scope=TEST_ONLY 必须能同时成立。当前代码无法配置此组合，平台要先补入口策略及可追溯元数据；不得改成 MOCK 冒充，也不得凭 session.test_only=false 升级成 OPERATIONAL。
6. 明确 QoS0 可能丢快照、重连后序列缺口、队列溢出和背压行为；不承诺每条到达/持久化。平台 SQLite durable 与 broker 协议 ACK、云确认分别验收，`node_cleanup_authorized=false` 保持。本轮不要求为诊断直连补完云或清理 SD 回执协议，但必须承认其未实现。

### 8.3 改动、风险与工作量

| 归属 | 必需后续工作 | 量级/阻塞 |
| --- | --- | --- |
| 平台侧（何宇轩） | REAL/TEST_ONLY 连接器或受控诊断入口；生产告警资格判定、scope 持久化/查询；诊断设备隔离；完整 v2/Topic/幂等/旧 boot/故障接收验收；如启用研究推理则先做第 5 节改造 | 约 3–5 人日，双 IMU 研究窗口另计可共用。当前 source/scope 自动映射是诊断接入的明确阻塞；本轮不修改。 |
| 固件侧（李青原） | 从旧分支按最小模块选择性集成并解决 main 演进差异；独立网络诊断构建、凭据/身份受控 provision；校对 serializer、system 状态、发送节拍；在采集同时运行网络的调度/内存/SD/总线影响验收 | 约 3–5 人日的开发/主机验证，另加硬件验收与协调。已有网络代码可复用，不能承诺只改配置即可稳定。不得整支合并或覆盖原冻结构建。 |
| 联合验收（另获施工/硬件授权后） | 本地隔离 broker→平台 DB→页面，断连/重连、重启身份、重复/冲突、无 UTC、坏传感器/队列压力、TEST_ONLY 告警隔离 | 约 2–3 人日的实验量级；硬件根因未清、标定及证据补交等待另计，不含部署。未经负责人批准不碰现板。 |

B 的最小诊断闭环合计约 8–13 人日（不含可共用的研究窗口、标定、硬件根因修复和部署等待）。主要风险是网络并发打破原采集稳定性、身份 provision 失误、TEST_ONLY 被误归生产、历史/当前混淆、以及误把通信成功写成设备/标定/模型验收成功。A 能先降低字段与时间理解风险，不能替代 B 的在线负载和真机验收。

## 9. 数据交付核销清单

| 项目 | 本轮状态/证据 | 用途与剩余动作/责任人 |
| --- | --- | --- |
| 9 场 BEG/CSV/END（27 文件） | **已交付、全部独立回读一致**；第 2 节/附录 | 离线回放、字节/CRC/行数/通道审计。两场问题场保留并隔离，不以文件完整核销传感器质量。 |
| session.json（9 文件） | **已交付并解析/指纹登记**，7 SUCCEEDED、2 FAILED | 关联场次/主机观察/终结结果；不改历史 NOT_OBSERVED、HOST_FILES_NOT_VERIFIED。 |
| events.jsonl、device.txt、serial.bin（27 文件） | **已交付，全部大小/SHA 与 session 记录一致**；events 全部可解析 | 对照控制/设备终结/错误与主机观察；不是逐行 UTC，也不是固件二进制。李青原保留完整原件。 |
| 现场图片（4 JPG） | **已交付、查看、大小/哈希登记**；均为秒表截图 | 配合根数据说明理解降雨开始/结束记录；没有安装或位移影像证据，不能替代接线/安装说明。 |
| 数据说明（根 DOC、子目录 DOC/DOCX，共 3 文件） | **已交付、只读提取文字、指纹登记** | 根文件解释两次计时；子文件的操作者解释仅作备注，不追认为已验证滑移/强度标签。 |
| freeze-manifest.json / 完整冻结关联清单 | **仍缺，本批目录未见** | 李青原补产物/源码快照/完整构建配置/工具版本/测试档案及哈希关系；何宇轩核验。用于重现与身份核销，不能拿本评估附录的“交付文件指纹”冒充冻结 manifest。 |
| 固件 bin 本体（以及可回读 ELF） | **仍缺；目前只有哈希声明** | 李青原提供原冻结二进制，在仓库外交接；分支文档称 bin 为 386,256 字节、SHA-256 `2be566f0195877656610ae2ebf17437ae41fdae280457f7b914e4dd64fadd422`，ELF 为 6,160,688 字节、上述 288e…身份。未见本体，不能标本轮独立匹配或复现构建。 |
| 成文接线/供电/安装说明 | **仍缺** | 李青原补实际引脚/地址/供电/地线/泵隔离/线长、IMU TOP/TOE 固定与朝向、soil 三位置/深度、安装照片、变更和传感器批次；何宇轩审阅。分支列出的引脚与秒表截图不够证明本批实际装配。 |
| soil 标定 | **仍缺** | 李青原提供本批探头/土样原始标定，B 定义并会签映射、误差/缺测/窗口；此前 raw only、uncalibrated。 |
| PWM/流量/降雨量标定关系 | **仍缺** | 李青原提供泵/喷头配置、独立体积/流量/面积与时长证据，B 会签关系；何宇轩保存版本。本批条件不换算任何降雨量数值。 |
| 逐行 UTC、正式 site/boot/seq、可对时的系统状态 | **本批缺失，离线只能诚实保留未知** | 李青原/何宇轩分别负责原生身份和注册、时间/状态机制；不要求回填不可能恢复的历史事实。原始回放不受其阻塞，完整 v2/在线验收必须按第 3、4、8 节解决。 |

## 10. 进入施工的准入标准

以下是供何宇轩评审的条件，**不构成本轮开工或上板授权**。

1. **范围会签。** 何宇轩明确下一轮选 A 原始离线归档、A 完整 v2 投影或 B 在线诊断，并批准相应设计；李青原确认通道/设备/条件释义，B 确认涉及的对齐/特征/模型边界。不得把批准评估解释为批准代码、固件或部署。
2. **原件和分区锁定。** 使用附录指纹的仓库外只读原件，7 场正向与 2 场故障分区固定；审计/派生 DB/缓存均在 git 外。任何变更都重新核验，不以旧 CRC/SHA 代表新文件。
3. **身份、时间和用途可检查。** 离线派生身份须持久可重放并显式标注；在线须正式注册与 boot/seq 机制。UTC 缺失就保持 null/false，接收时间与相对采样轴分开；REAL/TEST_ONLY 不污染生产设备/当前态/告警。完整 v2 中未知 system 不得补造布尔。
4. **选择合适接收边界。** A 原始归档可使用独立离线记录格式保留未知，不要求补造已经缺失的历史状态；选择完整 v2 的 A 或 B 时，必须有所有必需字段的真实/明确派生依据，并先完成 validator、幂等、隔离与坏输入验收。当前 HTTP MOCK 测试口、普通 REAL MQTT 自动 OPERATIONAL 不能直接替代。
5. **模型挂接单独准入。** 原始归档默认不调用 observe/ACL。任一路径启用真实数据研究推理前，TOP/TOE 独立窗口、采样节拍/单位/缺口政策、结果通道/time_basis 已实现并验收；soil 未标定不启用。重采样前完成抗混叠和信息损失评审。研究输出固定不参与融合，MOCK/TEST_ONLY 无生产告警。
6. **冻结与硬件证据分阶段核销。** 缺 freeze-manifest/bin 不妨碍 A 的只读原始归档，但阻止声称冻结构建可复现、原生身份已验收或直接开始 B 硬件联调。B 进入固件/硬件施工前，李青原交齐冻结关联/固件本体/成文接线安装，列明两问题场的风险处置及独立新构建方案。若只做 A 导入器，缺标定字段保留未知，不等资料齐全才承认已交付原始数据。
7. **验收与上线分离。** 后续若改平台代码按仓库要求跑全量 pytest 与前端 build，增加必要的通道、身份、时间、用途隔离回归；ACL/硬件改动另报真实环境结果，未运行就写未验证。先用隔离本地目录/DB/broker，不改现板、不恢复演示源、不删改历史记录。部署/烧录/板上服务变更需何宇轩另外决定。

## 11. 本轮完成项与停止点

- 完成 9 场独立原件核验、70 文件元数据清点、27 个会话证据文件对账、图片与数据说明检查、共享契约及平台/候选固件静态对照。
- 仅文档变更；没有运行 pytest、前端 build、导入回放、MQTT、NPU 自检或硬件实验，不借用历史 `155 passed` 等成绩宣称本轮测试通过。本文所有方案预期数都不是执行成绩。
- GitHub 连接器的批量 tree 写入与逐文件创建均返回 `MCP tool call requires approval, but approval policy is never`，没有文档写入成功。已回读远端同名分支仍在 `7f3ac3c`。未创建 PR，不将“本地文档完成”写成“远端交付完成”。
- 原仓库 `.git` 只读；在仓库外 `/private/tmp/node01-assessment/checkout/` 从 main 建立独立评估分支，准备仅两文档的本地提交、补丁和 PR 描述，供恢复连接器交付后审阅。原件仍在数据目录，未进入该独立 checkout。
- 停在本地文档交付准备与审阅边界；连接器可写后仍只交付文档 PR。未经何宇轩下一轮施工决定，不开始 A/B 任一路径，不合并或删除分支。

## 附录 A：仓库外场次目录与文件指纹

根目录缩写 `R=~/Desktop/ICT-2026/数据/相同降雨量/`。表内目录均相对 R；指纹表的“目录代号 + 文件名”可还原完整路径。SHA-256 均由本轮直接读取实物计算；这只是交付文件清单，不是缺失的 freeze-manifest。

| 目录代号 | 场次 | 相对 R 的目录 |
| --- | --- | --- |
| S1 | N0000001 | `50 pwm挡位` |
| S2 | N0000002 | `70 pwm挡位/1（I2C错误）` |
| S3 | N0000003 | `70 pwm挡位/1（I2C错误）/出错后30s沙盘外不下雨测试` |
| S4 | N0000004 | `70 pwm挡位/1（I2C错误）/出错后180s沙盘外不下雨测试` |
| S5 | N0000005 | `70 pwm挡位/1（I2C错误）/出错后180s沙盘内不下雨测试` |
| S6 | N0000006 | `70 pwm挡位/1（I2C错误）/出错后180s沙盘内不下雨测试（但启动水泵）` |
| S7 | N0000007 | `70 pwm挡位/1（I2C错误）/出错后180s沙盘内不下雨测试（但启动水泵）/30秒测试传感器的安全` |
| S10 | N0000010 | `70 pwm挡位/2` |
| S11 | N0000011 | `100 pwm挡位` |

| 目录代号 | 文件名 | 字节数 | SHA-256 |
| --- | --- | ---: | --- |
| R | `数据说明.doc` | 10,240 | `b0afc13855d9aa55e2bebff5f04c66c7e0a25eee03091fb51499dae87427f5ce` |
| S1 | `0668107885dbd5d297e54fb8e844c795.jpg` | 84,713 | `e40e6e3258957ce0e523eac0d9b1eddd572ad6c48246c6f76f2243ad6ad5098f` |
| S1 | `N0000001.BEG` | 930 | `0185d05d7632165b0f108180f75bc57a3b96e3427c830abd3a4e9ead5f9d800c` |
| S1 | `N0000001.CSV` | 5,152,085 | `886b48185a4a68d05e0a6bcb49b2fcfc8a727dfa347cf573333e76734bbe67b6` |
| S1 | `N0000001.END` | 996 | `20169efbbf211a99859930d0ccd279b287f81663448fac434e2b4dc099cb3822` |
| S1 | `device.txt` | 330,727 | `c4af9a6594963283c61d33c0e03c05794baededf071e1a696cb24f802edfff9b` |
| S1 | `events.jsonl` | 4,756,921 | `2a8f9945711f01d3f303ef21c9b5bed767c8ee3d24004d1c71c1c5996ecd1952` |
| S1 | `serial.bin` | 330,727 | `c4af9a6594963283c61d33c0e03c05794baededf071e1a696cb24f802edfff9b` |
| S1 | `session.json` | 5,097 | `ac69d1e9c5b051dbb923874bf66cf1caf395ea99ca1b09055d7206121f075903` |
| S10 | `N0000010.BEG` | 930 | `aeedf97732daea2ac0c846252f60479f2a7e2993640c41fec28346f00a6a3c06` |
| S10 | `N0000010.CSV` | 5,020,416 | `b5770a4466194981558e229b5dd7235b6830dcdaf96392a6505b5953d2ff7790` |
| S10 | `N0000010.END` | 996 | `fbb936ad1325820df16bed7e0d0da9884bdae48e3b0051b81173fe33444fb5f3` |
| S10 | `b05434328e5daef366195f3e13679b58.jpg` | 227,829 | `6a5df31ed45a554726967536b693bbcbb692c8e4c2e92567542669a2bc67086d` |
| S10 | `device.txt` | 255,574 | `e3d6ae3b8e7b33b1ef284f5b1252b576f74cb5b8e6feb75d7be707ee11586998` |
| S10 | `events.jsonl` | 3,648,189 | `f9feeb00f1f1def323c19d7ef133144d7197039470476dbc165ed98f079c2d27` |
| S10 | `serial.bin` | 255,574 | `e3d6ae3b8e7b33b1ef284f5b1252b576f74cb5b8e6feb75d7be707ee11586998` |
| S10 | `session.json` | 5,097 | `de44557d473be6b8e9828f280f3654ba9623c506d68a38727553c6d3ffac6406` |
| S10 | `数据说明.doc` | 10,240 | `5b58c1138769241bfa01406d843b017533215c38ccb0d57434719ad72d6b6677` |
| S11 | `8ea9a07ee6c07f94fa9998a7122d8f01.jpg` | 237,226 | `ddc3ccf9c3c495a0bd870086261b0eab9d7b51d15afdef060bbacd5f6f78c637` |
| S11 | `N0000011.BEG` | 930 | `a10b7d777e8ae16a73636dbfd7cf8d767cc38229d82e923f0879ee49f745ee50` |
| S11 | `N0000011.CSV` | 5,069,739 | `e37bca8df80f7328977e2d0cdae2bc63358f4a41b1aca988df73885441d4214e` |
| S11 | `N0000011.END` | 996 | `641c670418740ba1e4132fd0c9a35c98773a6906cad7c9f2b4ab548d1e42dc50` |
| S11 | `device.txt` | 238,845 | `82327100051c46d0081c63de511b7a324a1bca1a1a63674b61f8fcbd86afba88` |
| S11 | `events.jsonl` | 3,406,887 | `006ab1371de808cb8dc54fc933761382f3f5897c51991dcadf3c1ec0b16b9cf8` |
| S11 | `serial.bin` | 238,845 | `82327100051c46d0081c63de511b7a324a1bca1a1a63674b61f8fcbd86afba88` |
| S11 | `session.json` | 5,130 | `b09736f8a822bfc4710ed0a218883899289051a08b58a54791beb24367df6538` |
| S11 | `数据说明.docx` | 10,586 | `b9fc0f20493cb8493f8b013d67414be5a2c275d94d026aa23d0dfb5f29e75120` |
| S2 | `N0000002.BEG` | 930 | `1cd34b288fc64c887682303ff7f5bb27a6b16951dbaf40b77ea7489d55e473f0` |
| S2 | `N0000002.CSV` | 4,972,721 | `d54c00fda2788361d87f2c5975a5017b8ce5597e58288a4200b9ca4c4fe005fb` |
| S2 | `N0000002.END` | 1,003 | `f255c3e9547b984410268b6c60789283fc573a75f5383d0c366e242e9b1fffa1` |
| S2 | `c435276d01377be6a2d31dd5ef961e35.jpg` | 85,962 | `312cc80ac106dbe17d10a1b6ae8be0d9283fca075e8c5a28b9959c7dcb1779ed` |
| S2 | `device.txt` | 378,869 | `5ab983c4b53e1842d9e21031b167245602e50a2af54dfa4a3f7636aeeebd431c` |
| S2 | `events.jsonl` | 5,561,422 | `6b4013fae69f56df9aca95e7f36b1d4c6e46026c714a00e989b6d37147fab48f` |
| S2 | `serial.bin` | 378,869 | `5ab983c4b53e1842d9e21031b167245602e50a2af54dfa4a3f7636aeeebd431c` |
| S2 | `session.json` | 6,179 | `5eca0fe5e329760c672d44c27eb39d4f300950df00a29a6384621909a14e8014` |
| S3 | `N0000003.BEG` | 929 | `295f1138cb92befe7bd7a9b3a6d53d4ffda16797a4327df7e60b5bcd79bca765` |
| S3 | `N0000003.CSV` | 820,851 | `1cb0776952021bddaa457d8896ef1c2f25eaaa06bb138805ba8ce63217c83934` |
| S3 | `N0000003.END` | 983 | `3888f16b8a4d31e317e92c361cb322090d9a5719f2f883d478c1e11a6c45d25c` |
| S3 | `device.txt` | 151,765 | `11c9274edd62bfb67d183eff06a762ffe53b48ae56733d0b5330be7ad7201156` |
| S3 | `events.jsonl` | 2,216,235 | `528d30f8cb5710e9e03c8189ce55a970003e3d8cfaf39b3b37b5b244db4316aa` |
| S3 | `serial.bin` | 151,765 | `11c9274edd62bfb67d183eff06a762ffe53b48ae56733d0b5330be7ad7201156` |
| S3 | `session.json` | 5,089 | `3bffed9d50b96b8760f3b68b81351d48055e34aae6822eb625de53df3b376488` |
| S4 | `N0000004.BEG` | 930 | `dbedb5d9ffabf6de22324f1a994696dcdec3c3b7039535dd5a0168ef969c0e45` |
| S4 | `N0000004.CSV` | 5,026,570 | `9f0fb35db5fd90fc5a11b8e00cc960be03f0f1197b5e2cdb505bb0a1460ca1d7` |
| S4 | `N0000004.END` | 996 | `e701f1d37731663f654239ecbdd2a65c8ef1b7f7dd5d2015ffcaa04131f9bd39` |
| S4 | `device.txt` | 243,469 | `f658cd13e34836eadb68804481b50ed58cf50e274c4844df45a663fa3b844760` |
| S4 | `events.jsonl` | 3,575,676 | `30efbb399f105a6009bc46f6e02e14325ade56614894357c3de922e4a0891f68` |
| S4 | `serial.bin` | 243,469 | `f658cd13e34836eadb68804481b50ed58cf50e274c4844df45a663fa3b844760` |
| S4 | `session.json` | 5,097 | `a1c7101265723dbb5e6412f2454243a2118e02ba6b315a9c6871c325ca2ad49f` |
| S5 | `N0000005.BEG` | 930 | `30aaf6a1e3403ed415f5939108feb1c8058a8a119700ff115f12ea08132f9901` |
| S5 | `N0000005.CSV` | 5,061,847 | `d6c7594a91687cda117a4b010e4e3d1513de48aa6420b49a1af62746154c8950` |
| S5 | `N0000005.END` | 996 | `de3dee09da28a8fe391eea1753cfff34c7c79d9fa73ecb45682da68397c71f81` |
| S5 | `device.txt` | 183,700 | `4bc6f5b95c0096870df1dae821d32cbf1b9def801451cdb265ee8eb6ca97b964` |
| S5 | `events.jsonl` | 2,642,690 | `410a66ee4a4c09e13812c1f0d010b96afc2a416340a20370a7f00abcf54c20e3` |
| S5 | `serial.bin` | 183,700 | `4bc6f5b95c0096870df1dae821d32cbf1b9def801451cdb265ee8eb6ca97b964` |
| S5 | `session.json` | 5,130 | `ff0e7d9326cabca03c610655111fa2f8c576e28c1a78e9ea20c998d449bc8519` |
| S6 | `N0000006.BEG` | 930 | `e3c19b5124d7419a5107c6eb4763e94ba4eee391f69d27b06b2f795e197d25f0` |
| S6 | `N0000006.CSV` | 1,303,757 | `0a386e06db734a1e0227470164e62ef53b7d33c9ceab6f0cc20ec8f1207ada9c` |
| S6 | `N0000006.END` | 984 | `3e55ec3e6f41e4aa25975fc8f89e6d6fc6afb31bd16892b9c8909a61662e7d9b` |
| S6 | `device.txt` | 81,131 | `8b47fe4a9e94dabee6af41d61af4c53b0697e72515395e60754853a10b649669` |
| S6 | `events.jsonl` | 1,188,008 | `d79e836d5a86395f6de808aee4564028cd038ac2411d3c5550f29789e39e064f` |
| S6 | `serial.bin` | 81,131 | `8b47fe4a9e94dabee6af41d61af4c53b0697e72515395e60754853a10b649669` |
| S6 | `session.json` | 6,429 | `f7ba68a44d814fb48064843ca99c8cc619186e7fd28383ff7a2780ab198ad637` |
| S7 | `N0000007.BEG` | 929 | `c58a6450a220af4cbb372fb5afccbce75ac66c7e4c79b6b80fba12200b6a35a6` |
| S7 | `N0000007.CSV` | 848,959 | `7d52d4d30c7b88e80ce3cbbb0926be20b506fcac0d7fd4029c04948a57c3ce14` |
| S7 | `N0000007.END` | 984 | `6b87f30db876349b8ca11fa00b478bd7daf68328d63a5dcfcde4df3118da5713` |
| S7 | `device.txt` | 165,933 | `9d5d69d0e9acbde1818e536b33c994fa6bfb672436e6d82f340851a261c19868` |
| S7 | `events.jsonl` | 2,381,015 | `fcbbad59a596527e381b6a79a4d2651399a6bead50accac14ecf6ef170358b29` |
| S7 | `serial.bin` | 165,933 | `9d5d69d0e9acbde1818e536b33c994fa6bfb672436e6d82f340851a261c19868` |
| S7 | `session.json` | 5,090 | `d72aa4194d1b66507f9d43f36041f23101f2551468447f354a3821a66fdc177d` |

## 附录 B：静态参考位置

- [共享契约](../../00_TEAM_SHARED_CONTRACT.pdf)：第 5 节采样/低频快照，第 6 节完整 NODE 字段，第 7 节身份/确认，第 8 节 MQTT，第 11 节正式实验 CSV/标定和对齐。
- [平台 v2 校验与持久接收](../../platform_backend/src/geohazard_platform/telemetry.py)、[数据库](../../platform_backend/src/geohazard_platform/database.py)、[MQTT 接收](../../platform_backend/src/geohazard_platform/connectors.py)、[应用挂接](../../platform_backend/src/geohazard_platform/main.py)、[时间和页面投影](../../platform_backend/src/geohazard_platform/dashboard.py)、[研究推理](../../platform_backend/src/geohazard_platform/inference.py)。
- [Edge Intake 边界](../protocols/telemetry_v2_edge_intake.md)、[ACL 研究适配设计](atlas-acl-integration-design.md)、[TinyQuake 输入边界](../../firmware/tinyquake_esp32s3/README.md)。现有文档的历史状态不覆盖本次核验事实。
- 候选固件只读来源为本地 `origin/李青原@ef13495b64c23d0982e3fc2698438bf0f1d4ecde`：`docs/NODE01_SANDBOX_CAPTURE_V1.md`、`firmware/node01/components/node_drivers/include/node/acquisition.hpp`、`node_drivers/sensors.cpp`、`node_storage/diagnostic_log.cpp`、`node_comm/{telemetry,network,identity}.cpp`、`config/sandbox-capture-v1.defaults`。该 ref 仅作阅读定位，没有 checkout、合并、编译或烧录。
