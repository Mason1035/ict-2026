# PROJECT-WIDE ADAPTATION AND READINESS REPORT

## 2026-10-05 当前进度增量：Telemetry / Edge Intake

已补充 C 独立 `edge_intake` V0.1.0，入口为 `receive_validated_telemetry(payload, *, context=None)`。
此前 A 实际调用的是训练方向 `RealAdapter.to_dataset()`，真实抛出 ContractNotReadyError，
是接口职责不匹配；训练入口保持原状，新 Telemetry 入口独立维护。

| 项目 | 当前事实 | 证据与边界 |
|---|---|---|
| Physics / Training | 本仓库 0.1.1 软件/骨架已有历史验证 | 本轮未改源码；正式数据/训练仍 WAITING_FOR_A/B |
| A 固件 | A 分支记录 9/28 Build PASS、host tests PASS | 固定 A commit 25c55ca；Flash/Serial Boot NOT_RUN，不等于传感器/实机验收 |
| A Mock Runner | 10/4 已有真实跨分支调用记录 | 曾触达 C 训练方法，INTERFACE_MISMATCH；不是三人联调通过 |
| C 最小 Intake | 本轮 syntax/import、37 tests、四例本地复验通过 | M01/M02/M07 各 1 调用；M08 四拒绝、0 调用；保留身份/null/source/payload |
| 三人 Mock | NOT_RUN / 等待 A/B 新入口接线重跑 | 旧 he_adapter.py 及旧状态断言仍需 A 更新；本轮未调用 B |
| 生产 Edge 下游 | NOT_IMPLEMENTED | 生产 Validator、认证、持久化/去重、MQTT、Atlas、Cloud 未接入 |
| 正式训练/真实效果 | BLOCKED / 无性能主张 | Mock 软件结果不是 Real CSV、标定或灾害模型评价 |

这次远端核对 A/B/C 分支分别为 `25c55ca0ab2e9d0f18e3640833a575102f7e48c6`、
`4d635759f4b9e222609938ef5e6d829463d40024`、`019a03a53336790a1439485754afdaaf3c34c9c1`。
B 仅核对分支 revision，未重新审计其全部新交付；下方 B 细节仍限定 9/25 的本地交付快照。
C revision 是本轮修改前基线，最终被测新入口以测试记录中的源码 hash 定位。
仓库现有 Git；下方 9/25 的“Git 不可用”仅为历史事实。

下一步：李青原固定包含新 Intake 的 C commit，更新 `he_adapter.py`/返回状态断言，
与 B 算法入口并列重跑 M01/M02/M07/M08。通过前不能标 `THREE_PERSON_MOCK_INTEGRATION_PASS`。

详见 [新入口说明](edge_intake/README.md)、[接口交接](docs/protocols/telemetry_v2_edge_intake.md)、
[本轮测试证据](docs/test_records/integration/2026-10-05_edge_intake_v0.1.0/README.md)。

## 2026-09-25 历史完整审计（以下 A–S 保留当时事实）

审查日期：2026-09-25。范围：当时开发仓库的活动源码、文档、契约、测试和已保存 artifact。
本报告不替代 00 Shared Contract，也不证明仓库以外的硬件/服务没有工作成果；未交付的证据不计为完成。
机器可读对应：[project_status.json](project_status.json)。不提供缺乏依据的完成度百分比。

## A. Executive Summary

现在能可靠完成三件事：生成可复现、可解释的物理启发合成观测；核验 B 的规则演示交付；
在 C 的训练骨架中验证契约拒绝、来源分离、训练/恢复/产物追踪等软件流程。
本次新增 B→C 显式 reader，使 B 的真实交付文件能够被 C 读取、验 hash 和检查用途。

**这不是已训练的灾害预警系统。** B 规则 fixture 是代理标签的软件测试数据，物理模拟尚未真实标定，
A Real CSV/标定/逐通道 validity 尚未交接，B 正式训练契约仍是 DRAFT。
因此正式训练、真实效果评价、ONNX/Ascend/Atlas 部署、云/Web 与真实端到端演示均未完成。

本轮适配完成的是 TEST_ONLY 接口与审计能力。没有为了连接 demo 而改变物理公式、B 的四特征、
label、split 或阈值；没有选择或训练正式模型。

## B. Architecture Status

