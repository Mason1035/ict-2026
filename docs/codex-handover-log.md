# Codex 工程交接日志

本日志按工作段追加，区分负责人交接事实、历史记录、静态阅读结果和本轮执行结果。日志不替代 `00_TEAM_SHARED_CONTRACT`，不更改冻结契约。合并、删除、上线及板上服务变更由何宇轩决定。

## 2026-11-02 — 首次接手对齐，等待负责人确认施工方向

### 本轮做了什么、改了哪些文件

- 日期：2026-11-02，Asia/Taipei。
- 仓库：`Mason1035/ict-2026`；本地路径：`~/Desktop/ICT-2026/ict-2026`。
- 接手时本地 `main` / `origin/main` 均指向 `e8ebbe1cb1139005840d465e7996950f47a21ad8`，工作区干净；这是本地 Git 读取结果，未据此声称重新验证远端或板上状态。
- 本轮交付分支：`codex/handover-2026-11-02`，基于上述提交；只新增本文件 `docs/codex-handover-log.md`，供文档 PR 审阅。
- 阅读指定资料，并只读抽查 node01 分支说明、接口实现和平台接收/推理/告警边界。未改平台、前端、固件、模型或正式资料，未访问板子或队友电脑，未运行服务、桥接、隧道、演示源或部署命令。

### 阅读范围与资料缺口

已通读：

- 仓库根目录 `README.md` 和无扩展名的 `README`。
- `docs/decisions/README.md`、`docs/decisions/atlas-acl-integration-design.md`。
- 补充资料 `environment-lock-2026-10-20.md`、`model-selection-shortlist-2026-10-23.md`。
- 补充资料 `零自采数据模型研究/report.md` 和 `sources.md`。

补充阅读：`docs/README.md`、`platform_backend/README.md`、`ai_training/MULTIMODAL.md`、`docs/protocols/telemetry_v2_edge_intake.md`，以及本地 `origin/李青原` 中的 `docs/NODE01_SANDBOX_CAPTURE_V1.md` 和相关序列化实现。

交接指令提到 `docs/decisions/` 有三份文档；本地目录及该基线 Git 跟踪清单实际只有上述两份（含索引）。第三份的文件名/位置待负责人补充。本轮不假称已经读到，也不自行新造第三份决策文档。

### 对当前状态的理解

以下运行状态及历史实测成绩承接负责人本次交接，不重复登板核验：

- 平台由 FastAPI `platform_backend` 与 Vue `apps/geohazard-demo` 构成。Atlas 200I DK A2 / Ascend 310B4 / CANN 7.0.RC1 是边缘站；`geohazard-platform.service` 在板上运行，仅监听 `127.0.0.1:8000`。PR #9 已合并，ONNX→ATC→OM→pyACL→平台运行时已经真机跑通。
- `atlas_acl=connected` 仅以真实 NPU 推理成功为依据；IoTDA 仍为 `not_connected`，等待负责人云账号。NPU 与云连接是两项独立状态。
- 板上演示遥测已暂停，历史 MOCK 遥测冻结为 57,903 条并保留。本轮没有查询/更改板上数据库；未经何宇轩明确决定，不恢复演示流、不删除数据、不重启或改动板上服务。
- TinyQuake 的 ESP32→队友电脑 USB 桥接→SSH 双向隧道→板平台链路在 2026-10-22 已跑通，743 条全接受落盘。连接器 `reconnecting` 可表示正常待机；复现由负责人转达队友切 `main` 后重跑桥接与隧道，ESP32 固件不重烧。
- `origin/李青原`（交接给定 `ef13495`）为双 IMU、三路土壤及 SD CSV 的未标定沙盘采集候选，基于旧点、落后 main 27 个提交且未开 PR。已有 30/120/300 秒实板记录；300 秒为 61,631 行、零丢包。该成绩属于采集证据，不等于集成或校准验收。分支说明保留 `UNCALIBRATED / INTEGRATION_NOT_READY`；原始 CSV 与完整冻结档案不随仓库交付。
- 项目当前零自采数据的研发/训练交接口径保持不变：队友本地已有原始工程采集记录，不等于项目已获得可用于正式训练的自采数据交付。
- soil / motion 均为研究模型，`deployment_ready=false`。soil 板端最大绝对差 `1.03e-05`，略超默认 `≤1e-5`，在 `atol=5e-5` 下通过；motion 按尺度相对误差 `3.2e-04` 与相关性 `0.99999996` 通过，不能宣称两者全部指标均 `≤1e-5`。
- 未标定输出仅作事件分类、异常分或参考指标；不得生成、展示或写入“滑坡概率 %”。TinyQuake softmax 不得进入 `sensor_score`，MOCK / TEST_ONLY 不得形成生产告警。视觉暂缓，后续仍为普通 USB 摄像头＋OpenCV 基线，不引入 ToF；ClassHub 与本项目无关且不在工作范围。

