# B 适配交付 Changelog

只记录本次实际改动，不重写 B_original 或早期验证历史。

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