| 组件 | Owner | 状态 | 实际证据与界限 |
|---|---|---|---|
| Hardware | A 李青原 | PARTIAL / WAITING_FOR_A | 有正式角色/BOM/资产表；三块已有板有文档记录，无本仓库实机验收/HIL 包 |
| Real Data | A；B 质量审核 | WAITING_FOR_A | 无正式实验 CSV+Calibration+Validity+run metadata 交付 |
| B Risk Algorithm | B 张鹏飞 | DEMO_ONLY | 老七字段协议、演示规则和 24 测试；正式四级 sensor_score 参考实现未交付 |
| B Training Contract | B | DRAFT / WAITING_FOR_B | 0.1-draft；readiness=NOT_READY_FOR_FORMAL_TRAINING |
| Physics Simulation | C 何宇轩 | DONE（第一阶段软件）/ TODO_CALIBRATION | 0.1.1；三场景、54 测试；不是真实灾害预测器 |
| Synthetic Data | C | PARTIAL | Simulator Observation CSV 有身份/质量字段；无已标定正式训练数据集 |
| AI Training Framework | C | SKELETON | 0.1.1；toy train/resume 可运行；正式解释器未注册 |
| Dataset Adapter | C | PARTIAL | B reader TEST_ONLY 已实现；physics 仅 lineage inspector；Real/正式 Feature 转换阻塞 |
| Model Training | C | NOT_STARTED（正式） | toy 测试循环有执行；正式 model_version=null |
| Evaluation | C 执行、B 定义 | SKELETON | toy Validation 可执行；独立真实 Test 未运行 |
| ONNX | C | SKELETON（schema）/ NOT_STARTED（导出） | manifest/parity 类型存在；真实 export/parity=NOT_RUN |
| Ascend | C | NOT_STARTED | 未运行 ATC、未生成 OM、无 ACL 推理 |
| Atlas | C 软件、A 硬件/HIL | NOT_STARTED（仓库集成） | 无实机环境锁定/推理/持久化验收证据 |
| Vision | C，A 采集协作 | NOT_STARTED | 无活动 OpenCV/视觉模型/主 UVC 接入实现 |
| Cloud | C | NOT_STARTED | 无 IoTDA、持久化消费、云部署验收 |
| Web | C | NOT_STARTED | 无活动 API/Dashboard 实现 |
| End-to-End | A/B/C | BLOCKED | 缺真实采集、正式规则、端边接入/持久化、设备与 HIL、云/Web |

### 正式链与当前旁路

```text
A Real Experiment Data [WAITING_FOR_A]
        ↓
B Formal Training Contract / Split / Metrics [DRAFT]
        ├── Real Data ────────────────────┐
        └── C physics_sim + Train校准 ────┤
                                        ↓
                     C Formal Adapter [WAITING_FOR_A/B]
                                        ↓
                Canonical Dataset → Training → Evaluation
                                        ↓
               Model → ONNX/Parity → ATC/OM/ACL → Atlas

B Demo Risk Rules → B TEST_ONLY Fixture → C BRuleFixtureReader
                                            ↓
                          TEST_ONLY artifact smoke check [本次实现]

C tests/fixtures toy → toy Trainer/Validation/Checkpoint [独立软件自检]
```

B demo 旁路不进入正式 Physics Synthetic 主线，不把预聚合的单行四特征变成正式时序 window。
最终边缘/云业务还需要 NODE→MQTT→Atlas→IoTDA→可靠云存储→API/Web；训练链不替代系统接入链。

## C. Completed Work：软件与科学验证分开

### Software-complete（限定已实现范围）

- Physics 0.1.1：配置校验、单 RNG、hydrology/state/sensor 分层、三基础场景、CSV/metadata、诊断图与测试。
- B-adaptation-0.1：两份可机读契约、公开 validator、TEST_ONLY exporter/verifier、manifest、保留原规则行为。
- C 0.1.1：读取 B 契约/产物、核对 hash/source、白名单 X、保留 provenance、Test 封存、正式用途拒绝。
- 训练骨架的软件路径：toy 模型/优化器/损失注入、Train-only normalizer、Validation、checkpoint 保存/恢复、
  manifest 与文件身份核验、重跑和恢复一致性，均有实际自动化验证。
- 项目总状态/阻塞清单、分模块版本、README/CHANGELOG、机器可读状态和本次证据记录。

### Scientific-validation-complete

**暂无真实灾害模型的科学验证完成项。** 软件场景覆盖不是沙盘参数标定；沙盘成功也不自动等于山区有效。
没有正式项目模型、真实世界 accuracy/F1、独立真实 Test 结果或部署性能。
正式意义目前在于 SSOT 职责/接口约束及可复现软件基础，不在于已证实的预警能力。

## D. Physics Simulation Status

版本 generator_version=0.1.1；observation_schema_version=physics_sim.observation.v0.1.1；
contract_status=PRE_B_TRAINING_CONTRACT；artifact_kind=simulator_observation_csv。
源码职责：config 校验、hydrology 含水存储、slope_state 状态/运动、sensor_model 观测、pipeline 编排与保存。

实际模型仍是：降雨→入渗/排水→归一化 M→I=M·sin(theta)→配置控制的状态/速度→积分 D→观测代理。
水分更新使用常降雨步段的一阶存储解析解，不是 Richards Equation；状态阈值和速率全为 SIMULATION_ONLY。
NORMAL/SATURATION 速度为零，CREEP/INCIPIENT_SLIP/FAILURE 使用配置速率；FAILURE 吸收，较早阶段允许恢复。

