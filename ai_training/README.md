# AI Training Framework V0.1 Skeleton

当前版本 **0.1.1**；状态 **PRE_B_TRAINING_CONTRACT**。
新增 B_revised 的 **READY_FOR_TEST_ONLY_INTEGRATION** 旁路；正式训练状态仍为
**NOT_READY_FOR_FORMAL_TRAINING**。项目总状态见 [PROJECT_STATUS_AND_READINESS](../PROJECT_STATUS_AND_READINESS.md)。

**AI Training Framework V0.1 Skeleton does not constitute a trained disaster-warning model.**

这是负责人 C 的训练基础设施骨架：验证契约门禁、来源追踪、数据隔离、可复现执行和
artifact 管理。当前只有显式 TEST_ONLY 软件自检可执行。没有正式灾害模型、真实性能结论、
production-ready 或 deployment-ready 声明。正式训练仍被 A 的真实数据和 B 的 Training Contract 阻塞。

## 依据与团队职责

按以下优先级阅读并实现，原件只读：

1. [00_TEAM_SHARED_CONTRACT](../docs/00_TEAM_SHARED_CONTRACT.pdf)：Single Source of Truth。
2. [A 开发文档](../docs/01_硬件嵌入式与系统负责人开发文档.pdf)、
   [B 开发文档](../docs/02_算法与数据负责人开发文档.pdf)、
   [C 开发文档](../docs/03_AI应用云与昇腾负责人开发文档.pdf)。
3. [V0.1.0 Contract Alignment Review](../outputs/Contract_Alignment_Review_v0.1.0_2026-09-25.md)。
4. [physics_sim 当前说明](../physics_sim/README.md)、CHANGELOG、源码、配置和测试。

| 负责人 | 本模块消费的交付 / 边界 |
|---|---|
| A 李青原 | Real CSV、实验/设备来源、Calibration Metadata、validity、真实实验；当前未接入 |
| B 张鹏飞 | Feature 数学/顺序/单位/dtype、mask、Window、Label、Split、Leakage、Normalization、Metrics、Synthetic Constraints；C 不代为冻结 |
| C 何宇轩 | 契约消费、模型/训练器实现、注入 optimizer/loss、checkpoint、追踪、评价执行及未来导出；本轮只建骨架 |

没有修改 physics_sim 的公式、状态机、映射、参数或场景，也没有修改正式文档和历史记录。

## 架构与目录

```text
A Real Experiment Artifact ──> Real Adapter [WAITING_FOR_A/B]
physics_sim Observation Artifact ──> Synthetic Adapter [仅检查身份]
                                  │ 正式转换 WAITING_FOR_B
B Training Contract + Split Manifest
                                  ▼
                    CanonicalDataset / TrainingSample
                                  ▼
                 Train ──> fit Normalizer ──> injected Model/Optimizer/Loss
                 Validation ────────────────> injected Metrics/Best Policy
                 Test [sealed; 未提供最终评价释放入口]
                                  ▼
                  Checkpoint + Evaluation + Artifact Manifest
                                  ▼
                          ONNX [NOT_RUN]
```

`tests/fixtures` 人工 toy sequence 可执行训练器自检；B rule-distillation artifact 可执行只读
reader smoke test。两者均不经过 Real/Synthetic 生产适配，也不会互相冒充训练契约。

