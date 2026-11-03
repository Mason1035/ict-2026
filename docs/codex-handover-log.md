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

## 2026-11-02 — 阶段 I WP2 原始回放与内部分析格式

### 基线、授权与实际交付状态

- 开工前完整阅读仓库外 `任务书-阶段I-WP2-回放适配.md`，阅读 Astra 决策中阶段 I、原始回放、分通道、时间/量纲、用途与验收口径，以及本日志尾部 WP1 记录。按用户本轮覆盖后的交付要求施工，不 push、不创建 PR。
- 本地 main 和 origin/main 的基线均为 `ed50d14130e465d1f202bf8316700391587e73d5`（PR #12 已合并），开始时工作区干净。
- **分支和提交未完成：** 原仓库执行 `git switch -c codex/stage1-wp2-replay main` 被沙箱拒绝创建 `.git/index.lock`，原文 `Operation not permitted`。本轮要求直接在原仓库提交，因此没有沿用 WP1 的替代仓库；实际仍在 main，改动为未提交工作区文件，没有 WP2 提交哈希。
- **指定交付目录未写成：** 创建 `~/Desktop/ICT-2026/deliveries/stage1-wp2/` 同样被沙箱以 `Operation not permitted` 拒绝。审阅说明、验证摘要、测试输出、四场统计和普通 diff 补丁保存在原仓库内可写的 `work/stage1-wp2/`（已被既有 `.gitignore` 忽略，位于桌面项目内，非 `/private/tmp`）。`delivery-note.md` 如实写明没有提交哈希及这两项路径/权限差异，不能视为已完成用户指定的 Git/目录交付。

### 实现与口径

- 新增 `sd_replay.py`，只读读取单场 BEG/CSV/END，逐项核对身份与固件声明、22 列结构、原始全字节长度/CRC32、END 行数及有效计数、全表从 0 连续的 acquisition_index。三件套分别计算 SHA-256；不一致抛结构化异常，不返回部分场次。非 Valid 行单独计数并保留原始 validity/error、缺失值及源物理行号。
- 新增 `research_sessions.py`，定义 `research-raw-session-v1` 内部会话/观测/五通道序列及转换，提供 `register_session()` 和 `python -m geohazard_platform.research_sessions` CLI。TOP/TOE 与三路 soil 各自独立，场内时间使用 acquired_uptime_us 相对 END.start_us，缺 acquired 仍为 None，不使用 attempt/登记时间替代；UTC 原样保持 null/false。合法 ADC=0 与缺测明确区分；不补零、不重采样、不拼场次。
- 专用 SQLite 研究登记库仅存元数据/指纹及登记审计，不复制或持久化原始观测。以完整 `(experiment_id, adapter_version)` 登记持久 UUID，标 `generated_replay_identity=true`；同内容重导幂等，同身份异字节或改类型拒收并审计。登记库不得放在输入场次目录内，已有生产/其他业务表的数据库拒绝复用。完整性拒收记录 `REJECTED_INTEGRITY`，身份冲突记录 `REJECTED_IDENTITY`，已知场次错标签记录 `REJECTED_METADATA`。
- 研究元数据固定 REAL/TEST_ONLY/sd_replay，risk/fusion eligible 均 false。R3/R4 的完整 experiment_id 对应会话及 soil_toe 的 `AIN2_JITTER_REVIEW`；R4 另标 `POST_RAIN_NOT_DRY_BASELINE`，四场类型按完整身份核对。固件声明一致不等于本体独立验收，保留未标定与声明身份标记。
- 按通道输出总数、原始 Valid/非 Valid 数、usable 数、缺值数、首末 acquired 时长和相邻 usable 记录间隔中位数。错误/缺测行不被间隔计算跨越；无数据/无间隔为 null。时长是观测跨度，不是连续覆盖率；长缺口策略、窗口、特征、参考与规则判定留 WP3。
- 新增合成与外部数据测试两文件；新增 [SD 回放格式与 CLI 文档](protocols/sd_replay_analysis.md)，平台 README 增加入口链接。未修改 WP1 的 database/telemetry/connectors/main/dashboard 或任何既有测试；未改历史 inference 混窗入口，此路径不调用旧 soil/motion 模型。无新依赖、前端、固件、规则、部署或硬件操作。

