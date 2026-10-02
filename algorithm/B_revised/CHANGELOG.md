# B 适配交付 Changelog

只记录本次实际改动，不重写 B_original 或早期验证历史。

## 2026-10-02：用途审计与 A 接口 v0.2

- 新增 `docs/B_CODE_USAGE_AUDIT_2026-10-02.md`，逐项区分正式候选数学、手动初检、规则蒸馏 TEST_ONLY 与旧七字段演示；明确 A 可设计模块边界，但不能用未标定参数发布正式 Risk。
- 新增显式窗口/缺口/年龄参数的 `candidate_features/causal_window.py` 和 6 项边界测试；boot、ODR、校准等分段键变化会清空历史，长缺口/过期不伪装有效窗口。测试中的毫秒数不是正式配置。
- 数学与评分函数对字符串、布尔值等错误数值类型返回无效，不把它们隐式转为有效观测。B→A TEST_ONLY 向量由 18 扩至 26，覆盖负斜率、干湿端点、退化分母、score clamp 和等级上边界。
- A 交接 ZIP 构建清单补入因果窗口、测试、用途审计和 B 负责人文档；新包名带 `v0.2`，旧包留作历史，不覆盖。正式 Training Contract 状态不变。

## 2026-10-02：B→A 算法接口预交接

- 根据共享契约和 A 负责人文档新增 `hardware_handoff/`：模块边界、时间/validity、候选数学、缺测/故障、评分外壳、不可加载的风险配置草案、18 个 TEST_ONLY 黄金向量与首批实验数据交接清单。
- 新增可复现的向量运行器、测试和 ZIP 构建器；ZIP 同时包含两份权威 PDF、B 参考函数和 CSV 初检工具，并生成包内哈希清单。
- 真实窗口、滤波、贡献曲线、`reason_mask`、滞回及板端数值容差仍待 A 数据与 A/B/C 会签；本包状态为 `INTERFACE_DRAFT_DO_NOT_DEPLOY`，未宣称正式 Risk 配置已冻结。

## 2026-09-28：划分预检与交接状态

- 新增 `evaluation/split_preflight.py`、TEST_ONLY 计划样例和测试：检查 run/parent_run 跨分区、合成数据只能属于 Train 且必须有真实 Train 母 run、重复 run 和空计划；结果始终不宣称正式训练就绪。
- 新增 `docs/B_DELIVERY_STATUS_AND_DEPENDENCIES.md` 与 `docs/B_QUALITY_REPORT_TEMPLATE.md`，记录本分支实际交付和 A/C 待提供的来源证据。仅检查了远端分支可见文件，不推断队友本地进度。
- 正式 Training Contract 状态不变：`NOT_READY_FOR_FORMAL_TRAINING`；未生成或训练正式模型。

## [B-adaptation-0.1] - 2026-09-25

### Added

- 新增 `contracts/B_RULE_DISTILLATION_CONTRACT.json/.md`，把既有四列、六点窗口、代理标签和演示组级
  split 显式限制为 `RULE_DISTILLATION_TEST_ONLY`，列出 model_features / provenance / forbidden fields。
- 新增 `contracts/B_FORMAL_TRAINING_CONTRACT_DRAFT.json/.md`，用 null、WAITING_FOR_A/B、
  TODO_CALIBRATION 列出正式输入缺口；没有编造正式 Ordered Features、Label 或 Split Manifest。
- 新增 `contracts/validate_contract.py`：Rule Contract 返回
  `READY_FOR_TEST_ONLY_FRAMEWORK_SMOKE_TEST`；正式 Draft 返回
  `NOT_READY_FOR_FORMAL_TRAINING` 和 unresolved fields；虚构 ready/版本/字段漂移时拒绝。
- 新增 `adapters/export_training_fixture.py`、一份 `artifacts/rule_distillation_demo/`、
  `docs/HANDOFF_TO_C.md`、本目录 README、18 项接口/泄漏/产物测试。
- Artifact 包含四个 supervised CSV、unknown 排除 CSV、contract/summary/manifest、原始窗口审计、
  metric 模板和说明。Manifest 保存文件 SHA-256、源规则/生成器哈希、字段顺序、状态和行数。

### Changed

