# 队员 B 适配交付（供 C 对接）

本目录把既有两份 B 交付分成三个明确层次：**演示 Risk Algorithm**、**规则蒸馏 TEST_ONLY fixture**、
**正式 Training Contract Draft**。当前正式训练状态为 `NOT_READY_FOR_FORMAL_TRAINING`。
项目契约优先级为仓库根目录 `00_TEAM_SHARED_CONTRACT.pdf`，随后是 `docs/reference/` 下的 A/B/C 负责人文档。

| 对象 | 所在位置 | 当前用途 | 不能推断的事情 |
|---|---|---|---|
| B Risk Algorithm | `队员B_算法开发交付/risk_algorithm.py` + `demo_rules.json` | 保留原 `RiskEvaluator` 三字段输出与演示阈值 | 真实危险阈值或灾害预测能力 |
| B Rule-Distillation Fixture | `智哨防灾_PRE_B_TRAINING_CONTRACT/synthetic_dataset.py`，由 `adapters/export_training_fixture.py` 导出 | 规则模仿/框架冒烟测试；四列和二元代理标签只在此范围有效 | 正式 Feature/Label/Window/Split 或物理合成数据 |
| B Formal Training Contract Draft | `contracts/B_FORMAL_TRAINING_CONTRACT_DRAFT.json` + `.md` | 程序可读的待交付清单，返回 NOT_READY | B 已冻结正式训练契约 |
| A Real Data | A 后续交接 | Real Experiment CSV、Calibration Metadata、validity、run metadata | 当前已存在可训练 Real 数据 |
| C Physics Simulation | C 后续交付，当前分支尚无 `physics_sim/` | 独立的 Physics-inspired synthetic observation | B 规则蒸馏 fixture 等于 physics_sim |
| C AI Training | C 后续交付，当前分支尚无 `ai_training/` | 训练基础设施；后续消费 B 契约 | 本目录已训练正式模型 |

## 对接入口

- B 下一阶段的真实实验 CSV 初检见 [`data_intake/README.md`](data_intake/README.md)：严格校验 v2 的 20 列并生成质量报告；此步骤不意味着正式训练就绪。
- 候选特征原语与未决参数见 [`candidate_features/README.md`](candidate_features/README.md)，数据泄漏、评价及下一次交接边界见 [`docs/B_NEXT_STAGE_BOUNDARIES.md`](docs/B_NEXT_STAGE_BOUNDARIES.md)。
- 拟议 run 划分的防泄漏结构预检见 [`evaluation/README.md`](evaluation/README.md)；它不会批准正式训练。
- 当前已交付内容、A/C 所需输入和收到数据后的顺序见 [`docs/B_DELIVERY_STATUS_AND_DEPENDENCIES.md`](docs/B_DELIVERY_STATUS_AND_DEPENDENCIES.md)，真实实验质量记录模板见 [`docs/B_QUALITY_REPORT_TEMPLATE.md`](docs/B_QUALITY_REPORT_TEMPLATE.md)。
- 发给 A 的首轮实验与交接方案见 [`docs/B_EXPERIMENT_PLAN.md`](docs/B_EXPERIMENT_PLAN.md)。
- 先阅读 [`docs/HANDOFF_TO_C.md`](docs/HANDOFF_TO_C.md)。
- 程序读取 [`contracts/B_RULE_DISTILLATION_CONTRACT.json`](contracts/B_RULE_DISTILLATION_CONTRACT.json)
  进行 TEST_ONLY 接口联调；读取
  [`contracts/B_FORMAL_TRAINING_CONTRACT_DRAFT.json`](contracts/B_FORMAL_TRAINING_CONTRACT_DRAFT.json)
  判断正式训练阻塞项。不要把旧 `training_contract.json` 当成正式项目契约。
- 运行 `contracts/validate_contract.py` 可得到机器可读 readiness；`READY_FOR_TEST_ONLY_FRAMEWORK_SMOKE_TEST`
  **绝不等于** `READY_FOR_PRODUCTION_TRAINING`。
- 一条命令由 `adapters/export_training_fixture.py` 导出 `artifacts/rule_distillation_demo/`。
  C 只读该目录内的 `contract.json`、`manifest.json` 和 CSV，无需阅读生成器内部。
- `model_features` 是唯一允许的 demo X 列顺序；`provenance_fields`、`forbidden_model_features` 和
  `label_name` 分开。CSV 的所有数值列不得自动选入 X。`excluded_unknown.csv` 不进入监督集。

## 命令（从仓库根目录）

Python 3.11+，本适配层只用标准库。首次在干净目录导出：

```bash
python algorithm/B_revised/contracts/validate_contract.py algorithm/B_revised/contracts/B_RULE_DISTILLATION_CONTRACT.json
python algorithm/B_revised/contracts/validate_contract.py algorithm/B_revised/contracts/B_FORMAL_TRAINING_CONTRACT_DRAFT.json
python algorithm/B_revised/adapters/export_training_fixture.py
python algorithm/B_revised/adapters/export_training_fixture.py --verify algorithm/B_revised/artifacts/rule_distillation_demo
```

**当前仓库已经包含本轮生成的示例目录。**重复导出时默认路径会明确报错，避免覆盖；请选择新目录：

```bash
python algorithm/B_revised/adapters/export_training_fixture.py \
  --output-dir algorithm/B_revised/artifacts/rule_distillation_demo_repeat
```

原算法 24 项：在 `队员B_算法开发交付/` 内运行 `python3 -m unittest discover -s tests -v`。
新增接口测试：在仓库根目录运行
`python -m unittest discover -s algorithm/B_revised/tests -v`。
新增 CSV/候选特征测试：在仓库根目录运行
`python -m unittest discover -s algorithm/B_revised -t algorithm/B_revised -p 'test_*.py' -v`。
实际结果见 [CHANGELOG](CHANGELOG.md)。

## 数据和职责边界

真实主线是 A Real Experiment Data → B 正式 Contract/Feature Table → C Dataset Adapter / AI Training；
C 的 physics_sim 合成观测在真实 Train 校准和 B Synthetic Constraints 后才可受控接入。
B Rule-Distillation Fixture 是独立旁路，只验证规则复现与软件接口。规则的湿度/倾角演示数值未经
真实实验标定，Soil 百分点不等于真实体积含水率 VWC。

A 李青原负责采集、Real CSV、校准和 validity；B 张鹏飞负责正式 Feature/Label/Window/Split、
泄漏规则、归一化、Metrics 和 Synthetic Constraints；C 何宇轩负责 Adapter、训练/评价执行、
Real-only 与 Real+Synthetic、ONNX 和未来昇腾部署。B 演示 fixture 的 `train/validation/test`
只是同一规则生成器内的 **TEST_ONLY_GROUP_SPLIT**，不等于独立真实 Test。

历史目录中的 `TRAINING_CONTRACT.md`、`training_contract.json` 和旧 `artifacts/pre_b_training_contract/`
保留作来源审计；其“冻结”仅限规则蒸馏示例，旧产物未改写。正式项目契约需 B 后续版本化批准。
