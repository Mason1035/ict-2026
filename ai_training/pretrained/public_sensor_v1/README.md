# Public sensor research models v1

2026-10-19 在CPU实际拟合，配置为`training_config.json`。两个JSON包含已训练权重及训练集标准化参数。
原始数据来自真实公开实验，不含项目NORMAL/RAIN/SLIP标签，也没有自采沙盘数据。

| 模型 | 数据与实际使用 | 评价范围 |
|---|---|---|
| `soil_model.json` | LISA读入68条位置序列/1,102次观测，44条序列足够构造4点历史窗口；Train 608窗、Validation 104窗、探索性Test 144窗 | 日期/明确连续试验分组，25/5/6组；Validation选择alpha=1.0。预测下一记录的VWC体积比，不是固定时间提前量。 |
| `motion_model.json` | Smartstone四颗石子/2,001次观测，8点历史构造1,969训练窗；固定alpha=0.1 | 只有一个物理实验，全部拟合，Validation/Test为空；不提供独立泛化或分类准确率。 |

土壤探索性留出RMSE：模型 **0.016925**，保持上一观测的基线 **0.018138**（VWC体积比）。
这是公开来源组上的下一观测回归结果；留出集在开发时检查过，不是锁定的确认性本地Test，
不证明本地B方案优于A方案，也不表示滑坡预警准确率或提前量。
详细逐通道指标、分组、缺测/隔离及来源见`report.json`、`split_manifest.json`。

LISA中心实验47含36条10.30–33.49的值，与VWC体积比声明冲突。整条位置序列被隔离，
未猜测除100、未截断数值、未修改原始CSV。报告保留源记录范围；表级隔离审计统一保存于`source_table_audits`，避免重复统计。
初始混合尺度试训结果保留在本地ignored work目录，未作为本版模型发布。

使用与重跑见 [MULTIMODAL.md](../../MULTIMODAL.md)。模型加载只读JSON，不使用pickle；
预测须匹配有序通道、物理单位/原生单位与时间语义。禁止把本地ADS原始码当成VWC输入，
或把来源原生IMU值默认为已验证的本地m/s²和°/s。
两个预测器没有告警阈值，未直接接入规则融合状态或生产风险引擎。

来源署名：LISA — Longoni、Scaioli、Panzeri、Arosio、Corti、Hojat、Papini，
[DOI 10.7910/DVN/0H4AVF](https://doi.org/10.7910/DVN/0H4AVF)；
Smartstone — Dost、Gronz、Casper、Krein，
[DOI 10.5281/zenodo.4316597](https://doi.org/10.5281/zenodo.4316597)。
两来源均为[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)。本目录为子集清理后拟合的派生产物，继续分发时保留来源与改动说明。