### 实物核对与旧故障样本

四场新批共 172,559 行；以下为本轮独立核对并固定在新增测试中的验收值，三件套字节/CRC/行数/索引及有效计数全部一致，非 Valid 行为 0。

| 类型 | CSV | 数据行 | CRC32 | IMU TOP / TOE 有效 | AIN0 / AIN1 / AIN2 有效 |
| --- | --- | ---: | --- | --- | --- |
| rain_50 | N0000001.CSV | 36,979 | 8d69498e | 17,998 / 17,901 | 360 / 360 / 360 |
| rain_70 | N0000002.CSV | 36,978 | 730feccd | 17,997 / 17,901 | 360 / 360 / 360 |
| rain_100 | N0000004.CSV | 36,973 | 711a03ea | 17,995 / 17,898 | 360 / 360 / 360 |
| post_rain_static | N0000005.CSV | 61,629 | 1a5fd03b | 29,994 / 29,835 | 600 / 600 / 600 |

- 新批原件位于 `~/Desktop/ICT-2026/数据/2026-11-02重测与无雨300秒/`；12 份 BEG/CSV/END 在 CLI 前后 SHA-256 全等，新增黄金值测试也逐场复查读前/读后指纹。原始数据未写入或复制到仓库；work 下的数据库与 JSON 仅为研究登记元数据、统计和验证记录。
- **旧 N0000002 原件未定位，真实故障回归跳过。** 历史评估附录 A 记载路径为 `数据/相同降雨量/70 pwm挡位/1（I2C错误）/N0000002.CSV`，本次该路径不存在。已用 rg 检索整个项目父目录中 N0000002/N0000006 文件，并枚举数据目录；目前仅两个 N0000002 位置，分别在新批目录与 `数据/相同降雨量/70档pwm/`，二者完整身份均为 `NODE01-d5a1317c1f27fded-N0000002.CSV`，CRC 730feccd、零错误，不是旧故障样本。
- 旧回归只在原件实际可读时核对历史文档固定的 SHA-256 `d54c00fda2788361d87f2c5975a5017b8ce5597e58288a4200b9ca4c4fe005fb`、CRC 311660b9、36,020 行、771 错误与通道计数；可用 `ICT_REPLAY_LEGACY_N2` 指定确切 CSV。没有编造旧 experiment_id 或以新数据充当旧故障数据。合成测试已实测错误保留、缺时间/缺载荷、通道失效及合法零值。

### 实测结果与尚欠验收