| 路径 | 职责 |
|---|---|
| `pyproject.toml`, `requirements.txt`, `.gitignore` | 独立 src 包、轻量依赖和输出保护；未改根目录配置 |
| `configs/README.md` | 明确没有正式模型配置/默认科学参数 |
| `contracts/README.md`, `contracts/examples/unresolved_contract.json` | C 侧 envelope 提案和未解决字段；不是 B 正式 Contract |
| `src/ai_training/__init__.py`, `errors.py` | 版本、状态、显式契约/泄漏/完整性错误 |
| `src/ai_training/contracts/schemas.py`, `validation.py` | 契约、SplitManifest、fail-closed、特征来源与分组检查 |
| `src/ai_training/datasets/sample.py`, `provenance.py`, `base.py` | X/mask/y 与来源分离、预构造窗口接口、数据身份和 Test 门禁 |
| `src/ai_training/datasets/normalization.py` | Normalizer Protocol、Train-only fit、转换校验、保存/恢复 |
| `src/ai_training/adapters/base.py`, `synthetic.py`, `real.py` | 独立 artifact 边界；真实数据转换与合成特征转换均阻塞 |
| `src/ai_training/adapters/b_rule_fixture.py` | B demo CSV → TEST_ONLY tabular container；白名单 X、来源独立、Test 封存 |
| `src/ai_training/contracts/b_handoff.py` | 调用 B 公开校验 CLI、识别两种版本、记录 readiness/blockers/hash |
| `src/ai_training/models/base.py` | Model、Optimizer、Loss Protocol；包内没有正式模型 |
| `src/ai_training/training/trainer.py` | 显式配置、初始化、逐 epoch Train/Validation、注入 best/early-stopping 策略 |
| `src/ai_training/training/checkpoint.py`, `reproducibility.py` | JSON 状态恢复、身份比较、统一 RNG、规范哈希、环境/代码追踪 |
| `src/ai_training/evaluation/evaluator.py` | 严格按 Metrics Contract 注入，当前仅 TEST_ONLY Validation |
| `src/ai_training/artifacts/manifest.py` | 内容身份、审计时间、artifact 哈希、无覆盖目录与完整性检查 |
| `src/ai_training/export/onnx_contract.py` | ONNXExportManifest / ONNXParityResult；仅 NOT_RUN |
| `scripts/validate_framework.py` | 契约拒绝检查或显式软件自检 CLI |
| `scripts/validate_b_handoff.py` | B→C 读取、重复性、正式用途拒绝检查；不拟合模型 |
| `tests/test_*.py`, `tests/fixtures/` | 正向/负向测试和 TEST_ONLY 数据/组件 |
| `outputs/` | 新生成验证证据；每次分配新目录，不覆盖旧结果 |
| `CHANGELOG.md` | 实际变更与验证历史 |

各子包的 `__init__.py` 只声明包。没有全局注册的默认项目模型或隐式训练入口。

## B_revised TEST_ONLY integration（0.1.1）

正式数据主线与旁路分离：
`B Demo Rules → B rule-distillation fixture → BRuleFixtureReader → TEST_ONLY smoke check`。
`B_FORMAL_TRAINING_CONTRACT` 0.1-draft 的候选特征不是正式有序 Features。
`load_training_contract` 对此草案明确报告 WAITING_FOR_A / WAITING_FOR_B / TODO_CALIBRATION；
即使调用者改 status 或填写所有 null，也没有注册正式解释器，仍不能训练。

Reader 显式接收可信本地 `B_revised` 路径和 artifact 路径。它通过独立 Python 子进程调用 B 的
公开 validator/verifier，避免把 B 的顶层 `contracts` 包混入 C，也不复制 B 特征公式或拆分算法。
这是执行已审查的本地交付代码，不是用于运行任意不可信下载代码的沙箱；源码 checkout 是当前依赖。

读取嵌入 Contract 和上游 Contract，核对版本、身份、10 个文件 hash、label 映射、split/group
一致性、来源规则/生成器 hash。随后只按 `model_features` 顺序取 X；所有数值列自动选入的行为不存在。
B 的四列特征、二元 rule proxy label、六记录聚合和 demo split 仅属于 `1.0-test-only`。
不修改其数学定义，不把 B fixture 当 physics-inspired 数据，不声称真实 VWC/灾害标签。

容器是 tabular `BRuleFixture`，不继承 `CanonicalDataset`，不伪造 `[time, feature]`、mask、
sampling 或正式 window。`partition('train'/'validation', purpose='TEST_ONLY')` 返回
`X[n,f]`、`y[n]` 和独立只读 provenance；float64/int64 只是 reader 内存类型，不是 B 正式 dtype。
Test CSV 只用于完整性审计，不经此 API 释放；unknown 行只核验，不进入有监督样本。
没有把 B fixture 塞入现有 toy Trainer 的契约解释器，也没有运行 B 规则模仿模型训练。

