# B 下一阶段边界与待交接项

状态：`NOT_READY_FOR_FORMAL_TRAINING`。本页整理两份正式 PDF 已能确定的原则，以及必须等待真实实验/团队确认的参数；不修改团队 CSV 或设备 Telemetry 接口。

## 已可执行的规则

- **因果性**：样本窗口只取 `[t-W,t]`；按 boot/run 连续片段处理。不能跨重启、换装、校准版本切换、明显时钟倒退或缺口拼接。离线零相位滤波和全序列统计不能用于声称实时可用的模型输入。
- **来源与泄漏**：`run_id`、`parent_run`、`device_id`、`boot_id`、`label_source`、`is_synthetic`、时间到事件、未来事件信息等只作审计/切分，不作为模型 X。窗口、频谱帧、增强及合成后代继承母 run 的分组。先按组划 Train/Validation/Test，再拟合归一化、标定或生成增强；Test 不参与拟合和调参。
- **标签边界**：实验标签 `NORMAL`/`RAIN`/`SLIP` 与设备风险等级 `NORMAL`/`WATCH`/`WARNING`/`EMERGENCY` 是两套概念。模糊事件区间留空/unknown；SLIP 需可追溯的受控实验或人工/影像确认，不能由传感器突变自动回填。
- **原始与派生分离**：原始实验 CSV 保留不覆盖；清洗/过滤/特征计算另生版本化产物，记录原文件哈希、行范围、run/boot、校准与特征版本、有效路数、缺测和排除原因。大幅变化不能无证据地删除为噪声。
- **指标口径**：正式报告按 run 和通道给出缺测、无效、饱和、漂移、采样间隔与时间可信度；分类给出混淆矩阵、各类 precision/recall/F1 与 PR；事件级给出召回、每观察小时误报数和提前量；另报缺测/失联鲁棒性及运行代价。没有独立真实 Test 时只标探索性结果，不报泛化准确率。
- **合成数据**：保留 `is_synthetic`、生成器/参数版本、种子、母 run、校准来源。只用 Train 中真实分布确定物理范围与扰动；同一独立 Real Test 上比较 Real-only 与 Real+Synthetic；合成数据不得进入独立 Real Test，也不得靠结果反调 Test。

## 仍需真实交接或三方确认

| 待办 | 所需输入/决策 | 负责人 |
|---|---|---|
| 实验数据与时间可信度 | A 的五类 run 及重复 run 的原始 CSV、SHA-256、row_index→uptime、每通道实际采样时刻/validity、boot 与 ODR 变化记录 | A |
| 校准和坐标 | 双 IMU 安装方向、量程/ODR/滤波与基线；三探针各自干湿/深度/ADS1115 PGA；Flow 计量 | A 采集，B 复核 |
| 特征正式版本 | ordered features、公式、单位、dtype、mask、有效性、对齐和多传感器降级策略 | B，依赖 A 数据 |
| 窗口与目标 | W/stride/预热/缺口/覆盖率/延迟、标签有效区间和预测时间尺度 | B，依赖实验与团队应用目标 |
| 分组 manifest | 足够独立重复 run 后按 parent_run 划分 Train/Validation/独立 Real Test | B，依赖 A 的 run 来源 |
| 归一化与合成边界 | Train-only 统计量、物理扰动范围及真实性审核 | B，依赖 A 实测；C 执行合成/训练 |
| 部署验证 | B 的离线参考与 A 节点输出一致性、C 的数据适配和延迟/资源反馈 | A/B/C |

当前五个首轮 run 足以做流程检查和探索性分析，不足以单独证明泛化；不得为凑齐划分而把同一 run 的相邻窗口拆到不同集合。`reason_mask` 位号仍为 TBD-12；正式 score 贡献映射和物理阈值仍为 `TODO_CALIBRATION`。