- **新增测试：** `PYTHONPATH=platform_backend/src python3 -m unittest discover -s platform_backend/tests -p 'test_sd_replay*.py' -v`，标准库 loader 实际收集并运行 26 项，**25 通过、1 跳过、0 失败/错误**。含 21 项合成回归、4 场黄金值回归；唯一 skip 是上述确实未找到的旧 N0000002。未将 skip 计作通过，也未宣称执行了 pytest 收集。
- **CLI：** 通过真实 `python -m` 入口依次登记四场并生成五通道统计，研究库恰有 4 场；R1 重导复用回放身份，审计为 REGISTERED×4、DUPLICATE×1。统计 JSON 和专用研究库位于 `work/stage1-wp2/`。
- **编译：** 用显式输出到 work 的 `py_compile.compile(..., doraise=True)` 编译全部 25 个后端源文件/测试模块，通过。系统默认 bytecode 缓存目录不可写，因此输出位置显式落在可写工作区。
- **全量 pytest 未运行成功：** `python3 -m pytest platform_backend/tests` 返回 `No module named pytest`。本机仅发现系统 Python 3.9.6，平台声明要求 Python >=3.11，pytest/FastAPI/NumPy/Paho/OpenCV/Pydantic/amqtt 等依赖均未装。未安装、升级或新增依赖。
- **WP1 回归尝试也被环境阻断：** 标准 unittest 导入既有 edge_intake 时，Python 3.9 无法求值既有 `Mapping[str, Any] | None` 注解，尚未运行其中 21 项。此失败与新增路径无关，但本轮没有把 WP1 历史通过数当作复跑结果。既有用例未删改；完整回归是否不低于 WP1 合并基线，仍须 Python 3.11+ 开发依赖环境补跑后才能确认。
- 验证详情保存 `work/stage1-wp2/validation-summary.json`、`new-tests.txt`、`full_pytest.txt`、`wp1_unittest.txt`。已通过 tracked diff 及五个新文件的空白检查，普通补丁 `review.patch` 的 `git apply --check --reverse` 检查通过；六个 WP1/旧推理模块与十个既有测试文件逐字节等于 HEAD。本包没有前端变更，未跑前端 build，也没有访问板子、生产数据库或服务。
- **剩余交付：** 在可写原仓库 Git 的环境从 main 建立 `codex/stage1-wp2-replay` 并提交这七个实现/测试/文档文件；把 delivery-note 放至用户指定桌面交付目录并填实际提交哈希；补跑全量 pytest。当前不具备这些路径/依赖条件，不能声明本地提交或完整验收已完成。按要求停在审阅材料准备，不推送、不建 PR、不合并。

## 2026-11-02 — 阶段 I WP3 因果特征、R4 冻结与研究规则

### 授权、基线与交付位置

- 动手前已完整阅读仓库外 `任务书-阶段I-WP3-规则执行器.md`，回顾 WP2 `sd_replay.py`、`research_sessions.py`、[SD 回放协议](protocols/sd_replay_analysis.md) 和本日志 WP2 尾部；补读 Astra 决策 §3、§7.1 的因果窗口和质量口径。按用户已批准的 R4-only **PROVISIONAL v1** 开工，不等 B 的尚未交付方法，不用三场雨调参。
- 基线为 main `c32d404`（PR #13 合并），开始时工作区干净。执行 `git switch -c codex/stage1-wp3-rules main` 仍被沙箱拒绝创建 `.git/index.lock`，错误为 `Operation not permitted`。实际分支仍为 main，没有分支创建成功或提交哈希；没有绕过沙箱或另建提交仓库。
- 按用户本轮明确授权的备用交付协议，审阅材料落在仓库内 `work/stage1-wp3/`，含 `delivery-note.md`、`validation-summary.json`、`review.patch`、运行/测试日志、两次四场 JSON 报告、只读指纹与静态测试清单。该目录沿用 `.gitignore` 的忽略规则。Muse 可经 SSH 从 main 建目标分支并落地 conventional 提交；本轮不 push、不开 PR、不部署。

### 实现事实与隔离边界