- 旧 `PRE_B_TRAINING_CONTRACT` 的 JSON/README/Markdown 标明为 legacy TEST_ONLY 来源，修正“A 训练”
  和“已冻结正式契约”的误导性表述；规则蒸馏范围内的既有数值与 split 仍保留。
- 旧生成器新增显式 `output_dir` / `contract_path` 注入并独占创建目录；它只写入新的目标，
  不再默认覆盖历史 artifact。没有改风险算法、特征公式、标签映射或分区算法。
- 新 exporter 将运行摘要与 contract/manifest 对齐，去掉内容身份中的生成时刻；验证 CSV
  顺序、来源、规则代理标签、split 行数、unknown 隔离、哈希和跨文件内容一致性。

### Preserved

- `risk_algorithm.py` 核心语义和 `demo_rules.json` 全部数值、原 24 项测试。
- 旧 `artifacts/pre_b_training_contract/` 原样保留；新旧 CSV 字节一致，审计 JSONL 记录一致
  （历史 Windows CRLF 与本机 LF 仅换行编码不同）。
- B_original 归档、physics_sim、ai_training、根目录 docs 均未修改。

### Tests

- 原 B 风险算法 `unittest`：**24 passed, 0 failed**。
- 新 B 适配 `unittest`：**18 passed, 0 failed**。
- 指定导入路径的联合 pytest（B 旧+新、C ai_training、physics_sim）：
  **179 passed, 20 subtests passed, 0 failed**。
- B_revised **9 个 Python 文件编译通过**；Contract JSON 校验与 fixture `--verify` 均实际执行。
- 默认一条命令生成新 fixture：`dataset_all=180`，`train=126`，`validation=27`，
  `test=27`，`excluded_unknown=18`；**10 个文件哈希已复算**。重复同目录导出被拒绝，
  相同 seed 新目录的 manifest 字节一致。
- 原 RiskEvaluator 三场景结果与原 sample_outputs.json 相同；源码及 demo_rules SHA-256
  与修改前一致。CSV 与历史 demo 字节一致。

### Assumptions / Waiting Items

- 本产物只支持规则模仿与框架冒烟测试，不是 Physics-inspired synthetic dataset。
- A 李青原仍需 Real Experiment CSV、Calibration Metadata、validity、run metadata。
- B 张鹏飞仍需正式 Feature/Label/Window/Split/Leakage/Normalization/Metrics/Synthetic Constraints
  和独立真实 Test 协议；真实传感器/物理参数为 TODO_CALIBRATION。
- C 何宇轩仍需实现与当前 `ai_training` 骨架匹配的显式 TEST_ONLY fixture reader，及以后正式版
  Contract Adapter；本次未开始训练、评价模型或导出 ONNX。
# B 数据接收阶段 1（2026-09-26）

- 新增 `data_intake/check_experiment_csv.py`：只读检查团队 v2 实验 CSV 的固定 20 列、有限数值、标签、缺测、逐 run 时间重复与倒退，并输出 SHA-256 和质量报告。
- 新增 `data_intake/README.md`：PyCharm 运行方式与 A → B 原始文件/元数据交接清单。暂不声明元数据或正式训练契约已就绪。
- 新增 3 项边界验证，均通过；测试行仅标作 `TEST_ONLY`。

# B 候选数学与交接边界（2026-09-27）

- 实验 CSV 初检增加逐 run、逐通道的 observed/missing/min/max；这些是原始码统计，不代表校准或可训练性。
- 新增 `candidate_features/reference.py`：相对重力夹角、因果时间斜率、已滤波动态加速度 RMS、逐探针相对湿度指标、探针均值/空间差、双 IMU 角度差。全部是候选数学原语，不冻结正式特征顺序/窗口/阈值。
- 新增 `docs/B_NEXT_STAGE_BOUNDARIES.md`：已确定的因果、分组、防泄漏、评价和合成来源边界，以及 A/B/C 仍须交接的数据和决策。
- 新增共享契约固定的评分外壳 `candidate_features/risk_math.py`，缺贡献时保持 unknown/null；新增 `docs/B_EXPERIMENT_PLAN.md` 供 A 记录首轮实验与证据。
- 修复旧适配测试在 Windows 默认 GBK 环境下读取 UTF-8 JSONL 的解码错误；测试逻辑与交付数据未改。