来源保留 group/sample/node、teacher、split、generator seed/version、rule version/hash、CSV 行索引/hash；
未知 scenario、run_id、parent_run、parameter_hash、dataset_version、feature_version 保持 null。
group_id 不冒充真实 run_id。dataset_role=TEST_ONLY，formal_training_dataset=false，physics_inspired=false。
任何非 TEST_ONLY purpose 先于读文件即抛出 FormalTrainingNotAllowedError。
seed/failure_time/future/state、scenario/synthetic_source/teacher/group/label source 等禁止进入 X。

reader fingerprint 覆盖 Contract、manifest、成员文件和 B validator/exporter 源码 hash；不含时间/路径。
它是输入完整性身份，不是正式 dataset_version、审批签名、科学真实性或 model identity。
读取时重新核对字节哈希；历史 artifacts 不写入。Python API 门禁不能阻止人工直接读取 CSV。

在仓库根目录运行：

```bash
PYTHONPATH=ai_training/src PYTHONDONTWRITEBYTECODE=1 work/.venv/bin/python ai_training/scripts/validate_b_handoff.py \
  --handoff-root team_handoffs/B_revised \
  --artifact team_handoffs/B_revised/artifacts/rule_distillation_demo
```

可加 `--output <新文件路径>` 保存 JSON 证据；已有文件拒绝覆盖。成功仅表示 TEST_ONLY 接口可用。
B 的历史 HANDOFF_TO_C 中“后续实现 reader”描述的是 C 0.1.0 交接时点，本节记录 C 0.1.1 的接入结果；
B 原交付及历史记录保持原样。

## Training Contract dependency

所有科学字段从外部 JSON envelope 读取。schema 包含 contract/feature version、ordered_features、
feature_units、dtype、mask、坐标、采样对齐、window length/stride/causal/warmup/gap/padding、
label、split manifest、normalization、metrics、synthetic constraints、nonfinite policy。
没有正式值时使用 null / WAITING_FOR_B；无默认 features、label、window size、split ratio 或主指标。

`ai_training.contract-envelope.v0.1` 只是 C 侧封装版本。**当前没有支持的正式 B Contract version**。
`load_training_contract(path)`、默认 `Trainer`、默认 `Evaluator` 都拒绝正式执行。
改写 status/approved_by 或给 toy contract 贴“B 已批准”标签也不能通过。

单元测试必须显式 `test_only=True`，且完整标记
TEST_ONLY / NOT_PROJECT_CONTRACT / NOT_APPROVED_BY_B。仅支持 `TEST_ONLY.v1`
的小型解释器；其中规则不是项目默认值。收到 B 正式交付后，需要版本化兼容实现和契约测试，
不能只把 null 填满或打开开关就宣称训练就绪。

## Dataset interface、单位与 Provenance

`TrainingSample` 含 `X`, `mask`, `y`, `provenance`，以及 `feature_names`, `times`,
`available_at`, `decision_time`。X 概念为 `[time, feature]`；未来 batch 为
`[batch, time, feature]`，当前没有 batch tensor backend。具体维度、顺序、dtype、单位来自契约。
toy 的时间与两个 dimensionless 特征仅有测试意义，不对应硬件采样率或 VWC。

`from_columns` 只显式选择 ordered_features，不扫描所有数值列。mask 编码从契约读取，可表达
valid/missing/padded/unavailable；当前 toy 模型只实现全 valid。y 的正式类型待 B，toy 为标量。
窗口已经由 fixture 预构造；`WindowBuilder` 是接口，不实现项目窗口生成、stride 排程或对齐算法。

`Provenance` 独立保存 REAL/SYNTHETIC、run_id、row_indices、parent_run、dataset/feature version、split。
Synthetic 保留 generator_version、seed、parameter_hash、source_artifact_hash；Real 可携带
device_id、boot_id、seq、calibration_version，未知值保持 null；这些不是对 A CSV schema 的假定。
行范围当前用明确 row_indices 表示。任何 lineage 均不会自动变成模型输入。