- 新增 `research_features.py`，输入仅为 WP2 完整性校验并登记后的五通道 `AnalysisSession`；新模块不自行读取 CSV。每场/每通道独立状态，只用实际 acquired 微秒时间，无重采样、未来插值、跨通道拼窗或零填补。
- TOP/TOE 使用起始 10 秒各轴中位参考、时间常数 1 秒的因果重力 EMA，输出相对方向角和倾角变化率。动态加速度能量按实际时间左保持积分，计算 2 秒 RMS、1 秒 STA / STA 之前 10 秒 LTA，并记录角速度 RMS。IMU 评估至少间隔 0.25 秒、数量覆盖至少 90%、相邻间隔 >30ms 切断窗口。
- 三路土壤仅保留原始 ADC 码及变化，基线为起始 10 秒处理副本的中位码，相对变化为 `(filtered_ADC-baseline_ADC)/abs(baseline_ADC)`；另报码/秒变化率。AIN2 在副本使用后向 5 点中位滤波，相邻原始码差超过 R4 冻结门限即中断该通道持续判定。原件和 WP2 原观测不被改写，保留 AIN2 复查标记。
- 错误、缺测、重复/回跳、零加速度向量、IMU 长缺口或土壤 >1.5s 缺口立即中断本通道判定；不以错误前旧值掩盖错误。初始参考被中断则该场不另选后段参考；建立后的参考在后续缺口保留，动态窗口重新预热。合法 ADC=0 不丢失，零基线的相对变化未定义，禁用对应事件。
- 新增 `research_rule_config.py`，冻结器只接收完整 R4 身份和 `post_rain_static` 类型，拒绝雨场、错标签/其他静态身份及无效参考。配置为 `research-rule-config-v1 / PROVISIONAL-v1`，记录逐通道中位数/MAD/p95/p99/最大值/冻结值、方法、来源身份/三件套 SHA、生成时间、参数和临时 reason 映射。公式为 `max(abs(R4)) + max(6*1.4826*MAD(abs(R4)), minimum_margin)`；分母噪声下限也只从 R4 LTA 生成。
- 配置已冻结为 `platform_backend/config/research_rules/provisional-v1-r4.json`，生成时间 `2026-11-02T14:33:50.196601+00:00`，内容摘要 `baf8b4bec4ab1cbace6f2abef1a76cb2dabcbe0e8cfde8b8b8f06f62f84cb8cd`。该配置在首次雨场计算前生成；雨场验证期间及之后均未改变特征公式、冻结值或窗口参数。
- 新增 `research_rules.py` 纯执行器与 `freeze/run` CLI。方向角或土壤相对变化各需独立越限 ≥3 秒；RMS 和 STA/LTA 同时越限 ≥1 秒只产振动候选，永远不进入触发计数或多通道事件。恢复门限为进入值的 0.8，持续 1 秒；质量异常立即中断。重合区间只使用已确认时间，不把持续起点冒充决定时刻。
- 每个结果和时段固定 `scope=RESEARCH`，输入 scope 另保留 TEST_ONLY；生产告警、风险融合资格均 false。输出含通道贡献、峰值、原因码/临时 mask、版本、来源、质量和起始/确认/末端时刻。开启特征轨迹可查看每点持续时间与决定，严格前缀一致；离线时段摘要可随未来证据延长末端/峰值，不冒充已发布的历史决定。
- 临时 reason 位定义明确标 `PROVISIONAL-platform-reason-v1-awaiting-B`，映射来自配置；测试证明换位映射无需改执行器。未来 B 标准在同一契约内只需换版本化阈值配置和映射；当前冻结器只实现临时方法。没有修改生产 risk_config、固件 reason_mask 或 WP1/WP2 代码/语义。
- 没有引入依赖、原始数据入库、旧 soil/motion 模型调用、概率、PWM→雨量换算、土壤含水率或风险分。未连接平台、Atlas、MQTT、串口或服务。新增 [实现协议](protocols/research_rules.md) 和四份研究报告，平台 README 增加入口。

### R4 自检与三场雨验证

freeze CLI 在写配置前要求零事件和零振动候选；最终 run CLI 另对四场各执行两次。全部消费同一份已冻结配置，原始文件仅读取校验/解析和计算指纹。

| 场次 | 研究事件 / 振动候选 | 时段要点（秒相对 END.start_us） |
| --- | --- | --- |
| R4 post_rain_static | **0 / 0，自检通过** | 五通道均有 READY 窗口，无 INVALID 或基线不足；不是因无可用数据得到零触发 |
| R1 rain_50 | 5 / 0 | TOE 方向角 24.400 开始、27.446 确认；三路 ADC 分别在约 32.576–42.086 开始变化；TOP 方向角 45.402 开始、48.451 确认；五段均到场尾 |
| R2 rain_70 | 5 / 0 | 三路 ADC 与 TOE 各一段；TOP 方向角 60.273 开始、63.317 确认、75.007 最后支持，之后满足恢复条件 |
| R3 rain_100 | 5 / 0 | TOE 方向角一段，AIN0/1 各一段，AIN2 两段；TOP 无事件；AIN2 共 205 个相邻差防护点，两段已确认事件均由该防护中断 |