2 IMU + 3 Soil 与实验平台拓扑一致，但没有仿真 ICM 六轴原始码或 ADS1115 真实量测链。
Soil 0–1 归一化、位置响应系数/延迟，不是 VWC；相对湿润度 0–100、raw ADC、物理含水率不是同一量。
D 是 latent m，不是当前 NODE 的直接传感器；tilt 是线性位移映射，rate 是因果后向差分，
vibration_rms 是 m/s² 的合成代理，不是经过去重力/滤波/窗口计算的真实动态 RMS。
对照依据：00 的实验/数据单位约束、02 第 4/5/10 节、03 A1/A2；当前 proxy 命名不表示 B 正式 Feature 批准。

每行 run_id、row_index、is_synthetic、generator_version、seed、parameter_hash、parent_run 保留。
run_id 基于规范参数 hash；同 config+seed 同核心数据，输出目录唯一防覆盖；当前 parent_run=null。
Failure Time 只在 metadata，latent/state 与九列 observation whitelist 分离。
首行两列 tilt_rate 明确为空且 valid=false，observation_warmup=true；不是有效的零速度观测。
这里的 warmup 仅表示前一 tilt 尚不存在，不是未来真实滤波器预热规范。

本次重新执行结果（每场景 601 行，均通过 C lineage inspector）：

| Scenario | final_state | max M（0–1） | max D（synthetic m） | failure_time_s | 重复运行 |
|---|---|---:|---:|---:|---|
| normal | NORMAL | 0.2 | 0 | null | 相同 |
| rain_no_failure | SATURATION | 0.46197034836346235 | 0 | null | 相同 |
| heavy_rain_failure | FAILURE | 0.959374624464318 | 0.5144500000000003 | 357 | 相同 |

三份 plot CLI 均成功；重雨图已视觉检查，状态阶梯/单位/非真实预测声明可读。
Inf=0；允许的空值仅首行两列 rate，其余数值由 validate_output 严格检查有限性。不能把合理 null 宣称为数值错误。
54 项测试包含未来降雨不改变前缀、噪声不反控物理、种子与 hash、状态边界、配置错误和输出保护。

TODO_CALIBRATION：入渗/排水、状态驱动与速率、位移→姿态、速度→振动、各位置传播、真实噪声/偏置/漂移/
缺测/时间抖动及泵干扰；需 A 的受控实验与 B 的 Train 来源/约束。此轮没有改任何 physics 文件。

## E. B Delivery Status

活动交付位于 `team_handoffs/B_revised/`，原始 ZIP 位于 `B_original/`。
版本 B-adaptation-0.1；规则蒸馏 Contract 1.0-test-only；formal Contract 0.1-draft，三者不是同一个版本维度。

| 交付 | 当前可用性 | 不能据此声明 |
|---|---|---|
| `队员B_算法开发交付/risk_algorithm.py` + demo_rules.json | 24 原算法测试通过 | 正式 v2 Risk Engine / 真实危险阈值已实现 |
| `contracts/B_RULE_DISTILLATION_CONTRACT.json` | machine-readable；明确四列/顺序、label、demo window/split、禁用字段 | 正式 Features/Labels/Window/Split 已冻结 |
| `contracts/B_FORMAL_TRAINING_CONTRACT_DRAFT.json` | machine-readable；NULL 科学字段、未决责任和 readiness | 填满 null 或改 status 即可训练 |
| `contracts/validate_contract.py` | 返回 TEST_ONLY_READY 或 NOT_READY_FOR_FORMAL_TRAINING | B 已批准正式项目模型训练 |
| `adapters/export_training_fixture.py` | 独占创建/公开 verify；10 文件 hash；group/label/count 核验 | 可作为正式数据生产 Adapter |
| `artifacts/rule_distillation_demo/` | 180 supervised、18 unknown 隔离；train126/validation27/test27 | 198 个独立真实实验 |
| `docs/HANDOFF_TO_C.md` | 边界与分工有效；描述的是 C 0.1.0 交接时点 | 其中“后续实现 reader”代表本次适配后的最新 C 状态 |

旧 Risk 输入为 node_id/timestamp/soil_moisture_pct/tilt_deg/battery_pct/sequence/source；输出 normal/attention/
warning/unknown 等 demo 语义。00 正式规则是 NORMAL/WATCH/WARNING/EMERGENCY 与权重 sensor_score。
二者不能互接或仅改大小写冒充兼容。此次保持 demo 隔离，正式参考算法/标定仍 WAITING_FOR_B。
旧目录名 PRE_B、历史 training_contract.json 的 frozen 字样已被 B_revised 顶层说明限定为 legacy TEST_ONLY。
C 只从新的 contracts/ 与 artifacts/ 接入，不读取旧契约作为正式训练配置。

fixture 的四列为 soil_moisture_delta_pp、soil_moisture_slope_pp_per_min、tilt_median_deviation_deg、
tilt_min_abs_deviation_deg；label 来自 B 规则教师，normal→0，attention/warning→1，unknown→null/排除。
六记录、10 秒间隔、70/15/15 group split 都是 B 的 demo 规定，不被 C 提升成项目科学值。
physics_inspired=false，formal_training_dataset=false；run_id/parent_run/parameter_hash=null，不补造。

本次检验 B 两个 public CLI、artifact hash、模型/来源分离均正常，因此 **B_revised 未重写/未修改**。

