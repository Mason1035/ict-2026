# PRE_B_TRAINING_CONTRACT v1.0

**Legacy TEST_ONLY 规则蒸馏来源包。**原名称与旧说明保留以便追溯；它不是 A 的交付，
也不是 B 已批准的正式训练契约。当前给 C 的规范入口是上一级
[`contracts/B_RULE_DISTILLATION_CONTRACT.json`](../contracts/B_RULE_DISTILLATION_CONTRACT.json)；
正式契约待办在 [`contracts/B_FORMAL_TRAINING_CONTRACT_DRAFT.json`](../contracts/B_FORMAL_TRAINING_CONTRACT_DRAFT.json)。
此目录原有四列/窗口/split 的“冻结”仅限 TEST_ONLY 规则模仿。完整历史细节见 [TRAINING_CONTRACT.md](TRAINING_CONTRACT.md)。

**PyCharm：** 用 PyCharm 打开本目录，选择 Python 3.11+，运行 `synthetic_dataset.py`。不需要安装第三方依赖。默认加载同级目录下 `../队员B_算法开发交付/risk_algorithm.py` 和 `demo_rules.json`，输出放在 `artifacts/pre_b_training_contract/`。

如 B 算法包位置不同，可设置 PyCharm Run Configuration 的 Script parameters：

```text
--algorithm-dir "E:\华为ict大赛\队员B_算法开发交付" --groups-per-class 60 --seed 20260925
```

输出包含 `train.csv`、`validation.csv`、`test.csv`、`dataset_all.csv`、unknown 排除台账、原始窗口审计 JSONL 和运行摘要。TEST_ONLY 模型输入只能由程序 `FEATURES` 指定的四列组成，不能把标注或节点/时间/电量元数据作为特征。

本包**不训练模型**。标签由 B 演示规则生成，只能验证/拟合规则行为；全部是非物理 TEST_ONLY 数据，不能解释成真实地灾样本或预测准确率。演示指标只在规则蒸馏范围内固定；正式 Metrics 等待 B。`model_metrics` 留空。历史默认输出路径已存在，直接再次运行会拒绝覆盖；用 `--output-dir <新路径>`，或使用上级 exporter。