## Split、未来泄漏与 Normalization

- 必须有 SplitManifest；不存在 random_split、按窗口随机划分或默认 split 比例。
- 每个 run 只出现一次；同 run、可选 experiment group、任意代 parent_run 必须处于同 split。
  所有祖先必须显式声明；未知父来源/循环关系拒绝。B 决定真正的分组单位与划分算法。
- Trainer 只取 Train/Validation。Normalizer 同时检查样本 provenance 和 manifest 的 Train 身份；
  只向 fit 传递 X/mask，不传 label 或 lineage。Test/Validation fit 立即失败。
- Test API 默认密封；Evaluator 只接受 Validation。best checkpoint 和 early stopping 只能消费
  Validation/history。Test 标签改变的测试验证优化状态和最佳状态不变。
- `seed`, `run_id`, `parameter_hash`, `failure_time`, future 字段、latent physics 等禁止成为 X；
  同时检查 feature source 声明和 lookahead，避免仅改名绕过。
- 每个输入值的 available_at 不得超过 decision_time，源时间也不得在未来；顺序、shape、dtype、
  mask、对齐和 NaN/Inf 按可支持的显式 toy contract 验证。归一化后再次检查，错误即停止。
- Normalizer 只有接口，无 StandardScaler/MinMaxScaler 等默认选择。TEST_ONLY.identity 只在 fixture；
  参数写入带身份和哈希的 artifact，恢复时核对身份，相同参数供后续 Validation 使用。

这些门禁约束受信任的工程接口，不是 Python 安全沙箱；无法证明外部数据生产者没有谎报来源或
预先计算未来信息。完整 Test 数据可被对象持有并参与数据完整性哈希/结构检查，但不参与拟合、
指标选择或调参。未来真实 Test 的独立保管与释放程序仍需 B 明确。

## Model / Trainer / Evaluation boundary

ModelProtocol、Optimizer、Loss 都经注入；Trainer 不选择科学模型/优化器/损失。
TrainingConfig 显式提供 seed、epochs、model/optimizer config、loss/normalizer/best/early-stopping
标识和实验模式。无默认项目超参数。模型初始化获得同一个 numpy Generator；epoch 内按输入顺序执行。
最佳 checkpoint 策略可选，early stopping 接口可选，均不得隐式冻结项目策略。
策略必须无隐藏状态，或仅由已保存的 history/best metrics 决定。

Evaluator 要求契约指标与注入 registry 完全一致；无 Metrics Contract 即拒绝。
评价 artifact 包含指标、dataset/split/contract/model identity、逐预测 provenance 和 predictions。
评价 timestamp 当前 null，实际 start/end UTC 时间写在 run manifest，避免破坏可复现内容。
toy loss/metric **没有项目科学意义**，不报告项目 accuracy/F1。

## Reproducibility

唯一数值随机源是 `numpy.random.Generator`，种子显式提供并注入组件，不修改系统全局随机状态。
checkpoint 保存 RNG 状态。fixture 的受控随机扰动用来验证恢复连续性，不是物理噪声假设。

规范 JSON 使用排序 key、保留 list 顺序、拒绝重复 key 和 NaN/Inf；SHA-256 不含当前时间。
逻辑 `training_run_id = training_<SHA256(identity)>` 覆盖 config、data、contract、split、seed、
framework、model config、Python/NumPy 版本、OS/架构、框架源码内容和注入组件源码文件哈希。
Git revision 可用时保存，否则 null；源码哈希仍保存。输出路径、操作者和审计时间不决定 run_id。
操作者进入 manifest 内容哈希；manifest 的 started_at/ended_at 从内容哈希中显式排除。

同环境、同代码/数据/config/seed 的 TEST_ONLY 数值与核心 artifact 要求逐字节一致；同目录重复
写入明确失败，重跑使用不同输出根目录。软件自检目录随机后缀只避免覆盖，不影响随机数或逻辑身份。
系统时间变化只影响审计字段。改变 Test 数据会改变完整数据身份，但不改变训练决策。

