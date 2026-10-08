# B Rule-Distillation Contract

Contract ID: B_RULE_DISTILLATION_CONTRACT
Contract Version: 1.0-test-only
Status: TEST_ONLY

此文档解释同名 JSON；JSON 是程序读取的规范来源。Validator 只返回
`READY_FOR_TEST_ONLY_FRAMEWORK_SMOKE_TEST`，`formal_training_ready=false`。

目的仅为 **rule imitation / AI Training Framework smoke test**。合成样本来自 B 的演示
`RiskEvaluator.evaluate(history)`；不是 C physics_sim、A Real CSV、真实灾害标签或正式训练集。

`model_features` 的四列和顺序只用于本 fixture：

1. `soil_moisture_delta_pp`：当前三点末值减首值，演示百分点。
2. `soil_moisture_slope_pp_per_min`：当前三点时间回归斜率，演示百分点/分钟。
3. `tilt_median_deviation_deg`：当前倾角中位数减固定基线中位数，度。
4. `tilt_min_abs_deviation_deg`：当前三点相对基线绝对偏差最小值，度。

这不是正式 Ordered Features。标签 `label` 为演示规则代理：normal→0，attention/warning→1；
unknown→null，仅留 `excluded_unknown.csv`。一个生成 group 六条记录、一个窗口；按独立 group
在演示标签内切分，默认 70/15/15。此切分和指标定义仅服务 TEST_ONLY 规则复现。

`provenance_fields` 和 `forbidden_model_features` 在 JSON 中明确列出，且不与 `model_features`
重叠。部分来源在 CSV（group_id、sample_id、node_id、split），部分在 summary/manifest（规则
版本、seed、synthetic_source），原始窗口在审计 JSONL。scenario 只作为生成器内部来源，
没有导出为模型列；run_id、parent_run、parameter_hash 当前为 null，不伪造真实或物理身份。
teacher_risk_level、label_text、原因、设备/时间/电量、未来字段、failure_time 均禁止作为 X。

Artifact 目录内 `manifest.json` 的 `file_hashes` 覆盖 CSV、contract、summary 和审计文件；
`adapters/export_training_fixture.py --verify <dir>` 验证哈希、字段顺序、split、计数与 unknown 隔离。
同 config+seed 的 CSV/核心 JSON 内容确定；`summary.generated_at_utc=null` 表示它不参与内容身份。
已有输出目录不会被覆盖。正式模型指标未计算，`model_metrics=null`。
