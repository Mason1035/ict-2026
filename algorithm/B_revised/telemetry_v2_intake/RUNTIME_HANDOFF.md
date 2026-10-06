# B Feature / Risk 计算内核交接 V0.1

2026-10-06。程序位于 `E:\华为ict大赛\ict-2026\algorithm\B_revised\telemetry_v2_intake`。
这次补齐截图中的计算路径，**正式标定和现场验收仍未完成**。现有 Telemetry v2 字段、A/C 分支和
正式 Training Contract 均未修改。内部原始观测批次是 B 的接口提案，须 A/B/C 确认后接入。

## 现在可以运行

在 PyCharm 打开仓库，使用 Python 3.11+，直接运行 `demo_runtime.py`，无第三方依赖。
从 PowerShell 运行：

```powershell
Set-Location -LiteralPath 'E:\华为ict大赛\ict-2026'
python -B -X utf8 algorithm/B_revised/telemetry_v2_intake/demo_runtime.py
python -B -m unittest discover -s algorithm/B_revised -t algorithm/B_revised -p test_runtime.py -v
```

终端输出三个完整 JSON 结果，包含逐路 Feature、窗口质量、贡献输入、四路贡献、共识奖励和阻塞原因：

| TEST_ONLY 场景 | 当前输出 | 含义 |
|---|---|---|
| 静止、湿润度稳定 | score=5，NORMAL | 人工数据/演示曲线下的软件计算结果 |
| 倾角变化、振动、湿润度上升 | score≈75.478，WARNING | 人工数据/演示曲线下的软件计算结果 |
| middle Soil 缺测 | score/level/reason_mask 均 null | 保守策略阻塞，不补零、不改权重 |

这三个输出不是灾害预测，也不是正式真实训练数据或阈值验收。`reason_mask` 在 TEST_ONLY 下始终 null。
示例生成器用于代码测试，不能代替 C 的 Physics Simulation 或 A 的真实实验。

## 已实现的映射和数学

| 阶段 | 代码行为 |
|---|---|
| IMU 原始映射 | top/toe 三轴含重力加速度，单位 m/s²；不消费未经核验的上报派生字段 |
| 重力候选滤波 | 首个有效向量初始化；`alpha=1-exp(-dt/tau)`；`g=g_prev+alpha*(a-g_prev)`；dt 为实际采样间隔 |
| baseline / tilt | 每路独立静止重力基线；用当前重力与基线夹角，单位 °；不等同于地表位移 |
| 动态振动 | `d=a-g`；窗口内 `sqrt(mean(dx²+dy²+dz²))`，单位 m/s² |
| 倾角趋势 | 同一窗口实际时间的最小二乘斜率，单位 °/s |
| Soil calibration | 逐探针 `100*(raw-dry)/(wet-dry)`；返回相对湿润度，不是 VWC；近零干湿差拒绝配置 |
| Soil 范围 | 保留未裁剪指数及超范围诊断；本版超出 0..100 即失效并阻塞，不静默裁剪 |
| Soil 均值 / 增长 | 三路有效且对齐才取均值；三根都更新后新增一个均值事件；按真实时间回归斜率乘 60，单位百分点/分钟 |
| contribution mapping | 单调折线 `[物理值,贡献值]`；端点外贡献饱和，值在 0..100；湿润度下降保留负特征，但上升风险贡献输入取 max(0,growth) |
| 聚合 | tilt/vibration 取双路最大值；moisture 用三路均值；growth 用上升斜率；这是待验证的本版候选策略 |
| consensus | 双路有效、时间对齐，均达到配置倾角门槛且角度差不超过配置上限，才加配置奖励（0 或 5） |
| Risk | 沿用共享契约 0.30/0.25/0.25/0.20、clamp 0..100、浮点评级 30/60/80；不先四舍五入 |

重力低通是可回放的**候选滤波方法**，尚未通过动态加速度干扰、安装漂移和硬件量化验证；本版未实现
陀螺互补融合。若实测证明需要替换滤波器，应升级 feature_version 并重新标定。不能把“有代码”称为
“已有验证过的滤波性能”。陀螺原值仍由上游保存，本算法不伪造其使用。

## 原始观测批次（内部 API，不进入 Telemetry JSON）

低频 Telemetry 快照没有足够的历史波形和逐路采样时刻，不能据此恢复 100/200 Hz 振动。
调用方先校验 Telemetry，然后从 NODE 原始采样缓冲/真实回放提取新增观测：

```python
from telemetry_v2_intake import evaluate_telemetry_v2
from telemetry_v2_intake.runtime import FeatureRiskRuntime

runtime = FeatureRiskRuntime(config)  # 同一节点生命周期内复用，不能每条消息重新构造
result = evaluate_telemetry_v2(payload, context={"runtime_input": batch}, runtime=runtime)
```

将 `algorithm/B_revised` 加入 PYTHONPATH。完整可运行输入见 `demo_runtime.fixture()`。
batch 形状如下；省略号表示需要填入实际值，不能直接发送：

```text
schema: B.observation_batch.v1
source: TEST_ONLY 或 REAL，必须与配置模式一致
identity: {site_id, device_id, boot_id}，必须对应当前 payload
run_id: 必须与 payload.experiment.run_id 相同，且非空
frame_id / calibration_version / odr_hz / sensor_ids: 必须与配置一致
imu:
  top / toe: [{uptime_ms: 实际毫秒, valid: bool, acceleration_mps2: [ax,ay,az]}]
soil:
  top / middle / toe: [{uptime_ms: 实际毫秒, valid: bool, raw: ADS 原始码或 null}]
```