- 每场完整时段/峰值/质量/同时变化表分别在 [R1](research/stage1-wp3/rain_50.md)、[R2](research/stage1-wp3/rain_70.md)、[R3](research/stage1-wp3/rain_100.md)、[R4](research/stage1-wp3/post_rain_static.md)。全部只陈述观测变化，不将同时变化解释为因果，不作滑坡结论，也不声称与 PWM 单调关联。
- **确定性通过：** 四场各两次真实 `python -m ... run` 报告逐字节一致；`run-verification.json` 保存报告摘要，执行器不生成新时间戳/随机数。登记库复用本轮持久 replay UUID，新登记库的 UUID 可不同，特征/冻结统计仍一致。
- **只读通过：** 四场共 12 份 BEG/CSV/END 在 CLI 前后 SHA-256 全等；配置文件字节在全部雨场运行前后全等。`raw-fingerprints.json` 和数据测试均核对只读，不复制原件进仓库。研究 SQLite 只含 WP2 的两张登记/审计表。
- **口径差异如实记录：** 任务书的试跑方向角摘要使用单秒中位偏离，本实现按上文 EMA 重力和起始向量定义计算，因此不直接套用摘要数值。土壤按本实现 10 秒起始 ADC 中位码分母计算时，R4 三路相对变化绝对峰值是 0.0325343947 / 0.00534062785 / 0.0200677182，与试跑摘要的对照 ≤0.34% 不同；本轮未取得试跑的完整归一化定义，保留公式和统计供 Muse 复核，未为贴合摘要或雨场结果修改参数。相邻 raw 差中位数/最大值重算仍为 3/80、1/4、81/172，与任务书一致。
- R4 零触发是冻结来源自身的包络自检，不是独立静态效果验证，更不能外推误报率、滑移识别能力或标定有效性。

### 测试、补丁与尚欠验收

- **新增 26 项全部通过：** 标准库 unittest 实跑 22 项合成/隔离/CLI/因果逻辑测试及 4 项真实场次测试。覆盖来源隔离、零触发、冻结不被雨场改动、精确前缀、未来扰动、实际时间积分、独立 TOP/TOE、错误/长缺口、零 ADC 基线、AIN2 防护和持续阶跃、候选永不触发、替换原因位表、原件/配置只读、无生产 SQLite 访问及 CLI 独占写。
- **WP2 回归已复跑：** 26 项运行，25 通过、1 跳过、0 失败/错误；唯一跳过仍为外部旧故障 N0000002 缺失，未以新雨场代替。
- **语法与保留范围：** 全部 30 个后端源/测试模块编译通过；全部 25 个既有后端源/测试文件与 HEAD 逐字节相同，没有删改原用例。静态 AST 展开参数化后从基线 204 项增为 230 项，**这是清点，不是 pytest 收集/通过数**。
- **全量 pytest 未运行成功：** 默认 Python 3.9.6 执行 `python3 -m pytest platform_backend/tests` 返回 `No module named pytest`。平台要求 >=3.11；本轮未安装/升级依赖，也未把历史 WP1 或全量回归当作本轮通过。Muse 需在 VM 的 Python 3.11+ 开发依赖环境补跑全量，确认实际收集规模不低于 204 及无回归。
- `review.patch` 覆盖全部实现/配置/测试/文档变更，交付检查包含空白、当前工作区反向检查和干净 HEAD 文件树上的应用/逐文件内容核对；最终检查结果见 `validation-summary.json`。原仓库仍未提交，不能声称有本地提交哈希。
- 与任务书的其他差异仅为已授权的 Git/交付目录沙箱备用路径及本机全量 pytest 环境限制；CPU 真机运行、地灾效果、长期误报和标定均未在本包宣称完成。本轮没有前端改动，不涉及前端 build。