**deterministic intent ≠ 跨硬件 bitwise guarantee**。当前检查本机 NumPy toy 流程；不保证
跨 CPU/BLAS/NumPy 版本、未来 GPU/Ascend 算子的逐位一致。注入组件不得使用隐藏 RNG；
动态无可追踪源码的组件当前拒绝。注入代码的传递依赖仍需未来明确锁定，不能仅凭组件名字推断可复现。

## Training run artifact 与 Checkpoint

```text
outputs/TEST_ONLY_validation_<unique>/
  full_a/training_<content_hash>/
    manifest.json
    training_config.json
    contract.json
    split_manifest.json
    training_log.csv
    checkpoints/last.json
    checkpoints/best.json          # 仅提供 best policy 时
    preprocessing/normalizer.json
    evaluation/metrics.json        # 内含 predictions 与 prediction provenance
  full_b/                         # 同配置独立重跑
  partial/                        # epoch 边界中断
  resumed/                        # 从中断 checkpoint 恢复
  validation_summary.json
```

Manifest 回答操作者、framework/contract/feature/dataset/split/seed/model/config/environment、
REAL/SYNTHETIC 来源声明、normalizer/checkpoint/evaluation hash、恢复来源、开始结束与停止原因。
ONNX、parity、deployment validation、independent Real Test 均为 NOT_RUN；未知字段 null。
来源列表覆盖 SplitManifest（含未使用的密封 Test 和 source-only ancestor），不表示全部来源都参与拟合。
哈希校验保护完整性，不是数字签名或外部审批证明。加载 manifest 时还核对配置、checkpoint、
normalizer 和 evaluation 的运行归属，拒绝把其他实验的文件混入本次 bundle。

Checkpoint 是非可执行 JSON，保存 model、optimizer、normalizer、RNG、epoch/step、history、
metrics 与 best state；identity 含完整数据/契约/划分/config/环境标识。
恢复前核对文件/内容哈希、schema 和完整 identity；不同 dataset/contract/config 不允许悄悄恢复。
恢复不重新 fit normalizer。当前只支持 epoch 边界恢复，不支持中间 batch、分布式或 tensor checkpoint。
`stop_after_epoch` 只模拟软件中断；它不是项目 early stopping 方案。

文件和目录 exclusive 创建；同 run artifact 不覆盖。中途失败可能留下不完整新目录，不自动删除；
只有存在且通过验证的 manifest 才视为完成的 artifact bundle。没有周期性 crash recovery 保证。

## physics_sim / Real CSV / Telemetry boundary

physics_sim V0.1.1 是冻结的独立依赖。SyntheticAdapter **不 import** hydrology、slope_state、
sensor_model；只读 simulation.csv + metadata.json，检查 schema/status、CSV 哈希、逐行 lineage、
config parameter_hash。只接受已知 v0.1.1 lineage 约定，不声称完整验证所有传感器值/validity。
输出为 Provenance；不会把九列 observation proxy 自动映射到 B 的 Feature Table。
SyntheticAdapter.to_dataset 仍拒绝执行，warmup/validity/多率对齐的正式消费待 B。

D(t)、velocity、state 是 latent/synthetic ground truth，failure time 只属于 synthetic metadata/标签
设计依据，不能成为部署输入。3 Soil + 2 IMU 的模拟观测不等于 A 的原始实验采样；Soil normalized
值不能称真实 VWC，vibration/tilt proxy 不能冒充已标定的硬件计算特征。

RealAdapter 始终 WAITING_FOR_A / WAITING_FOR_B。当前没有使用 A 尚未交付的数据。
Simulator Observation CSV ≠ A Real Experiment CSV ≠ B Feature Table ≠ zhifang.telemetry.v2。
本模块不实现 Production Telemetry Adapter、MQTT、Risk Fusion、Cloud、Web、IoTDA 或 Gateway。

## Future experiments / ONNX / Ascend

