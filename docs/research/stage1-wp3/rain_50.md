# WP3 时段报告：R1 rain_50

来源 experiment_id：`NODE01-5f604a129b915316-N0000001.CSV`。范围 `RESEARCH`；输入 `REAL/TEST_ONLY/sd_replay`，由 WP2 校验登记接口读取。原件未复制进仓库。

方法 `PROVISIONAL-v1`；配置内容摘要 `baf8b4bec4ab1cbace6f2abef1a76cb2dabcbe0e8cfde8b8b8f06f62f84cb8cd`。冻结生成时间 `2026-11-02T14:33:50.196601+00:00`。全体阈值只来自 R4；本报告未更新配置。

本场研究事件 **5** 个，振动候选 **0** 个。两次 CLI 报告逐字节相同，JSON SHA-256：`6f4489b84993b80167b6ff80b282d5f6698d1b084990e393a177d2d7763e8cce`。完整 JSON 位于 `work/stage1-wp3/rain_50-run1.json`。

时间单位为秒，相对 END.start_us 的 acquired 场内时刻；不是泵启动或可信 UTC 时刻。开始为持续越限起点，确认时刻才形成决定，末端为最后有支持证据的观测。土壤相对变化为无量纲 fraction，正负只表示 ADC 码变化方向。

## 研究事件时段

| 通道 / 分类 | 开始 s | 确认 s | 末端 s | 时段内绝对峰值 | 原因 mask | 关闭原因 |
| --- | ---: | ---: | ---: | --- | ---: | --- |
| imu_toe / RELATIVE_ORIENTATION_CHANGE | 24.399652 | 27.445766 | 179.926478 | direction_angle_deg=5.79065341 | 2 | SESSION_END |
| soil_middle / SOIL_ADC_RELATIVE_CHANGE | 32.575508 | 35.576059 | 179.576441 | relative_change_fraction=0.0530201342 | 8 | SESSION_END |
| soil_top / SOIL_ADC_RELATIVE_CHANGE | 38.058754 | 41.558698 | 179.556350 | relative_change_fraction=0.420651952 | 4 | SESSION_END |
| soil_toe / SOIL_ADC_RELATIVE_CHANGE | 42.086083 | 45.096079 | 179.596091 | relative_change_fraction=0.15804769 | 16 | SESSION_END |
| imu_top / RELATIVE_ORIENTATION_CHANGE | 45.401733 | 48.451083 | 179.858777 | direction_angle_deg=0.727058335 | 1 | SESSION_END |

## 各通道全场特征峰值

以下峰值来自完成预热的评估点；不把初始基线/缺测填成 0。全场峰值与“连续满足规则的时段内峰值”可能不同。

| 通道 | 主要指标 | 绝对峰值 | 峰值时刻 s | 峰值处有符号值 | R4 冻结值 |
| --- | --- | ---: | ---: | ---: | ---: |
| imu_toe | direction_angle_deg | 5.79065341 | 128.194261 | 5.79065341 | 0.290243119 |
| imu_toe | tilt_rate_deg_s | 0.367690791 | 50.784274 | 0.367690791 | 0.30717663 |
| imu_toe | vibration_rms_mps2 | 0.280517432 | 147.454549 | 0.280517432 | 0.185417608 |
| imu_toe | sta_lta | 52.9348661 | 146.429880 | 52.9348661 | 291.225574 |
| imu_toe | gyro_rms_dps | 1.97404189 | 30.744473 | 1.97404189 | 1.02583662 |
| imu_top | direction_angle_deg | 0.727058335 | 178.841728 | 0.727058335 | 0.199799696 |
| imu_top | tilt_rate_deg_s | 0.0754864337 | 146.381597 | -0.0754864337 | 0.448203193 |
| imu_top | vibration_rms_mps2 | 0.115383276 | 153.287544 | 0.115383276 | 0.242709851 |
| imu_top | sta_lta | 45.3063629 | 140.027483 | 45.3063629 | 351.935813 |
| imu_top | gyro_rms_dps | 1.32305461 | 153.287544 | 1.32305461 | 4.65905994 |
| soil_middle | raw_adc_code | 12029 | 29.572407 | 12029 | — |
| soil_middle | relative_change_fraction | 0.0530201342 | 89.571492 | -0.0530201342 | 0.0153829881 |
| soil_middle | adc_rate_code_s | 252.893489 | 32.071589 | -252.893489 | 25.1423027 |
| soil_toe | raw_adc_code | 13475 | 29.591935 | 13475 | — |
| soil_toe | relative_change_fraction | 0.15804769 | 139.595213 | -0.15804769 | 0.0604722108 |
| soil_toe | adc_rate_code_s | 753.307191 | 41.111211 | -753.307191 | 322.746308 |
| soil_top | raw_adc_code | 19575 | 10.055731 | 19575 | — |
| soil_top | relative_change_fraction | 0.420651952 | 92.056155 | -0.420651952 | 0.0756384529 |
| soil_top | adc_rate_code_s | 2078.07266 | 38.548631 | -2078.07266 | 193.248846 |

## 质量与同时变化

保留会话标记：`UNCALIBRATED / FIRMWARE_IDENTITY_DECLARED_ONLY`。

| 通道 | 输入观测 | READY 评估点 | WARMUP 评估点 | INVALID / 基线不足 | AIN2 相邻差防护次数 |
| --- | ---: | ---: | ---: | ---: | ---: |
| imu_toe | 17901 | 666 | 44 | 0 / 0 | 0 |
| imu_top | 17998 | 662 | 44 | 0 / 0 | 0 |
| soil_middle | 360 | 340 | 20 | 0 / 0 | 0 |
| soil_toe | 360 | 340 | 20 | 0 / 0 | 0 |
| soil_top | 360 | 340 | 20 | 0 / 0 | 0 |

READY 仅描述该评估点的特征窗口完整；AIN2 防护另外门控事件持续时长，标记点不参与触发。

| 已确认重合开始 s | 重合末端 s | 同时变化通道 | reason mask |
| ---: | ---: | --- | ---: |
| 35.576059 | 41.558698 | imu_toe, soil_middle | 10 |
| 41.558698 | 45.096079 | imu_toe, soil_middle, soil_top | 14 |
| 45.096079 | 48.451083 | imu_toe, soil_middle, soil_toe, soil_top | 30 |
| 48.451083 | 179.556350 | imu_toe, imu_top, soil_middle, soil_toe, soil_top | 31 |
| 179.556350 | 179.576441 | imu_toe, imu_top, soil_middle, soil_toe | 27 |
| 179.576441 | 179.596091 | imu_toe, imu_top, soil_toe | 19 |
| 179.596091 | 179.858777 | imu_toe, imu_top | 3 |

## 解释边界

这些结果只陈述相对方向或原始 ADC 码变化及其时间重合；未证明变化由降雨引起，没有滑移真值，不作滑坡结论。PWM 只保留场次标签，没有换算雨量。所有结果均无生产告警/风险融合资格。振动即使形成候选，也不计入触发和同时变化事件。

五个独立通道均形成研究事件，列出时段均延续到场尾；这只说明该冻结口径下的观测变化。