每路列表按采样时间严格递增，不含未来点；一次可以提供多个真实新增观测，也可以为空。
只有完全相同的最后一条保持观测可重复传入，它不会新增窗口点。更早的历史须在新建的离线 runtime
按时间回放，不能混入当前在线状态。同一采样时刻内容不同会被拒绝。实际采样时刻使用单调时钟，
不使用接收时间代替；A 的微秒时刻转本接口整数毫秒前，须确认精度与双路对齐要求，不能私自取整。
Soil 扫描对齐和三路“都更新”规则仍需用 A 实测验证。

`sensor_ids` 逐路绑定物理传感器，`device_identity` 绑定该配置的节点。替换探针、安装坐标改变、
ODR 或标定改变必须换配置并重置。v2 Soil 没有逐路 validity；必须通过这个独立原始观测入口提供，
不能把 raw 非 null 推断为有效。A 当前 TEST_ONLY 的 Valid/Unavailable/Error 不能自动成为正式 bool 映射；
转换规则和错误原因侧表须另行确认。最新原始观测必须与 Telemetry 的原始快照对应，否则事务拒绝。

## Missing Policy 与状态

本版只实现 `REQUIRE_BOTH_IMU_AND_ALL_THREE_SOIL_V1` 候选保守策略。双 IMU 或三 Soil 任一路不足、
过期、时间不对齐、预热不足或窗口不足，Risk 为 null；不按剩余路数重新归一化权重。窗口为 `[t-W,t]`，
检查最少有效样本、最少时间覆盖、最大间隔、最新有效样本年龄。明确采样失效或长间隔会重建相应窗口；
Soil 扫描中的新旧值暂时未对齐不算一次新均值，不反复清空增长历史；完成新扫描后再检查对齐。
恢复后必须重新满足覆盖要求。同一节点的 boot/run、配置/标定/坐标/ODR 改变会重置。

只对当前最后一条 Telemetry 提供内存重复检测；重复保持上一结果，冲突/乱序不提交历史；已结束 boot
的补传不覆盖当前窗口。配置替换先完整校验，失败保留最后有效配置，成功切换重置窗口。调用方串行化
每个 runtime。持久去重、完整原始存储、补传历史回算仍由 A/C 接收链处理，这个对象不是数据库。

本内核不发报警、不处理网络送达、不清除已有现场报警。评分失效只表示无法提供新分数，不能据 null
解除 A 已锁存的高等级警报。故障、离线、风险等级和报警送达仍需由 A/C 分别管理。

## 配置加载与正式启用条件

`RUNTIME_CONFIG_DRAFT.json` 所有未标定参数保留 null，mode=DRAFT，加载会明确拒绝。
`demo_runtime.test_only_config()` 只用于演示。配置文件更新后用 `config_hash(config)` 计算规范化 JSON
的 SHA-256（排除 config_hash 自身）；它只检验完整性，**不验证物理正确性、签名或人工审批真实性**。

CALIBRATED 模式要求完整参数、validated_for_runtime=true、A/B/C 的真实 review_refs、正式 reason_mask_version
和无重复位号表，并且采样来源为 REAL。软件只做结构门禁；refs 的实际审批证据和采样真实性需要团队
人工核验，不能靠改布尔值或 source 标签把演示变成实测。
本轮没有交付 CALIBRATED 配置或会签记录，也没有创建任何正式 bit 编号。

reason 的候选语义 `*_CONTRIBUTION` 表示对应贡献大于零，不等于单路超过真实危险阈值；
DUAL_IMU_CONSENSUS 表示配置中的共识条件满足。正式位表、故障原因和滞回/解除策略须 A/B/C 会签；
若需要不同语义应升级机器契约和相关代码。本版 TEST_ONLY 不输出 reason_mask 数值。

## 下一份必须交接的材料

1. A：原始 100/200 Hz 双 IMU 与 2/5 Hz 三 Soil 实验 CSV；每路实际采样时刻、validity/错误原因，
   run/boot、ODR、量程、安装坐标、传感器物理 ID 和校准版本；静止、倾斜、振动、湿润和故障恢复重复实验。
2. A：两路静止重力基线、每根探针干湿参考和有效范围、同步偏差实测；不能只给接口 MOCK 截图。
3. B 后续：用真实 Train 实验选择滤波、窗口、增长/共识条件和贡献曲线，记录误差、误报、漏报及独立 Test；
   发布正式参数与模型特征契约，保持训练数据隔离和版本追踪。
4. A/B/C：会签原始观测批次转换、reason bit 表、设备数值容差及报警滞回/清除。A 需要更新其 hash 固定的
   联调 manifest 才会执行新提交；现有固定旧 commit 的联调不会自动验证本轮 runtime。
5. C：后续提供真实模型/ONNX 及其 Feature Contract、训练与独立评价记录；这不是本轮规则内核运行前提。

当前独立软件工作到此可运行；缺上述实测材料时停止发布正式标定值。Edge Intake、持久化、Atlas、MQTT、
Cloud、Web/AI/视觉由 C 推进。CodeArts 使用与部署须保留真实操作记录，本轮仅为 Codex 本地代码实现。