未来在 B 批准的同一 Independent Real Test 上比较 REAL_ONLY 与 REAL_PLUS_SYNTHETIC。
当前只保留显式实验模式配置位置，两种正式模式都拒绝执行。测试使用 SYNTHETIC toy 并不构成上述实验。

ONNXExportManifest 预留 model version、checkpoint hash、feature version/order、输入输出名称、
dtype/shape、dynamic axes、mask、normalization artifact、opset、导出框架版本和 ONNX hash。
ONNXParityResult 预留输入/输出身份与 tolerance contract。默认 NOT_RUN，拒绝虚构成功或误差结果。

未来链路：Training Framework → Framework Checkpoint → ONNX → ONNX parity validation →
ATC → OM → Atlas 200I DK A2 → ACL inference。本轮未安装 ONNX Runtime、未导出、未运行 ATC/OM/ACL/Atlas。

## WAITING FOR A / WAITING FOR B

**WAITING_FOR_A（李青原）**：正式 Real CSV 及 schema/交接样本，真实 run/设备/boot/seq 来源，
Calibration Metadata、validity、采样/时钟/实验记录；A/B 确认真实接口后再实现 RealAdapter。

**WAITING_FOR_B（张鹏飞）**：批准的 Training/Feature Contract，数学/顺序/单位/dtype/坐标/对齐，
validity/mask、窗口/causal/warmup/gap/padding、标签、分组/split manifest/泄漏规则、normalization、
metrics、synthetic constraints、Independent Real Test 保管/最终评价协议。

## Known limitations 与当前 Done Criteria

骨架完成只表示接口、保护、TEST_ONLY 训练/恢复/追踪与验证存在；不表示正式 training_ready。
当前解释器仅支持预对齐、全有效 toy 输入与标量 target，不实现生产 feature/window/label 算法，
不处理真实缺失数据/漂移/传感器校准，不提供任意 mask 数学或算法基线选择。
无正式训练、正式模型评估、ONNX parity、部署或真实性能保证。

当前 Done 要求：独立包；契约 fail-closed；X/provenance 分离；adapter/normalizer/model/trainer/evaluator
接口；split/causal/Test 门禁；可复现身份；checkpoint 恢复；manifest 与 NOT_RUN 导出契约；
自动化正负向测试、CLI 自检、README/CHANGELOG，且 physics_sim/正式文档/历史输出未改。
未来每次 meaningful change 都必须更新 README 当前状态并在 CHANGELOG 追加真实记录。

## 安装、测试与软件自检

Python 3.11+。运行依赖仅 NumPy；pytest 为开发测试依赖。未引入 PyTorch/TensorFlow/JAX。
本仓库已有 `work/.venv`，验证复用了该环境，没有安装新依赖。新环境可执行：

```bash
python -m pip install -r ai_training/requirements.txt
# 可选 editable 安装；下面 PYTHONPATH 命令无需安装包。
python -m pip install --no-deps -e ai_training
```

在仓库根目录执行：

```bash
PYTHONDONTWRITEBYTECODE=1 work/.venv/bin/python -m pytest -c ai_training/pyproject.toml ai_training/tests -q
PYTHONPATH=ai_training/src PYTHONDONTWRITEBYTECODE=1 work/.venv/bin/python ai_training/scripts/validate_framework.py --self-test

# 预期 exit 2：没有正式 Contract，不能训练。
PYTHONPATH=ai_training/src work/.venv/bin/python ai_training/scripts/validate_framework.py --contract ai_training/contracts/examples/unresolved_contract.json
```

CLI `--self-test` 重复执行完整 toy run、epoch 2 中断/恢复到同一终点，对比全部核心 artifact 哈希，
验证正式契约入口拒绝，并保存 `validation_summary.json`。`--output-root` 可另指定新验证根目录。
未传 `--self-test` 不会自动运行 toy。pytest 还覆盖非法契约/输入、泄漏、损坏 artifact、恢复身份、
Test 密封、ONNX 不实声明和防覆盖。实际测试数量/日期见 CHANGELOG。