## F. AI Training Status

training_framework_version 从 0.1.0 升至 0.1.1；整体仍 SKELETON / PRE_B_TRAINING_CONTRACT。
`AI Training Framework V0.1 Skeleton does not constitute a trained disaster-warning model.`

| 子能力 | 状态 | 已执行范围与剩余边界 |
|---|---|---|
| Contract loader | DONE（拒绝与已支持测试契约） | 识别 B draft，返回 A/B/calibration 阻塞；正式版本解释器 NOT_STARTED |
| Dataset interface | SKELETON | TrainingSample X/mask/y/provenance 与预构造 window 校验；无正式特征构建 |
| B fixture adapter | DONE（TEST_ONLY reader） | 显式上游/嵌入契约、hash、label、split、来源和白名单；不是正式 Dataset 转换 |
| Real / physics feature adapter | SKELETON | Real 拒绝；physics 仅 read-only 身份检查；科学映射待 A/B |
| Split guard | DONE（已支持契约） | run/group/任意祖先 parent 不跨 split；B demo 自有 group split 不被替换 |
| Leakage guard | DONE（接口范围） | 不自动把数值列送 X；provenance/latent/future/label 拒绝；不证明未审上游无隐性泄漏 |
| Normalizer | SKELETON | Protocol + Train-only fit/保存恢复；只有测试 Identity 实现，无正式方案 |
| Model interface | SKELETON | 注入式 Protocol；toy 在 tests/fixtures；无项目模型选型 |
| Trainer | SKELETON | 实际 toy train/validation/策略/日志可执行；无正式 tensor backend/训练配置 |
| Checkpoint | DONE（当前 toy JSON 范围） | epoch 边界状态/身份/hash/恢复；无 batch/distributed 保证 |
| Evaluation | SKELETON | 契约指定测试 Metric，Validation 执行；真实 Test 保管/释放/指标待 B |
| Artifact | DONE（当前测试 bundle） | exclusive 文件、manifest/成员/运行身份核验；不是正式 model release |
| Reproducibility | DONE（本机测试范围） | 显式 RNG、数据/配置/代码/环境身份；重跑与恢复逐字节一致 |
| ONNX interface | SKELETON | ExportManifest/ParityResult 类型；NOT_RUN，拒绝伪成功；无 ONNX 文件 |

### 本次适配细节

新增 `contracts/b_handoff.py`：以明确版本检查读取 B 两份 Contract；通过独立进程调用 B 的公开 validator。
新 reader 通过 B public verifier 重用领域规则，不将 B 顶层 `contracts` 包污染 C namespace，不重复实现四特征公式。
C 增加自身边界检查：与上游源 Contract 一致、B source rule/generator hash 一致、seed 合法、
无冒充 formal split/model metrics/真实 run lineage、读取字节与 manifest 一致。

`BRuleFixture` 是预聚合 tabular container；`partition(train/validation, purpose=TEST_ONLY)` 返回 X[n,f]/y[n]/provenance。
不造 time axis/mask，不转成 toy scalar-regression TrainingContract，不对 B fixture 拟合模型。
内存 float64/int64 只是读取实现约定，不替 B 冻结正式 dtype。Test 不经该训练 API 释放。
未知来源字段 null；source_row_index 表示 dataset_all 的零基记录位置，不是 A 的设备 seq 或原始六记录时间索引。

新增 CLI `validate_b_handoff.py` 验证重复读取、身份/输入一致和正式使用拒绝；结果为 READY_FOR_TEST_ONLY_INTEGRATION。
`validate_framework.py --contract B_FORMAL...` 返回 exit2 和明确阻塞原因；没有任何自动科学默认值。
两类 smoke 分开：B artifact 可读；独立 toy Trainer 能恢复。**没有宣称 B fixture 已进入正式 Trainer。**

## G. What Is Still Missing From A（李青原）

| 缺项 | 必要交付/证据 | 阻塞 |
|---|---|---|
| Real Experiment CSV | 00 表头、原始双 IMU 六轴/三 Soil raw/flow/rain/label 与文件 hash | Real Adapter、真实特征、模型训练 |
| Calibration Metadata | 安装坐标、IMU偏置/量程/ODR/滤波、ADC PGA、各探针端点、版本与方法 | 单位/坐标/量测可信度、校准 |
| Validity | 逐通道有效性、缺测、饱和、采样年龄、重启/ODR 边界 | cleaning、mask、causal alignment |
| run metadata | B 分配 run_id、source/parent、device/boot/seq、row→uptime、可信 UTC 与实验 Notes | 来源、分组、同步、证据关联 |
| 真实 noise/bias/drift | 静止/动态/重复装夹/长时实验、泵开关对照 | 合成扰动参数及域差距估计 |
| missingness/sensor response | 真丢样/通信丢包分开、长缺口、各位置响应和时间偏差 | 缺测/jitter/空间传播模拟 |
| pump/rain mapping | 流量脉冲系数、PWM/流量实测曲线、雨级目标与安全停泵日志 | rain 物理单位映射、可控实验 |
| 系统证据 | NODE/GW/SANDBOX/CAM 固件版本、v2/LoRa/Bundle 样例、故障/HIL 包 | 真正系统闭环 |

