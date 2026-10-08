# 队员 B 代码实际用途核对（2026-10-02）

结论：**先前生成的代码各有用途，但没有全部进入正式 NODE→Atlas→训练链路。** 测试通过只证明对应模块的边界行为，不证明 A 已烧录、C 已训练或系统具备真实地灾预测能力。当前 E 盘的 `张鹏飞.zip` 与原 B→A 交接 ZIP 的 SHA-256 相同；它是接口设计预交接，不是可部署算法包。

| 路径 | 现在怎样被使用 | 尚未发生的集成 |
|---|---|---|
| `队员B_算法开发交付/risk_algorithm.py` | 旧七字段 `RiskEvaluator` 演示；被旧 `synthetic_dataset.py` 调用以生成规则蒸馏数据 | 不接正式 `zhifang.telemetry.v2`；不能移植演示阈值到 NODE |
| `智哨防灾_PRE_B_TRAINING_CONTRACT/`、`adapters/export_training_fixture.py` | 规则蒸馏 TEST_ONLY 数据/导出与复核 | 不是 A 真实 CSV、C physics_sim 或正式模型训练集 |
| `candidate_features/reference.py` | 被 `hardware_handoff/run_vectors.py` 和数学测试实际调用 | 尚未经 A 实测校准、固件移植与黄金向量板端对比 |
| `candidate_features/risk_math.py` | 被向量和测试调用，核对固定权重与四级分数区间 | 四项贡献映射、异常判据、reason 位表未冻结，不能产生可信现场 score |
| `candidate_features/causal_window.py` | 被其测试实际调用，提供显式参数的时间/boot/ODR/缺口参考 | 数值均为测试输入；A 尚未移植，正式 W/age/coverage 待标定 |
| `data_intake/check_experiment_csv.py` | 本地自测和手动 CLI 可执行，检查固定 20 列及可见质量问题 | 尚无 A 的原始 CSV 与校准/validity 侧表供真实运行 |
| `evaluation/split_preflight.py` | 手动审核拟议 run/parent_run 分区结构，TEST_ONLY 样例可运行 | 无独立真实 run 的正式 Split Manifest；结构通过不等于训练就绪 |
| `contracts/B_FORMAL_TRAINING_CONTRACT_DRAFT.*` | `validate_contract.py` 明确返回 `NOT_READY_FOR_FORMAL_TRAINING` | 正式 Features/Labels/Window/Split 等尚未冻结，C 不能据此宣称正式训练 |
| `hardware_handoff/` | 文档、不可加载配置草案、数学向量和 A 实验交接清单已打包 | A/C 尚未会签风险配置 Schema、LoRa 量化、C 接入 validator |

## A 现在能设计到哪一步

A 可据共享契约实现采样、持久身份、时间/validity、独立 Sensor/Feature/Risk/Alarm 状态、缓存与通信接口，并按 B 的纯数学函数和因果窗口参考搭建可替换计算模块。**A 不能依据此包冻结物理阈值、滤波系数、窗口时长、单传感器降级评分、reason_mask bit 或消警规则。** 无已批准配置时 `risk.sensor_score`、`risk.level`、`risk.reason_mask` 保持 `null`，故障状态另报；隔离 TEST_ONLY 注入须明确标记。硬件/通信/云接入仍依 A/C 各自权威接口。

## 阻塞信息

- 向 A 需要：五类真实 run（再逐步增加独立重复 run）的固定 20 列原始 CSV、SHA-256、`row_index→uptime_ms`/逐通道真实采样时刻与 validity、boot/ODR/安装坐标、双 IMU 与逐探针校准、ADS PGA、实验操作与人工/影像标签证据；同时需要 A 板端资源/量化精度、双 IMU 异步误差和采样/缓存压力测试结果。
- 向 C 需要：正式训练 adapter 所要求的特征形状/掩码/延迟与在线计算资源约束、物理模拟来源和参数/seed/parent_run、模型对真实缺测的反馈；接入侧 v2 validator、命令/receipt/视觉结果接口，以及 A/C 的 LoRa 量化评审结果。C 的训练结果只能在 B 正式契约和独立真实 Test 确立后用于风险阈值与增益评估。
- 三方还须确认预测时间尺度、独立真实 Test 保管、reason_mask 位表与配置 Schema。没有这些材料，B 不应填入看似合理的数值，也不能宣布 B3/B4 或 A 固件端到端验收完成。
