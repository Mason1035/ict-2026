# 阶段 I WP3：PROVISIONAL v1 研究规则执行器

输入只接受 WP2 `register_session()` 返回的 `research-raw-session-v1`；实现不读 CSV，不调用旧推理/接收入口，不连接平台数据库。原始解析、三件套校验、登记身份和五通道语义见 [WP2 协议](sd_replay_analysis.md)。只使用 Python 标准库，运行于 CPU。

输出固定 `scope=RESEARCH`，输入仍保留 `REAL / TEST_ONLY / sd_replay`；`risk_eligible`、`fusion_eligible`、`production_alarm_eligible` 全部为 false。不输出概率、雨量或土壤含水率；土壤只报告原始 ADC 码及相对变化，符号不解释为变湿/变干。`NO_TRIGGER` 不代表边坡安全。振动永远只产候选时段，包括单独出现、双 IMU 同时出现的情况。

## 冻结来源、公式与版本

唯一冻结来源为完整 experiment_id `NODE01-2e379f02688fd631-N0000005.CSV` 且类型为 `post_rain_static` 的 R4。雨场、改类型的 R4、其他静态身份均拒绝冻结；R4 有错误、长缺口或未建立基线时也拒绝。R4 是雨后静置参考，不是干土或已标定参考。

已冻结配置为 [provisional-v1-r4.json](../../platform_backend/config/research_rules/provisional-v1-r4.json)，契约为 `research-rule-config-v1`，方法为 **PROVISIONAL-v1**。每通道记录来源 experiment_id、方法版本、各指标统计数量、中位数、MAD、线性插值 p95/p99、最大值和冻结值；配置根节点记录生成时间、三件套 SHA-256、适配器版本、登记身份、全部窗口参数及临时原因位表。

统计对有限指标的**绝对值**进行，至少 20 个值：

```text
frozen_value = max(abs(R4 feature)) + max(6 × 1.4826 × MAD(abs(R4 feature)), minimum_margin)
```

采用覆盖 R4 已见最大值并留稳健余量的保守方法。角度/角速率/相对变化/STA-LTA 的最小余量为 1e-6，振动 RMS 为 1e-9 m/s²，能量为 1e-12 (m/s²)²，ADC 相邻差为 1 码，ADC 码变化率为 1e-6 码/秒。LTA 分母下限为该 IMU R4 有效 LTA 能量中位数的 0.1 倍与 1e-12 的较大者。先以固定下限计算 R4 能量，登记下限后再次用同一 R4 计算最终特征；不读取任何雨场统计。AIN2 相邻差门限包含起始基线期间的相邻差。

这是临时工程规则，没有测得通用地灾阈值。R4 自检属于同源自检，零触发由上述包络方法保证，不能作为独立误报率验证。任务书试跑摘要的方向角和土壤变化数值没有作为常量硬塞进执行器；本实现的 EMA、10 秒基线和相对变化分母定义如下，报告给出本口径重算值。

配置内容用规范 JSON 的 SHA-256 绑定（排除 `config_sha256` 自身）。执行器只读并复制配置；CLI 对所有输出使用独占创建，已存在的配置/报告不会覆盖，输出也不能位于输入场次目录。改变配置需要另立审阅产物，结果绑定新的内容摘要。当前 B 的方法和位表未交付；以后在同一配置契约内替换阈值、窗口参数、版本和 reason 映射即可，不需要更改执行器。未来冻结方法的生成工具由其方法另行实现，当前冻结器只支持上述 R4 PROVISIONAL 方法。

## 因果窗口和质量中断

每次运行独立创建每个 sensor_id 的状态，不跨通道、会话或回放共享缓冲。时间只取 WP2 `relative_time_us`，不使用处理速度或登记时间；不重采样、不插值、不补零。

