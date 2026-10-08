# B 划分计划初检（不执行训练）

`split_preflight.py` 检查拟议 `run_id`/`parent_run` 分组有没有跨 Train/Validation/Test、合成记录是否只进入 Train，以及其母 run 是否确实是 Train 中的真实 run。它接受 B 的**临时划分计划**，不生成 split、不读取特征、不检查独立真实 Test 的科学独立性，也不批准正式 Training Contract。

从仓库根目录运行明确标注的 TEST_ONLY 样例：

```powershell
python algorithm/B_revised/evaluation/split_preflight.py algorithm/B_revised/evaluation/TEST_ONLY_split_plan.json
python -m unittest discover -s algorithm/B_revised/evaluation -t algorithm/B_revised -p 'test_*.py' -v
```

输入 JSON 只要求 `entries` 列表，每项四个字段：`run_id`、`parent_run`（真实根 run 可为 `null`）、`split`（`train`/`validation`/`test`）和布尔 `is_synthetic`。这些是此工具的草案输入格式，**不是团队的正式采样 CSV、设备 Telemetry 或已批准的 Split Manifest**。真实计划必须先拿到 A 的 run 来源与重复实验元数据。若尚无独立真实 Test，工具会明确提示不能报告泛化结论。

程序返回 `STRUCTURE_CHECKED_ONLY` 只表示上述结构检查通过，`formal_training_ready` 始终为 `false`。`REVIEW_REQUIRED` 包含需要修复的条目与原因。正式 manifest 格式、真实 run 的独立性与分组，以及 C 的训练解释器须经 B/C 对接后另行版本化。
