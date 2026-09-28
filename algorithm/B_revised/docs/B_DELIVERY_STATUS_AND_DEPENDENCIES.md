# 队员 B 当前交付与下一次数据交接

核对时间：2026-09-28。范围是本仓库 `张鹏飞` 分支及只读检查的 `origin/李青原`、`origin/何宇轩` 分支；分支之外的个人设备或未提交材料不在判断范围。正式 Training Contract 仍为 `NOT_READY_FOR_FORMAL_TRAINING`。

## 已完成、可运行

| 对象 | 路径 | 当前用途与边界 |
|---|---|---|
| 旧演示 RiskEvaluator | `队员B_算法开发交付/` | 七字段规则演示及测试；不是正式 v2 风险实现 |
| 规则蒸馏 fixture / exporter | `adapters/`、`artifacts/rule_distillation_demo/`、`contracts/B_RULE_DISTILLATION_CONTRACT.*` | 只供 C 的 TEST_ONLY 接口冒烟，不是实测或正式训练集 |
| 正式 Training Contract Draft | `contracts/B_FORMAL_TRAINING_CONTRACT_DRAFT.*`、`contracts/validate_contract.py` | 可机读阻塞项，绝不通过改状态字串启用正式训练 |
| 实验 CSV 初检 | `data_intake/check_experiment_csv.py` | 固定 20 列、时间/标签/缺测/数值与逐 run 通道统计；不核定校准和真实性 |
| 候选特征与评分外壳 | `candidate_features/` | 数学参考与共享权重/等级边界；贡献映射、窗口、异常判定尚未标定 |
| 划分计划初检 | `evaluation/split_preflight.py` | 检查母 run 与合成来源泄漏；仅为拟议计划的结构审核 |
| 实验/交接文档 | `docs/B_EXPERIMENT_PLAN.md`、`docs/B_NEXT_STAGE_BOUNDARIES.md`、本页 | 首轮五类 run 的证据要求、防泄漏和下一次交接条件 |

独立包之间的测试在仓库根目录运行：

```powershell
python -m unittest discover -s algorithm/B_revised/tests -v
python -m unittest discover -s algorithm/B_revised -t algorithm/B_revised -p 'test_*.py' -v
```

旧七字段演示算法测试在 `algorithm/B_revised/队员B_算法开发交付` 目录运行 `python -m unittest discover -s tests -v`。不要将这些测试通过解释为真实山区预警能力验证。

## 下一步具体需要谁提供什么

| 来源 | 交付内容 | 建议交接位置/方式 | B 收到后做什么 |
|---|---|---|---|
| A 李青原 | 至少首轮 `run_001_normal`、`run_002_rain_light`、`run_003_rain_medium`、`run_004_vibration`、`run_005_small_slip` 的原始固定 20 列 CSV，并逐步增加独立重复 run；每个文件的 SHA-256 | 团队同意公开后可在仓库 `docs/experiments/<run_id>/` 留索引；原始数据先按双方约定的安全方式交接，不因本页自动公开 | 运行 CSV 初检、核对原文件与标签，再写逐 run 质量报告；没有重复 run 时不硬凑 Train/Validation/Test |
| A 李青原 | `device_id`/`boot_id`、`row_index→uptime`、逐通道实际采样时间和 validity/错误、固件与 ODR 切换、安装方向、量程/滤波、ADS1115 PGA、逐探针校准、实验操作与影像/人工标签区间 | 与对应 run 一起交付原始元数据；当前元数据文件结构未由三方冻结，先保留原记录和哈希 | 判断时间/采样率可信度、缺测/饱和/漂移；确认重启与缺口边界，形成可追溯 Feature Table |
| C 何宇轩 | 物理模拟 observation 与 metadata 的版本、参数/seed/parent_run、生成器输出和 Train 校准反馈；正式训练适配器接受的特征顺序、mask、shape、时间对齐与部署资源反馈 | C 分支的 `physics_sim/`、`ai_training/`，或三方交接文档；目前这些内容只在 C 分支，尚非 A 真实数据 | B 对照 A 的 Train 真实分布约束合成扰动；与 C 版本化对齐正式契约，不把模拟代理当正式特征 |
| A/B/C 共同 | 预测时间尺度、标注不确定区间、独立 Real Test 保管与最终评价流程、`reason_mask` 位号、设备端计算/延迟约束 | 先更新共享契约或正式三方决策，再同步代码 | 冻结 Feature/Window/Label/Split/Leakage/Normalization/Metrics/Synthetic Constraints 和 v2 风险参考实现 |

当前远端核对：`origin/李青原` 截至本次读取仅有项目基础文档，没有正式实验 CSV；`origin/何宇轩` 已有 `physics_sim/` 与 `ai_training/` 骨架，但其报告也明确 Real Data 与 B 正式契约待交接。这个仓库观察不等于断言两位队员未在其他地方开展工作。

## 收到 A 数据后的 B 顺序

1. 保留原文件与哈希，运行 `data_intake/check_experiment_csv.py`；对照设备日志人工复核错误，不覆盖原始 CSV。
2. 按 run/boot 和逐通道 validity 做质量报告、排除原因、对齐与校准审查；不从原始 ADC 猜体积含水率。
3. 在连续有效片段上比较候选特征与真实实验事件，确定窗口、过滤、覆盖率、物理贡献映射及缺失/降级策略；B 参考实现与 A 节点输出做黄金向量一致性检查。
4. 有足够独立重复 run 后先按 parent_run 分组并审核 split，再版本化发布正式 Training Contract；C 才能开发正式 adapter、训练和同一 Real Test 上的比较。

所有演示阈值和规则仍只用于演示，不得宣称为经过验证的地灾预测能力。