全部按当前仓库记 **WAITING_FOR_A**。00/01 要求的首批 normal、light rain、medium rain、vibration、small slip
五类 run 尚无正式包；即使五类全部到齐，也不等于具有统计泛化证据。

资产约束（04 表的实际内容）：现有资产表第6–8行记录 NODE S3、GW WROOM32、CAM S3-CAM；
立即采购第7–9行列 ICM42688P×2/SEN0193×3/ADS1115×1，注明先扣库存/PURCHASE_VERIFY。
不能把计划需求当已验收设备；Atlas 在后续采购表第6行，当前无取得/实测证据。
实验2+3与最终1+1分别建模，C不改 BOM。模拟器对拓扑适配，不承担电气/芯片精度真实性保证。

## H. What Is Still Missing From B（张鹏飞）

**WAITING_FOR_B**，正式 draft validator 当前报告20个 unresolved fields；重点是：

1. Formal Ordered Features：公式、顺序、feature_version、单位、dtype、坐标、validity/mask、采样/对齐。
2. Formal Label：类别/目标预测时段、区间与 unknown、不确定证据和 label_source。
3. Formal Window：长度、stride、causal/warmup/gap/padding、在线延迟。
4. Formal Split Manifest：dataset identity、run/parent/实验批次分组、先拆分后窗口/派生、独立真实 Test。
5. Leakage Rules：正式字段来源/可用时间/派生特征规则、Test 封存与释放程序。
6. Normalization Contract：实现/参数来源、Train-only fit、部署复用与版本化 artifact。
7. Metrics：数学定义、窗/事件单位、误报/漏报/提前量、阈值来源、不确定性和评估程序。
8. Synthetic Constraints：扰动范围来源、校准拟合域、允许用途、同源限制、真实分布评价。
9. Independent Real Test protocol：独立性、保管、一次最终评价、Real-only/Real+Synthetic 共用测试集。
10. B→A 正式规则包：四级 Risk 的可执行贡献曲线/缺测策略、reason_mask、risk_config、黄金向量/容差。

C 消费这些定义，不能用四 demo features、六点窗口、代理 label 或测试 Identity normalizer 顶替。

## I. What C Can Do Now（无需虚构 A/B 输入）

- 维护当前 B→C reader 和 fail-closed 兼容测试；B 发布新版本时先审查，不改 status 字符串直接放行。
- 运行本次两类 TEST_ONLY smoke、复现 checkpoint/artifact；测试失败可定位来源版本/hash。
- 与 A/B 逐条核对 G/H 的交接清单，明确每项验收证据；不把口头“ready”计为完成。
- 以 00 已冻结字段实现独立 `zhifang.telemetry.v2` 离线 validator/正负向样例，为 A→C 接口预联调准备。
  TBD-11/12 的未冻结量化/业务消息/receipt 继续标未决，不自行发明。

**唯一推荐下一开发步：离线 v2 Schema Validator + 正负向黄金样例。**
它有 SSOT 支持、可在无模型时独立验收，并直接补齐 C1/M0 接入缺口；本轮未自动实施。
正式训练路线则持续等 A Real Data+B批准 Contract 到齐。

## J. What C Cannot Do Yet

不能确定正式模型输入/label/window/split/metrics/normalization；不能拿 demo 训练出高分后宣传预警能力；
不能把 physics 代理改成正式传感器特征以绕过 B；不能用 Test 标定模拟器/拟合 scaler/调参。
没有模型和黄金输入，就不能生成可信 ONNX/parity；没有实际套件兼容矩阵，不可冻结 CANN/SoC/ATC 参数。
不能把开发电脑运行、资产表型号、测试 checkpoint、NOT_RUN schema 或云架构文档计为真实 Atlas/云完成。

## K. Not Started（当前仓库可见范围）

- 正式时序模型训练/选型、Real-only baseline、Real+Synthetic 消融、Independent Real Test。
- 正式 ONNX export 与 parity、ATC、OM、ACL、真实 Atlas 模型推理/延迟/内存验证。
- NODE/GW/SANDBOX 固件与真实采集交付在本仓库未出现；不判断队员其他位置的未交付工作。
- C 的生产 v2 validator、MQTT intake、去重/持久化/receipt、离线 spool、可靠云确认。
- LoRa黄金帧与真实链路、UAV Bundle可靠导入/回执（无线选型仍未冻结）。
- 主视觉 UVC/OpenCV baseline/视觉AI、sensor/vision fusion及失败回退。
- IoTDA/Redis/RDS、Backend/API、Web Dashboard、鉴权、备份恢复/回滚验收。
- 真实端边/端到端故障注入、现场或长期运行验证。

有设计文档不等于有实现；有 Skeleton 不等于生产功能已运行。

## L. Project Roadmap（依赖顺序，不猜日期）