| 项目 | 已冻结口径 |
| --- | --- |
| 初始参考 | 各通道第一条有效 acquired 观测起的 10 秒；仅使用截止时刻之前的样本，收齐后才可输出依赖基线的指标 |
| IMU 参考方向 | 上述窗口三轴加速度分别取中位数，形成固定初始向量；不积分为绝对姿态或位移 |
| IMU 重力估计 | `g_i = exp(-dt/1s) * g_(i-1) + (1-exp(-dt/1s))*a_i`，每个真实样本更新 |
| 方向角 / 变化率 | `atan2(norm(g × reference), dot(g, reference))`；相邻评估方向角之差除以真实时间差，单位 °、°/s |
| 动态振动 | `a_dyn=a-g`；最近 2 秒能量均值的平方根为 RMS |
| STA/LTA | 最近 1 秒能量 / **STA 之前** 10 秒能量，LTA 使用登记下限；不将 STA 混入 LTA |
| 时间加权 | 前一观测值左保持，按微秒区间积分；当前能量不能倒填过去区间；未覆盖完整窗口不输出 |
| 覆盖与长缺口 | IMU 数量覆盖至少 90%（预期间隔 10ms），相邻间隔 >30ms 立即中断；土壤 >1.5s 中断 |
| 评估频率 | IMU 至少间隔 0.25 秒，选实际新样本时刻；土壤在每条新观测评估；错误立即处理，不等待步长 |
| 土壤基线 | 起始 10 秒可用处理副本的 ADC 中位码；AIN0/1 原值，AIN2 使用副本上的因果后向 5 点中位数，不用居中滤波 |
| 土壤相对变化 | `(filtered_ADC - baseline_ADC) / abs(baseline_ADC)`，无量纲 fraction；另报相邻 filtered_ADC 的码/秒变化率 |
| AIN2 防护 | raw 相邻差超出 R4 冻结门限时记 `AIN2_ADJACENT_JITTER_GUARD`，立即中断该通道判定的持续时间；副本的中位滤波仍需全 5 点，不覆盖 raw |

错误行、缺值、缺时间、时间回跳/重复、长缺口或零加速度向量会立即清本通道动态窗口及待触发持续时间。初始参考收集被中断则该场保持 `INSUFFICIENT_BASELINE`，不悄悄改选后段基线；已经建立的初始参考在后续缺口后保留，动态窗口重新预热。合法 ADC=0 仍保留；若起始 ADC 基线为 0，则相对变化未定义，禁用该通道事件，不用虚构分母。

保留会话/通道 `UNCALIBRATED`、`AIN2_JITTER_REVIEW`、`POST_RAIN_NOT_DRY_BASELINE`、固件仅声明等标记。上述复查标记不删除原始观测；AIN2 的滤波和门限防护为显式策略。缺测和长缺口不能靠通道复查标记被掩盖。

## 判定、时段和临时 reason 位表

| 研究分类 | 进入条件 | 连续时长 | 结果资格 |
| --- | --- | --- | --- |
| `RELATIVE_ORIENTATION_CHANGE` | 本 IMU 方向角大于本通道 R4 冻结值 | ≥3 秒 | 研究事件 |
| `SOIL_ADC_RELATIVE_CHANGE` | 本路 ADC 相对变化绝对值大于冻结值 | ≥3 秒 | 研究事件 |
| `VIBRATION_CANDIDATE` | 本 IMU RMS 与 STA/LTA **同时**大于各自冻结值 | ≥1 秒 | 永远是候选，`triggered=false` |
| `SIMULTANEOUS_CHANNEL_CHANGE` | 至少两个独立非振动通道事件的已确认区间重合 | 已确认交集 | 只描述同时变化，不推断因果或滑移 |

倾角变化率、ADC 码变化率、角速度 RMS、LTA 能量均产出统计/峰值，不单独触发。恢复门限是进入门限的 0.8 倍，连续低于恢复门限 ≥1 秒关闭；错误/防护/缺窗口立即中断，不等待恢复时间。持续计时只靠实际新样本时刻。

每个时段含：`start_us`（连续越限开始）、`confirmed_at_us`（首次满足持续条件的时刻）、`end_us`（最后有支持证据的时刻）、关闭报告时刻/原因、峰值、冻结值、通道贡献、原因码和 mask。合并同时变化只用 `confirmed_at_us..end_us`，避免将确认决定倒写到起点；瞬时交点不另产多通道时段。场尾关闭标为 `SESSION_END`，不推断后续恢复。