### 发现的问题和风险

1. **资料时点容易误导接手。** 根 README、平台 README 的部分段落仍写真板联调待执行；2026-10-20 环境锁保留当时的 `atlas_acl=not_connected`；ACL 设计仍标“待评审”，其中演示流、重启、故障注入等是历史验收方案。它们不能覆盖本次交接的新事实，也不授权现在执行旧验收步骤。建议后续单独补当前状态入口和历史时点说明，保留原实测记录；本轮只在日志登记。

2. **node01 的采集产物不能直接当作平台消息或训练集。** 分支说明为 22 列、按传感器记录的原始 CSV；主 README 的实验 CSV 契约及平台完整 `zhifang.telemetry.v2` 是不同边界。node01 声明 IMU ODR 100Hz，TinyQuake 波形规格为 40Hz / 80 点；需要分别定义通道、时间、窗口及抗混叠重采样，不能混用。节点无可信 UTC 时保持 `timestamp_ms=null / time_synced=false`，ADC raw 不能改名湿度百分比，风险字段继续未知。即使存在 v2 serializer，也不证明沙盘模式已实际完成 MQTT→平台集成。

3. **模型输入适配存在需要先澄清的边界。** 当前 `inference.py:182` 按 site/device 建缓冲，`:193` 使用 `avg_pct/100`，`:195` 将消息中两个 valid IMU 的六轴样本依次送入同一 motion 缓冲。静态结果说明，真实 node01 接入前需明确按传感器区分时间序列，避免把 top/toe 两个空间位置当作同一传感器的连续观测；缺土壤标定时也不能为了产出 soil 预测而填造 `avg_pct`。这不否定现有 NPU 流水线和研究自检已通过，只限制对真实观测的解释。

4. **普通 v2 告警的用途隔离需要评估补强。** `telemetry.py:214` 的风险升级写入条件没有检查 `source/scope`；`database.py:92` 的 `alarms` 表保存 `source`，没有保存 `scope`；`main.py:289` 的告警查询支持 source 筛选，未提供 scope 筛选。已有 `test_ingestion.py:85` 也在默认 MOCK / TEST_ONLY 输入下预期生成告警记录。演示告警保留来源并不自动证明它会形成生产告警，但不能仅凭这些边界宣称 TEST_ONLY 已在生产入口完整隔离。尤其 REAL / TEST_ONLY 仍需保留用途区分。此为静态风险登记，本轮未做运行复现，未声称板上发生生产告警事故，也未改变任何历史告警或数据。TinyQuake 仍是独立实验路径，不据此混同两种接收链。

5. **模型效果与数据证据仍有限。** 短名单记录 soil 仅略优于 persistence，motion 没有独立 Validation/Test；NPU 数值对账不证明预警效果。node01 300 秒报告还保留一次 deadline miss、SD 写入长尾及未做突然断电验收等限制；零丢包不能外推为长期可靠或掉电安全。本轮未取得队友本地原始文件，未独立重算其哈希或采集指标。

6. **选型结论已收敛，转换可行性仍有各自门槛。** 按已提供研究，不存在能直接匹配两路输入的可下载预训练模型。可行工作限定为 GPD 类架构用 STEAD 等公开数据按 40Hz / 80 点重训、USGS 公开边坡数据训练时序异常检测、或 TSPulse / TTM 类小模型做异常/预测。研究报告自身保留部分许可、数据获取、上下文长度与 ATC 算子验证缺口；这些不因列入短名单而自动关闭。本轮未重新联网选型或下载模型，也未将资料中的 ATC 风险判断写成实测通过。

### 建议下一步排序（建议，尚未获施工确认）