| 阶段 | 先决条件 | 产物/门槛 |
|---|---|---|
| 1 可信采集与契约 | A设备/实验可运行；B实验设计 | Real CSV+calibration/validity+质量报告；B versioned contract/split/metrics；冻结独立 Test |
| 2 受控数据转换 | 阶段1交付通过审查 | C版本化Real/Physics Adapter；B特征一致性黄金向量；只用Train校准；保留来源 |
| 3 Real-only baseline | 可用正式 dataset 与可复现训练配置 | B规则基线和C轻量模型；用Validation开发，不访问密封Test |
| 4 Real+Synthetic | B synthetic constraints + Train校准证据 | 同模型/评估约束下消融；同源母run不跨split |
| 5 Independent Real Test | 模型/参数选择锁定；B批准释放 | 同一独立真实Test比较两实验；事件指标/不确定性/适用域报告 |
| 6 ONNX | 已审查模型包、前处理、黄金输入 | export hash/shape/dtype/mask/opset；framework≈ORT parity |
| 7 Ascend/Atlas | 实际套件和兼容矩阵、ONNX parity | ATC/OM/ACL、ONNX≈OM、性能/回退/回滚实测 |
| 8 Full Integration | A本地自治/B规则、C端边持久化、云资源与HIL | 实机MQTT/备用/离线/视觉/云Web；故障不取消sensor EMERGENCY |

可并行的工程支线是 schema validator、测试接入、资产/数据采集、视觉基线；不能把支线完成写成正式训练条件满足。
SSOT M0/M1 尚有交接缺项，M2真实Atlas、M3备用/多模态、M4云闭环均无完成证据；整体 C1 也尚未全部完成。

## M. Blockers

| 状态/Owner | 缺什么 | 阻塞什么 | 关闭证据 |
|---|---|---|---|
| WAITING_FOR_A / A | 真实CSV、run/时间/validity/标定包 | Real Adapter、B质量/特征、真实训练 | 原始文件hash、逐通道证据、复现读取 |
| WAITING_FOR_B / B | 正式features/label/window/split/normalization/metrics/synth约束 | C正式契约解释器/数据转换/训练/评价 | 版本化批准Contract、黄金样例、独立Test协议 |
| TODO_CALIBRATION / A+B+C | 真实响应/噪声/阈值/泵与雨映射 | 科学有效性、受控合成、真实风险主张 | Train域估计、方法和不确定性、独立验证 |
| NOT_STARTED / C | v2 validator/intake/持久化/去重/spool | 最小端到边预联调/可靠性 | 正负向/重复/断电/回放记录 |
| WAITING_FOR_A+B / A+B | 正式NODE风险运行与黄金向量 | 本地自治报警及上下游一致 | B参考与A实机容差内一致、HIL |
| NOT_STARTED / C+A | 实际Atlas支持栈/设备验证 | OM/ACL/真实边缘运行 | 套件版本锁、转换/实测报告 |
| NOT_STARTED / C | 视觉与云/Web/鉴权/备份 | 多模态及完整演示 | 功能/降级/恢复/权限验收 |

不把缺失科学合同误报为代码 bug；也不把未开始的 C 独立工程都归咎于等待 A/B。

## N. Definition of Done（整个项目，不是本轮小任务）

1. SSOT角色/GPIO/协议/风险边界一致；设备状态、版本、配置/标定可追溯，无虚构采购/实测。
2. A 能稳定产出可信2IMU+3Soil/流量/实验记录；重启/缺测/断网/SD故障可诊断，本地Alarm不依赖云。
3. B 正式特征/风险/标签/拆分/评价契约可执行；A在线与B回放有黄金向量一致性与标定证据。
4. C正式数据来源、Train-only拟合、因果窗口、run/parent隔离、Test封存可审计；模型可重现/恢复/回滚。
5. Real-only/Real+Synthetic在同一独立Real Test评价，报告真实事件级效果、误差/限制，不把合成成绩冒充真实性能。
6. 如交付AI部署，需真实ONNX/parity/OM/ACL/Atlas验证包，前后处理/模型/环境/哈希一致，失败可回退。
7. NODE→MQTT→真实Atlas可靠落盘，重复/部分补齐/历史消息/断电恢复正确；已确认数据不能丢。
8. 主视觉质量/新鲜度/区域匹配有效；视觉/NPU/云失败不得降低sensor EMERGENCY。
9. 云历史持久化与可靠确认、Web缺测/过期显示、权限、备份恢复和回滚通过；断云不影响现场。
10. 真实端到端演示有输入/版本/预期/实际/日志hash与失败复现记录；未完成项仍明示。

编译通过、210测试、几个漂亮图、toy checkpoint 或一个 ONNX manifest 类均不足以满足上述项目 DoD。

## O. Contract Alignment、Leakage、Provenance 审查结果