`run_rules(..., include_features=True)` 还返回每条评估点的原始行号、acquisition_index、质量、特征及各规则的 `rule_decisions`，其中包含当前持续时长、状态、确认时刻和原因 mask。该逐点轨迹满足严格前缀一致；离线时段摘要的末端和峰值会随后续证据延长，不能把摘要当作过去已发布的决定。无特征的 warmup/invalid 点不以 0 代替。

**PROVISIONAL-platform-reason-v1-awaiting-B**，以下是平台内部临时位，绝不作为生产 risk_config 或固件 reason_mask：

| 原因码 | 临时值 |
| --- | ---: |
| ORIENTATION_IMU_TOP | 1 |
| ORIENTATION_IMU_TOE | 2 |
| SOIL_TOP | 4 |
| SOIL_MIDDLE | 8 |
| SOIL_TOE | 16 |
| VIBRATION_IMU_TOP | 32 |
| VIBRATION_IMU_TOE | 64 |

位值来自配置并验证为不同的 2 的幂。错误/缺口/抖动防护使用 `quality_flags` 和 `diagnostic_counts`，不冒充上述事件位。逐通道 `state` 为场次摘要（有事件则 TRIGGERED，否则曾有有效窗口则 NO_TRIGGER）；`last_feature_state` 和各状态计数另外描述质量，不把摘要当作实时当前态。

## CLI 与复验

仓库根目录执行，登记库和输出均置于原件之外；不会启动平台、MQTT 或硬件服务。原件可用 WP2 的 `--csv` 选定。

```bash
# 复验冻结应写一个新文件，不覆盖已冻结配置。
PYTHONPATH=platform_backend/src python3 -m geohazard_platform.research_rules freeze \
  "$HOME/Desktop/ICT-2026/数据/2026-11-02重测与无雨300秒/300s不降雨测试" \
  --registry "$PWD/work/stage1-wp3/research.sqlite3" \
  --output "$PWD/work/stage1-wp3/refreeze-review.json"

PYTHONPATH=platform_backend/src python3 -m geohazard_platform.research_rules run \
  "$HOME/Desktop/ICT-2026/数据/2026-11-02重测与无雨300秒/相同降雨量/50档pwm" \
  --type rain_50 --registry "$PWD/work/stage1-wp3/research.sqlite3" \
  --config platform_backend/config/research_rules/provisional-v1-r4.json \
  --output "$PWD/work/stage1-wp3/rain_50-review.json"

PYTHONPATH=platform_backend/src python3 -m unittest discover \
  -s platform_backend/tests -p 'test_research_rules*.py' -v

# Python 3.11+，已有平台开发依赖的环境运行完整回归。
python3 -m pytest platform_backend/tests
```

freeze 入口在写配置前执行 R4 零事件、零候选自检，失败拒绝写出。成功退出 0；校验失败或已有输出返回 1 和 stderr JSON。执行器无运行时随机数/当前时间，规范 JSON 排序固定；同一登记输入与配置运行两次逐字节相同。新的登记库会得到不同 replay UUID，这是来源身份差异，不应伪造统一 UUID；其特征和冻结统计仍须一致。

测试包含冻结来源隔离、静态零触发、真实四场只读与逐字节确定性、配置字节不变、因果前缀与未来扰动、时间积分边界、TOP/TOE 分离、错误/长缺口、合法零码和零基线、AIN2 单尖峰与持续阶跃、候选不触发、原因位映射替换、生产存储隔离及 CLI 独占写。外部数据位置沿用 WP2 的 `ICT_REPLAY_DATA_ROOT`；默认数据不存在则明确 skip，显式配置错误则失败。

本轮 [R1 时段报告](../research/stage1-wp3/rain_50.md)、[R2 时段报告](../research/stage1-wp3/rain_70.md)、[R3 时段报告](../research/stage1-wp3/rain_100.md)、[R4 自检](../research/stage1-wp3/post_rain_static.md) 陈述观测现象。完整 JSON、两次运行指纹和本机环境限制见 `work/stage1-wp3/` 的交付材料。