1. **先做 node01 集成可行性评估与接口对齐。** 产出一份基于 main 的字段/单位/时间/身份/validity/来源用途对照和集成拆分方案，区分离线 CSV 导入与在线 v2，不整支直接合并。由负责人协调李青原交付至少一场原始 BEG/CSV/END、冻结 manifest、固件身份和安装/校准说明；先只核对工程采集，不将其升级为正式训练数据。验收是明确哪些字段可原样接收、哪些必须 null、哪些阻塞及由谁补齐。本步骤不需要动板或重烧固件。

2. **在真实数据联调前做平台边界维护。** 先确认演示告警与生产告警的判定/查询边界，再小步补 source/scope 的约束与有意义的回归，并评估双 IMU 研究窗口的分离方案；同步修正文档当前状态入口。不得删除或重标历史 MOCK 数据，不改既有风险权重或编造校准值。若改平台代码，必须全量 pytest＋前端 build；涉及 ACL 的改动另列真机方法和结果，未真机验收就标“未验证”，部署另等负责人决定。

3. **模型路线先选 GPD 类 40Hz / 80 点公开数据重训作为单一离线实验。** 理由是输入与已验证 TinyQuake 参考链最接近，可保留其既有参考窗口成绩作为独立对照。先写数据许可/来源、抗混叠预处理、P/S/Noise 标签和按事件/台站分组避免泄漏的切分方案，之后才训练并评估。训练未优于基线也如实记录；输出始终是事件分类参考，不进 `sensor_score`，不宣称滑坡预警有效。公开地震台站到坡面 MEMS 的域差继续保留。离线训练、ONNX 对账和板端 ATC/ACL 各自验收，不能跨阶段宣称通过。这里是推荐方向，不是本轮启动训练或安排上板。

   USGS 异常检测与 TSPulse/TTM 作为另外两条可选路线保留，待负责人取舍；前者需先处理分钟级公开采样与本项目秒级观测的差异，后者需满足真实上下文长度，不用补零/插值伪造历史。本轮不并行启动多条模型线。IoTDA 等云账号，视觉继续暂缓。

### 测试结果、未决问题与停止点

- **本轮测试：** 文档变更，不运行 pytest、前端 build、NPU 自检或硬件联调；未安装/升级依赖。负责人给定的本地基线是全量 pytest `155 passed`、前端 build 通过，属于接手基线，不是本轮重跑成绩。
- **本轮检查：** 本地 Git 基线、指定资料清单及上述代码行号已核对；`git diff --cached --check` 通过，暂存变更清单仅含本文件。平台与固件没有改动。
- **交付过程：** 本机原生 `git push` 因缺少 HTTPS 凭据失败；已通过 GitHub 连接器创建同名远端分支，文档提交/PR 沿用连接器交付。未改凭据、全局 Git 配置或系统环境。
- **待负责人决定：** 是否接受上述排序；首先批准 node01 评估，还是先处理平台用途隔离，或优先 GPD 离线实验。方向确认前不施工。
- **资料阻塞：** 第三份决策文档未定位；node01 原始采集与完整 manifest 尚未交接；正式数据、土壤标定及 B 正式科学契约仍有缺口；IoTDA 等负责人账号。GPD 实验的数据许可/资源预算及评估设计需要在实施方案中明确。
- **权限与协作：** 合并/删分支/上线/板上服务变更留给何宇轩；联调步骤写给负责人转达，不直接改板子、队友电脑或负责人 Mac 的运行环境。Muse 可依据会话和仓库状态复核本记录。
- **停止点：** 本轮只交付交接日志的独立分支/文档 PR；写完并完成文档检查后停止，等待何宇轩确认方向。

## 2026-11-02 — node01 集成评估，实物数据已交付并独立核验

### 范围与交付

- 何宇轩已确认本轮方向为 node01 集成评估；更新版任务书取代“数据未交付”的前提，但仍只允许评估文档，不授权代码、固件、硬件或板上施工。
- 基线为 PR #10 合并后的 `main@7f3ac3c38261e058062b5227684f16a566e15a9a`；本地工作区开始时干净，远端 main 已通过 GitHub 连接器回读确认。
- 交付分支 `codex/node01-integration-assessment` 已存在且头部正是上述 main，未发现额外评估提交，沿用该分支。新增 [node01 集成可行性评估与接口对齐](decisions/node01-integration-assessment-2026-11-02.md)，本文件只追加本段；交付范围仅这两个 Markdown 文件。
- 本地 `.git` 为只读，`git switch` 创建 index.lock 被系统拒绝，因此原仓库 Git 分支仍为 main；未修改其 Git 元数据或全局配置。为准备可审阅提交，另在仓库外 `/private/tmp/node01-assessment/checkout/` 从本地 main 独立克隆并建立评估分支；原工作区保留文档副本。