| 分类 | 对应资料/文件 | 发现与处理 | 仍存限制 |
|---|---|---|---|
| MUST FIX，已修 | 00/02§8/10；C contracts/validation.py | 中央禁用表补 B scenario/source/teacher/group/seed/规则来源等，新增负向测试 | 字段名审查不能证明任意外部公式无隐性未来依赖 |
| MUST FIX，已修 | 03 A3、B formal draft；C loader/b_handoff.py | 正式draft不再仅报未知字段；readiness详情与训练拒绝连通 | 无正式解释器，不能靠改批准字符串启用 |
| SHOULD FIX，已修 | B HANDOFF_TO_C；C adapters/b_rule_fixture.py | 增加B artifact白名单reader/hash/provenance/Test门禁 | 仅tabular测试读取，不是正式window adapter |
| SHOULD FIX，已修 | C README、根目录 | 删除“唯一测试入口仅toy”的过期当前描述；独立版本/状态报告 | B历史交接文字按交接时点解释，未篡改原交付 |
| ALIGNED | 00实验拓扑、03 A1；physics_sim | 2+3、D latent、Failure metadata、obs/physics分层 | Soil/tilt/vibration均proxy，需真实标定 |
| ALIGNED | 02§8；C datasets/training | split/parent guard、train-only fit、Validation选择、Test封存 | Test独立保管最终协议仍待B；API不是安全沙箱 |
| ALIGNED | B rule Contract/manifest | TEST_ONLY、physics=false、formal=false、来源与X分开 | Demo label由规则教师产生，不是真实灾害真值 |
| FUTURE | 00 TBD-10/13/14；A/B/C文档 | 真实标定、泵雨映射、独立Test、Atlas兼容 | 本轮不猜数值、不采购、不部署 |

failure_time、future state/moisture/label、scenario、synthetic_source、run_id、seed、parameter_hash、parent_run、
group、teacher/label source 均不自动进入 X。B CSV 四列白名单与 C toy 契约名单分开验证。
同 run/parent/group 跨 split、Test/Validation fit、Test调参入口均有现有负向测试；B未知标签隔离由公开verifier核验。
完整数据/标签参与内容hash用于完整性，不等于参与训练决策；现有测试更改Test labels后训练决策仍相同。

未发现需要更改 physics 科学行为的接口错误，未发现新增职责越界。正式科学定义保持 A/B 主责。
没有新增平行的Risk/Feature/Split算法；旧交付/输出源码副本是历史记录，不在活动回归路径重复收集。

## P. Versions、Artifacts 与复现

| 身份维度 | 当前值 | 解释 |
|---|---|---|
| SSOT / A/B/C文档 | 1.0 | 2026-09-24基线，不由本次代码升级改变 |
| generator_version（physics） | 0.1.1 | 独立于训练framework |
| observation_schema_version | physics_sim.observation.v0.1.1 | 非telemetry/real CSV |
| B delivery | B-adaptation-0.1 | 接口交付版本 |
| B demo contract | 1.0-test-only | 不代表正式feature_version |
| B fixture generator | 1.0.0-test-only | 不代表physics generator |
| B formal contract | 0.1-draft | NOT_READY_FOR_FORMAL_TRAINING |
| training_framework_version | 0.1.1 | 本轮接口补丁版本 |
| model_version / formal dataset_version / calibration_version | null | 尚无正式模型/数据集/校准交付 |

时间不作为内容身份；Git不可用（当前目录不在Git仓库），源码内容hash仍保留。
数值随机统一Generator；B reader不生成随机数/不重新split，重用B artifact；路径变化不影响fixture fingerprint。
同本机环境 toy 全量重跑与epoch2→4恢复的artifact hash/last checkpoint bytes完全一致。
这是本机确定性证据，不承诺跨硬件/软件版本 bitwise guarantee。

本次新证据目录：[PROJECT_AUDIT_7rasdry4](ai_training/outputs/PROJECT_AUDIT_7rasdry4/)。

- [B→C结果](ai_training/outputs/PROJECT_AUDIT_7rasdry4/b_integration.json)：含四特征单位、10成员hash、readiness20项未决。
- [Toy运行/恢复](ai_training/outputs/PROJECT_AUDIT_7rasdry4/toy_cli.stdout.json)：仅软件验证checkpoint/manifest。
- [Physics三场景](ai_training/outputs/PROJECT_AUDIT_7rasdry4/physics_validation.json)：含新CSV/图目录，旧outputs不覆盖。
- [正式拒绝](ai_training/outputs/PROJECT_AUDIT_7rasdry4/formal_rejection.json)：exit2，A/B/calibration blockers。
- [验证总记录](ai_training/outputs/PROJECT_AUDIT_7rasdry4/verification.json)：测试分项、保护文件hash、编译/导入。

fixture fingerprint：`988e58bf3a4f8857cf32ec6a7e7f93740ccadbc00a8ce25e7afa2d2abadd3dfe`。
toy checkpoint hash：`285184331ccc4ac753b29fd2f8a0865f56c05e49bd293bde3c408e9223debd71`。
hash用于完整性，不能当外部批准签名或科学验证证明。本地outputs通常被忽略，应交付源码与报告时另保留所需证据包。

## Q. Tests Before / After 与运行证据

环境：Python3.11.9、NumPy2.4.3、pytest9.0.2；复用 work/.venv，无新增依赖。

