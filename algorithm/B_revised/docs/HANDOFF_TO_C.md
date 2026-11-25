# B → C 上游交接说明

当前版本是可读的**接口交付**，正式训练状态 `NOT_READY_FOR_FORMAL_TRAINING`。
优先遵循仓库根目录 `00_TEAM_SHARED_CONTRACT.pdf`。B 的规则蒸馏旁路不能替代 C 的 physics_sim 或 A Real Data。

## C 现在可以读取

| 入口 | 用途 | 状态 |
|---|---|---|
| `../contracts/B_RULE_DISTILLATION_CONTRACT.json` | 唯一规则蒸馏 fixture Contract，明确 model_features/label/来源/禁用字段 | TEST_ONLY；validator 返回 `READY_FOR_TEST_ONLY_FRAMEWORK_SMOKE_TEST` |
| `../contracts/B_FORMAL_TRAINING_CONTRACT_DRAFT.json` | 正式契约待办和可机读状态 | DRAFT；validator 返回 `NOT_READY_FOR_FORMAL_TRAINING` |
| `../adapters/export_training_fixture.py` | 一条命令生成/校验 fixture | 只导出 TEST_ONLY，默认输出 `../artifacts/rule_distillation_demo/` |
| `../artifacts/rule_distillation_demo/manifest.json` | 文件哈希、字段、身份、行数、状态 | `formal_training_dataset=false` |
| `../队员B_算法开发交付/risk_algorithm.py` | 原始 RiskEvaluator | 核心行为/规则数值保持不变 |

用 `python algorithm/B_revised/adapters/export_training_fixture.py --verify algorithm/B_revised/artifacts/rule_distillation_demo`
检查已有 artifact；选择新的 `--output-dir` 可重复导出且不会覆盖旧结果。
`dataset_all.csv` 有四列 demo 模型特征和审计字段；三个 split CSV 各有相同四列、label 与 group 来源；
`excluded_unknown.csv` 不得用于监督训练；`synthetic_histories.jsonl` 只供来源审计。
必须按 JSON 的 `model_features` 显式选列。`provenance_fields` 和 `forbidden_model_features`
不得进入 X，包括 synthetic_source、scenario、teacher_risk_level、run_id、group_id、seed、
parameter_hash、parent_run、failure_time 和任何 future-derived 字段。某些来源只存在于 manifest/
summary，某些值如 run_id/parent_run/parameter_hash 当前为 null；不要补造。

## 仍不能用于正式训练

B 的四列、二元代理 label、六点窗口、70/15/15 split、metrics 与演示阈值，只属于 TEST_ONLY
规则蒸馏。它们不代表 B 对正式 Feature、Label、Window、Split 或 Metrics 的冻结。
历史 `../智哨防灾_PRE_B_TRAINING_CONTRACT/training_contract.json` 的 PRE_B/“frozen”命名已在
本次适配中降级为 legacy TEST_ONLY 解释，不能作为正式入口。

当前 C 的 `ai_training` 骨架并不会把 B 的一行四特征 CSV 直接视为已批准的 `[time, feature]`
正式样本；C 后续应实现一个**显式、仅 TEST_ONLY**的 B fixture reader/adapter。读取前核对
`contract.json`、`manifest.json`、文件哈希、feature order、label、split 和 forbidden fields。
正式路径另需 B 发布 versioned contract 后由 C 实现对应新版本 adapter，不能把测试模式改名启用。

## A/B/C 后续分工

- **A 李青原 — WAITING_FOR_A**：Real Experiment CSV、Calibration Metadata、逐通道 validity、
  run metadata、采样与时间/坐标证据。真实文件字段和缺测形态以正式交接为准，不从 demo 猜。
- **B 张鹏飞 — WAITING_FOR_B**：Formal Ordered Features（数学、顺序、单位、dtype、mask、坐标）、
  Formal Label、Formal Window、Formal Split Manifest、Leakage Rules、Normalization Contract、
  Metrics、Synthetic Constraints；确定独立真实 Test 和校准/质量要求。实际阈值标定为
  **TODO_CALIBRATION**。
- **C 何宇轩**：Dataset Adapter、AI Training Framework、Model Training、Evaluation、
  Real-only vs Real+Synthetic、ONNX 和未来 Ascend 部署。C 不得替 B 猜正式字段，也不把
  physics_sim 观测代理当作 B Feature Table。真实/合成最终比较必须用同一独立 Real Test。

正式链路：A Real Data → B Formal Training Contract → C Dataset Adapter / AI Training；
C physics_sim 的受控合成数据须按 B Synthetic Constraints/Train 来源校准后才能接入。
旁路：B Rule-Distillation Fixture → C Framework smoke test。两条来源和用途必须保持可追溯。