### 实物核验与口径更新

- 原件位于仓库外 `~/Desktop/ICT-2026/数据/相同降雨量/`。本轮全部只读核对，共 70 文件、67,446,450 字节；没有把原件、原始行、串口内容、照片或其副本放入仓库或交付树，评估附录仅保留路径、文件名、大小与完整 SHA-256。
- 9 场完整 BEG/CSV/END 均独立重算 CSV 全字节长度、CRC32、数据行数，与 END 三项全等；22 列长表结构、逐通道有效计数、错误行数、索引连续性和单调采样时间也已核对。全部 242,616 行；7 场正向回放候选 197,182 行，两场故障记录单列保留。27 个 serial/device/events 文件的长度和 SHA 与 session 记录全等，events 全部可解析；不改 session 既有 HOST_FILES_NOT_VERIFIED。
- N0000002：70 PWM 第 1 次，I2C=527、sensor=771、soil 有效 166/145/143；N0000006：USER_STOP 于 46.157879s，I2C=72、sensor=287、soil 有效 0/0/0。两份 session 均 FAILED，不能与 7 场干净记录混为正向基线。水泵条件只提供相关性线索，未有开关时序/供电/总线/重复对照证据，不下因果结论。
- 9 场文件的 ELF 声明一致为 `288e76253c36efcc1939959443c2ae58c245eb2ea0f7ba667e950d9d2372119d`，与李青原分支说明相同；session 的 firmware_identity 均 NOT_OBSERVED，固件本体/冻结 manifest 未交付，不能标为本轮独立固件身份验收通过。
- 4 张 JPG 已查看，均是秒表截图；3 份数据说明已只读提取并登记指纹。截图不等于接线/安装/位移证据，操作者对盒体移动和初始土壤差异的备注不生成 SLIP 真值。
- 旧日志中的“原始数据未取得/未交接”保留历史时点，本段明确核销本次已交付项。本批仍是 REAL_SENSOR 工程诊断，not experiment CSV / not training data、未标定、UTC 缺失；不升级为正式实验/训练/标定数据，不将 PWM 换算降雨量。

### 静态评估结论与资料缺口

- 已只读对照共享契约相关完整页、main 的 validator/持久接收/MQTT/时间展示/研究推理/告警代码，以及本地 `origin/李青原@ef13495` 的采集、序列化、网络、身份和冻结配置。未 checkout、合并、编译或执行候选固件。
- 评估包含 22 列逐项映射、长表到帧因果对齐、acquisition_index/attempted/acquired 语义、派生回放身份、timestamp=null/false 与接收时间约定。soil 只存 raw/uncalibrated，百分比/增长/风险/未定义特征保持 null；三种采样/窗口规格和抗混叠损失分别说明。
- 路径 A 的原始归档/分通道离线回放已有实物前提；完整 v2 投影还受正式身份和未知 system 布尔状态约束，不补默认值绕过 full-profile。路径 B 有网络/serializer/NVS 身份代码可复用，但冻结配置关闭网络，缺网络运行与新构建验收。两条路径分别列平台/固件改动、风险、工作量及准入条件，本轮仅设计、没有实现导入器。
- 新增明确接入阻塞：普通 v2 MQTT 对 REAL 自动归 OPERATIONAL，不能表达本批应有的 REAL/TEST_ONLY；现有 HTTP 测试口又强制 MOCK。真实诊断入口、生产告警用途边界和历史回放当前态隔离需下一轮按获批范围处理。双 IMU 仍依次进入同一 motion 缓冲，启用真实数据研究推理前须按传感器分窗并补结果通道/单调时间边界。上述均为**静态结论，未运行复现**。
- 仍缺 freeze-manifest.json、固件 bin/可重算 ELF、成文实际接线/安装说明、土壤标定、PWM/降雨量标定关系；评估中逐项写用途与李青原/B/何宇轩的补交或会签责任。缺标定不阻止诚实的原始归档，但不能据此产出百分比、训练集或风险结论。

