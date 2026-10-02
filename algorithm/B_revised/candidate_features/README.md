# 候选特征数学参考实现（未冻结）

`reference.py` 只提供可在 PyCharm 中导入和单元验证的纯函数。它不读取实验 CSV、不生成正式 Feature Table，也不决定设备端参数。正式 `ordered_features`、窗口、坐标、有效性、滤波、采样对齐和版本仍在 `contracts/B_FORMAL_TRAINING_CONTRACT_DRAFT.json` 中保持未决。

| 函数 | 输入前提 | 输出含义 | 仍须 A/B 确认 |
|---|---|---|---|
| `gravity_tilt_change_deg` | 当前与基线重力向量，同一安装坐标 | 相对夹角（度） | 安装方向、静止基线、运动期是否可信；不是山体位移 |
| `causal_slope_per_second` | 严格递增的历史毫秒时刻和值 | 线性变化率（输入单位/秒） | 窗口、缺口、预热、有效样本数 |
| `dynamic_accel_rms_mps2` | 已按指定滤波产生的动态加速度 | RMS（m/s²） | 高通/重力去除方法、ODR、滤波延迟 |
| `relative_wetness_index` | 一根探针的原始码与该探针干/湿参考码 | 无量纲相对指标 | 探针逐支校准、ADS1115 PGA、稳定性；不是 VWC |
| `valid_probe_mean` / `spatial_probe_spread` | 同一尺度、同一有效窗口的探针指标 | 平均与有效路数 / 最大最小差 | 至少几路可用、位置解释、对齐 |
| `dual_imu_tilt_difference_deg` | top/toe 已对齐的相对倾角 | 双 IMU 差异（度） | 同步误差与一致性阈值 |

所有函数缺少必要输入时返回 `None`，不把缺测填 0；`relative_wetness_index` 不截断到 0–1，越界值应保留以供校准质量分析。`dynamic_accel_rms_mps2` 的输入**必须先**完成经验证的动态分量提取，不能直接把包含重力的加速度传入并称其为振动。

`risk_math.py` 只实现共享契约已固定的四项权重、0/5 双 IMU bonus 形式和等级区间。调用它之前必须由 B/A 基于实验确认四项 0–100 贡献映射、双 IMU 异常条件、降级策略；缺任一项就返回 `None`，不能把 `None` 当 `NORMAL`。`reason_mask` 位号仍未确定，模块不生成该字段。

从仓库根目录 `E:\华为ict大赛\ict-2026` 运行：

```powershell
python -m unittest discover -s algorithm/B_revised/candidate_features -t algorithm/B_revised -p 'test_*.py' -v
```

这些测试使用明确的数学样例；不是队员 A 的实测结果，也不是灾害预测验证。

`causal_window.py` 另提供**显式配置**的因果观测缓冲参考：`segment_key` 由调用方组合 run/boot/传感器/坐标/ODR/校准版本，任一改变即清空；时间倒退、长观测缺口、有效数据长缺口与数据过期均单独标记。测试中的毫秒数只为验证边界，正式窗口长度、最大年龄/缺口和最小有效样本数仍为 `TODO_CALIBRATION`。只有物理新观测调用 `add()`，不能把 CSV 高频行里的前向填充值重复送入。
