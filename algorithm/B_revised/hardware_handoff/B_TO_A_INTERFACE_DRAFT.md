# B → A Feature / Risk 接口草案

**性质：待 A/B/C 会签的模块边界，不新增或修改 `zhifang.telemetry.v2` 字段。** A 负责人文档第 6 节要求 B 提供 Filter/Formula/Window/Missing/Score、`reason_mask`、`risk_config` 和黄金向量。当前只有共享契约中明确冻结的评分外壳与等级区间、以及候选数学原语可供实现；其余必须留未配置。

## 1. 输入与时间

- NODE 采样侧向 Feature Engine 提供每路观测的 `boot_id`、单调 `uptime_ms`、可选可信 UTC、实际采样时刻、单位、传感器身份、validity/错误码、ODR/滤波/量程/校准版本。此处是**模块设计建议**，不是核心 Telemetry 新字段；原始记录及 CSV/侧表格式按 00 第 6、11 节。
- IMU 加速度以 m/s²（含重力）、角速度以 °/s；土壤输入保留 ADS1115 原始码。探针未逐支标定时 `_pct` 为 `null`，不得叫体积含水率。`flow_lpm` 只在实验 CSV / rain 状态中，不加入核心 Telemetry。
- Feature/Risk 以 20Hz 固定调度；窗口按真实毫秒时长，不按固定点数。只能读当前及过去观测；不跨 `boot_id`、重装、校准版本、ODR/坐标变更或未处理的缺口拼接。UTC 未同步时 `timestamp_ms=null`、`time_synced=false`，仍用单调时间做同一 boot 内运算；不伪造跨 boot 时序。
- Soil/flow 低频采样只在新观测到达时写原始行。因果保持的最大允许年龄、异步双 IMU 对齐误差、窗口长度、滤波重置/预热、最少有效样本均 `TODO_CALIBRATION`。过期值必须失效，不能无限保持或当新采样。

## 2. 候选特征（数学实现见 `candidate_features/reference.py`）

| 输出候选 | 参考函数或公式 | 前提与当前状态 |
|---|---|---|
| 相对倾角变化（°） | `gravity_tilt_change_deg(current, reference)` | 同一安装坐标、静止重力基线和运动期有效性待 A/B 验证；不是山体位移 |
| 倾角变化率（°/s） | `causal_slope_per_second` | 只用严格递增的历史毫秒时刻；窗口和缺口规则待标定 |
| 动态振动 RMS（m/s²） | `dynamic_accel_rms_mps2` | 输入必须先有经验证的去重力动态加速度；高通/滤波参数尚未定 |
| 逐探针相对湿润度指数 | `relative_wetness_index(raw,dry,wet)` | 干湿参考须逐支、逐校准版本；函数输出无量纲，原值越界不静默截断；用于 Telemetry `_pct` 的 0–100 映射/有效范围还须批准 |
| 有效探针均值/空间差 | `valid_probe_mean`、`spatial_probe_spread` | 仅在同尺度、同有效窗口下计算；可用路数显式返回 |
| 双 IMU 相对差 | `dual_imu_tilt_difference_deg` | 对齐/一致性阈值待标定；不足双 IMU 不加共识奖励 |

参考函数返回 `None` 表示无法计算；`None` 不能变成数值 0。参考实现不声称已有完整滤波器、生产窗口或物理异常检测。A 可以先实现采样、缓冲、时间与有效性、模块接线和原始上报，待 B 发布正式参数再启用评分。

## 3. Risk Runtime 最小状态输出

共享契约固定：`sensor_score = clamp(0.30*C_tilt + 0.25*C_vibration + 0.25*C_moisture + 0.20*C_growth + consensus_bonus, 0, 100)`；四贡献均须已验证且在 0–100。双 IMU 同时异常时的 5 分奖励只是可配置初值，异常判据未定；无法确认时**不得自行加 5 分**。`risk_math.py` 在贡献缺失时返回 `None`，不重归一；这只是当前保守外壳，未来降级策略须经 B 版本化确认。

浮点评级：`[0,30)` NORMAL、`[30,60)` WATCH、`[60,80)` WARNING、`[80,100]` EMERGENCY；先分类再四舍五入供页面显示。无有效 score 时 `level=null`，绝不当 NORMAL。风险、传感器故障、通信在线、Alarm 送达/本地触发是不同状态。已触发的本地高危报警不因传感器掉线或视觉/NPU/云故障自动取消；清除/滞回策略待 B 标定。

`reason_mask` 位号未发布，正式输出保持 `null`，不能用 0 伪装“无理由”。A 的固件可为字段预留类型与序列化位置，但不要私定 bit。配置对象必须在加载前验证版本、完整性哈希、类型/范围和校准版本；缺任何 `TODO_CALIBRATION` 参数时拒绝“可运行评分配置”。保留最后有效配置且记录拒绝原因，不能半更新。`RISK_CONFIG_DRAFT_NOT_LOADABLE.json` 专为接口设计，**不可加载到实机**。

## 4. 回放/HIL 验收入口

- 数学向量：执行 `python run_vectors.py`；A 的 ESP32 相同输入与 B 输出应在**后续确定的量化容差**内一致，不能自行写死容差。
- 状态向量：缺配置、单/双 IMU 故障、Soil 不足有效路、ODR/boot 切换、长缺口、校准切换、score 边界、断网本地报警都要记录输入哈希、固件/配置版本、预期与实际。正式测试向量必须由真实数据和参数补充。
- 接口版本变更由 B 发布并让 A/C 会签。任何新字段或 `reason_mask` 位号先更新共享契约/专门版本化机器契约，不能只改固件私有结构。