### 验证与停止点

- 本轮只运行本机原件只读解析/校验、文档一致性及 diff 检查；没有运行平台行为复现、pytest、前端 build、ACL 自检、MQTT、串口、桥接或硬件实验。历史研究模型成绩仅按既定口径引用，不宣称本轮重测或部署就绪。
- 没有改平台/前端/固件/模型代码，没有恢复演示流、改数据库、删历史数据、部署或触碰板上任何内容。
- **远端交付未完成：** GitHub 连接器批量 create_tree 与范围更窄的 create_file 均被工具审批策略拦截，原文为 `MCP tool call requires approval, but approval policy is never`。未有文档写入成功，PR 尚未创建；已回读远端评估分支仍在 `7f3ac3c`。不改凭据/权限，也不经其他入口绕过该审批限制。
- **可审阅交付准备：** 独立临时 checkout 仅提交两份 Markdown，另在 `/private/tmp/node01-assessment/` 准备补丁和 PR 描述。描述明确仅评估、无代码变更、原始数据未入库；本轮实际完成的核验和远端阻塞分别陈述，不假称 PR 已交付。
- **停止点：** 停在本地文档完成及审阅准备；待连接器允许写入后仅补交文档 PR。等待何宇轩决定是否及按何路径进入下一轮施工；不自行开始导入器、用途隔离补丁、重采样、模型训练、烧录或在线联调，不合并 PR 或李青原分支。

## 2026-11-02 — 阶段 I WP1 用途隔离修复与本地审阅交付

### 授权范围和本地分支

- 开工前已完整阅读仓库外 `Astra决策-2026-11-02.md` 的 §0、§4.1、§8.1、§9.3，再完整阅读 `任务书-阶段I-WP1-隔离修复.md`。本轮仅执行 WP1 的 source/scope、生产告警、当前态和查询隔离；模型路线保持多模态因果规则模型 v1，本轮没有实现规则链。
- 接手时原仓库干净，`main`、本地 `origin/main` 均为 `672133d`。原仓库 `.git` 只读，创建分支时 `index.lock` 被系统以 `Operation not permitted` 拒绝；没有更改权限、凭据或原仓库 Git 元数据。
- 在 `/private/tmp/stage1-wp1/repository/` 从本地仓库独立克隆，并从 `672133d` 建立 `codex/stage1-wp1-isolation`，用于本地提交和 format-patch。修复文件同步回原工作区；原工作区分支仍为 main，提交分支位于临时副本。交付目录为 `/private/tmp/stage1-wp1/`，供 Muse 复核；没有 push、创建 PR、连接远端写入或部署。

### 修复行为和复用结构

- `database.py` 为新库及旧 schema 的 `alarms` 增加 `scope`；初始化在写事务内检测列并 ALTER。既有告警统一为 `LEGACY_UNKNOWN`，不追认为 OPERATIONAL，保留原 ID、确认状态和其他字段。复用已有 `telemetry.scope`、`is_current`、`is_backfill` 和每设备唯一当前态索引，没有新增研究当前态表。初始化取消旧 REAL 非 OPERATIONAL 行的当前标记，不删除遥测、不清理历史 MOCK。
- `telemetry.py` 以 `production_alarm_eligible` 集中检查 REAL、OPERATIONAL、经 full NODE 校验的原生身份、实时且有序的当前观测，以及既有生产者风险向上升级条件。REAL 输入中的派生回放身份、非实时 sidecar、非 MQTT 通路及已同步但超出时效的输入均只落库。时效沿用 `Settings.freshness_seconds`，默认 30 秒；未同步设备保留 null/false 和 arrival-only 语义。这里的身份有效性不等于固件或设备密码学认证。
- REAL+TEST_ONLY 不更新生产当前态、不注册在线 boot、不参与生产风险基线。旧研究 boot 注册也不会挡住该 boot 第一条合规在线消息。MOCK/TEST_ONLY 可保留独立 MOCK 设备的演示当前值，既有设备全局来源约束继续拒绝 MOCK 冒用 REAL 设备。非当前研究输入沿用原回执的 `is_current=false/is_backfill=true` 字段。
- 选择**非生产输入不落告警行**：MOCK、TEST_ONLY、历史或派生输入仍有遥测与 intake receipt 留痕，`alarm_id=null`；只有合规生产升级写入 `alarms.scope=OPERATIONAL` 及升级事件。同 device/boot/seq 改 scope 重发返回 409 并 quarantine，原行及 scope 不变；同 scope、同内容重复接收仍幂等。
- `connectors.py` 复用持久化 MQTT `config`，新增 `config.scope`，默认 TEST_ONLY；旧配置缺字段也按 TEST_ONLY 接收。只有显式配置 REAL/telemetry_v2/OPERATIONAL 才进入生产资格检查；MOCK 和 TinyQuake 连接器不能配置 OPERATIONAL。
- `main.py` 的 `/alarms` 默认只查 OPERATIONAL，可显式 `scope=TEST_ONLY` 或 `scope=LEGACY_UNKNOWN`，过滤在 LIMIT 前执行。dashboard 的告警列表与计数使用一致的 scope 条件，避免把历史未知用途当生产告警。告警行/确认响应新增 `scope`，MQTT 配置新增 `config.scope`，原响应外层结构保留。前端无需因附加字段改动；现有前端未提供 scope 控件，生产用途需经连接器 API 显式配置。本包没有改前端或运行 build。