| 测试范围 | 修改前 passed | 修改后 passed | failed | skipped | subtests passed |
|---|---:|---:|---:|---:|---:|
| physics_sim | 54 | 54 | 0 | 0 | 0 |
| B original Risk（revised内保留原实现） | 24 | 24 | 0 | 0 | 12 |
| B revised adaptation | 18 | 18 | 0 | 0 | 8 |
| ai_training（含新integration） | 83 | 114 | 0 | 0 | 0 |
| 其中：新B→C integration | 0 | 31 | 0 | 0 | 0 |
| 完整活动源码回归（不重复计integration） | 179 | 210 | 0 | 0 | 20 |

修改前实际全量命令179 passed/20 subtests；修改后全量210 passed/20 subtests，另独立运行各套件核对。
JUnit 的tests数包含subtests，不能把230写成230个顶层测试。
编译检查65个活动Python文件（含测试/脚本），导入28个ai_training模块成功。
完整命令见根README；未将历史outputs副本或venv包当项目测试收集。

新增31项包括：真实B交付读取/顺序/标签/nullable来源；拷贝路径与时间不影响hash；Test封存/用途拒绝；
formal readiness及未知版本/伪ready；B审计字段入X拒绝；hash/role/physics/伪parent/伪metrics/source篡改；
缺文件、更新hash仍违反split/label/feature/finite语义；CLI成功及防覆盖。未降低旧测试要求。
既有测试继续覆盖真实run/parent跨split、scaler/Test泄漏、checkpoint不兼容、虚构ONNX成功等。

额外实际运行：两类验证CLI成功；正式draft CLI预期exit2；三个physics场景/三张诊断图；
重复模拟frame+metadata一致、1803行C lineage inspector成功；无不允许NaN/Inf。
本轮没有未解决测试失败。没有正式模型指标可报告。

## R. Changes Made / Files

### 新增源码/测试

| 文件 | 用途 |
|---|---|
| ai_training/src/ai_training/contracts/b_handoff.py | B版本/公开validator桥接、readiness与blockers |
| ai_training/src/ai_training/adapters/b_rule_fixture.py | 只读TEST_ONLY tabular reader、来源/白名单/Test保护 |
| ai_training/scripts/validate_b_handoff.py | 集成CLI及非覆盖JSON证据 |
| ai_training/tests/test_b_handoff_integration.py | 31项正负向接口测试 |

### 修改文件

| 文件 | 修改原因 |
|---|---|
| ai_training/src/ai_training/contracts/validation.py | 扩展禁用字段、显式拒绝B demo/formal draft作为训练契约 |
| ai_training/src/ai_training/errors.py | FormalTrainingNotAllowedError明确用途错误 |
| ai_training/src/ai_training/__init__.py、ai_training/pyproject.toml | 独立framework版本0.1.1 |
| ai_training/README.md、ai_training/contracts/README.md | 当前B接入范围/类型/限制/命令 |
| ai_training/CHANGELOG.md | 追加本次真实接口、测试和限制记录，不改0.1.0历史 |

新增根README.md、本文、project_status.json：仓库原无统一入口与总状态文件，需要最小根级增补。
新增本次outputs证据，使用新目录不覆盖历史。未增加大型依赖或插件系统，没有模型/科学算法重构。

**刻意不修改**：physics_sim所有文件、B_original/B_revised、docs正式PDF/XLSX、根历史outputs、任何Real数据。
预先hash基线覆盖上述164个已有文件；验证0 changed/0 removed/0 added。原ai_training历史artifact也未覆盖。

## S. 最终 Q1–Q10

| 问题 | 答案 |
|---|---|
| Q1 physics_sim第一阶段完成？ | 是，限定0.1.1模拟软件、三场景/图/复现/lineage；真实校准与地质预测验证未完成 |
| Q2 B_revised适配C？ | 是，作为TEST_ONLY fixture+formal draft交付；本轮C已可实际消费。正式训练仍未适配 |
| Q3 ai_training可TEST_ONLY smoke？ | 是，B reader smoke和独立toy Trainer/resume smoke均实际通过 |
| Q4 正式模型训练条件？ | NO；WAITING_FOR_A Real Data、WAITING_FOR_B批准Contract及正式adapter/版本解释器 |
| Q5 真实世界性能结果？ | 没有；没有真实accuracy/F1/提前量结果 |
| Q6 正式模型生成？ | 没有；model_version=null，toy checkpoint只用于软件验证 |
| Q7 已有ONNX？ | 没有真实导出文件；只有manifest/parity schema，NOT_RUN |
| Q8 Ascend/Atlas完成？ | 没有；ATC/OM/ACL/真实设备推理与HIL未执行 |
| Q9 距正式端到端演示缺什么？ | A可信采集/自治、B正式特征风险契约、C真实adapter与受控模型（AI演示时）、端边可靠接入/持久化、视觉/融合、Atlas实机、云Web及故障HIL；详G/H/K/M/N |
| Q10 何宇轩下一步？ | 实现独立v2离线validator与正负黄金样例，为A→C预联调补缺；本轮停止，不自动训练 |

**本轮适配与审计完成；整个项目未完成；正式训练仍 BLOCKED。**