### 实测结果和未完成验收

四组合均使用现有 v2 夹具，经真实接收函数和 SQLite 落库检查；每个场景先建立一条 REAL/OPERATIONAL/NORMAL 生产当前态，再送入有效高风险输入。MOCK 使用独立设备 ID。`behavior-matrix.json` 留在交付目录。

| source | scope | 新增生产告警 | 生产当前态 | 遥测与回执 |
| --- | --- | ---: | --- | --- |
| MOCK | TEST_ONLY | 0 | 不变 | 保存 |
| MOCK | OPERATIONAL | 0 | 不变 | 保存；MQTT 配置层拒绝该组合 |
| REAL | TEST_ONLY | 0 | 不变 | 保存 |
| REAL | OPERATIONAL | 1 | 更新为合规输入 | 保存 |

- **已运行：** 新增 `test_isolation.py` 的 21 项测试使用标准库 unittest 全部通过，包含四组合、派生/非实时/超龄/乱序输入、换 scope 重发及重启、旧 alarms 迁移、旧 REAL 研究当前态、boot/告警基线隔离、MQTT 默认/显式用途与 scope 变更回调。全部 21 个后端源文件和测试模块语法编译检查通过；diff whitespace 检查通过。测试仅使用临时 SQLite 和不连网的 MQTT 回调，没有启动平台、Broker、演示源或其他服务。
- **全量 pytest 尚未通过：** 任务书给定基线为 `155 passed`；本机改前、改后均因 `No module named pytest` 无法开始测试。系统 Python 为 3.9；已在交付目录用现成 Python 3.12 建临时环境，但缺 pytest、FastAPI、amqtt、Paho、OpenCV 等依赖，安装被包源 DNS 解析失败阻塞。没有修改系统 Python 或项目依赖声明。
- **静态清点不是实跑：** AST 按现有参数化展开，改前 155 项、改后 178 项；旧用例未删除，新增 21 项标准库兼容用例及 2 项 HTTP 端点用例。`test-inventory.json` 保存清单。新增 HTTP 用例及完整既有回归尚待具备依赖的环境实跑，不能将 178 写为 passed。PR 草案逐条列出 8 项既有测试的资格夹具/用途修改及理由。
- **交付限制：** 本地提交、format-patch 和 PR 描述草案可供审阅，但未满足任务书的全量 pytest 验收条件。Muse 复核时需先补跑完整 178 项预期用例，实际收集数和结果以 pytest 为准，再决定后续推送。本轮没有宣称部署或验收完成。

### 未做事项和停止点

- 未实现 CSV 适配器、原始回放、规则执行器或神经网络训练；未拆 `inference.py` TOP/TOE 窗口，未改研究模型或 OM，未改前端、固件及契约文档。
- 未连接或修改 Atlas、任何服务及板上数据库，未处理板上历史 MOCK 数据；未 push、开 PR、合并或删除分支。
- 停在 WP1 本地修复和审阅材料准备；范围之外的阶段 I 工作不继续启动。尚欠完整 pytest 验收，原仓库 `.git` 只读导致提交位于临时副本，两项差异均在 PR 草案和最终回复中明示。
