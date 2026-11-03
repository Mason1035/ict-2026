# WP3 时段报告：R2 rain_70

来源 experiment_id：`NODE01-d5a1317c1f27fded-N0000002.CSV`。范围 `RESEARCH`；输入 `REAL/TEST_ONLY/sd_replay`，由 WP2 校验登记接口读取。原件未复制进仓库。

方法 `PROVISIONAL-v1`；配置内容摘要 `baf8b4bec4ab1cbace6f2abef1a76cb2dabcbe0e8cfde8b8b8f06f62f84cb8cd`。冻结生成时间 `2026-11-02T14:33:50.196601+00:00`。全体阈值只来自 R4；本报告未更新配置。

本场研究事件 **5** 个，振动候选 **0** 个。两次 CLI 报告逐字节相同，JSON SHA-256：`20caf2c4c9beb4556d471902fe80b4458e11a2977ddc4e2fa0f2f799f9e1bee4`。完整 JSON 位于 `work/stage1-wp3/rain_70-run1.json`。

时间单位为秒，相对 END.start_us 的 acquired 场内时刻；不是泵启动或可信 UTC 时刻。开始为持续越限起点，确认时刻才形成决定，末端为最后有支持证据的观测。土壤相对变化为无量纲 fraction，正负只表示 ADC 码变化方向。

## 研究事件时段

| 通道 / 分类 | 开始 s | 确认 s | 末端 s | 时段内绝对峰值 | 原因 mask | 关闭原因 |
| --- | ---: | ---: | ---: | --- | ---: | --- |
| soil_middle / SOIL_ADC_RELATIVE_CHANGE | 30.577421 | 33.582981 | 179.575864 | relative_change_fraction=0.0364102564 | 8 | SESSION_END |
| soil_toe / SOIL_ADC_RELATIVE_CHANGE | 37.101531 | 40.591517 | 179.594996 | relative_change_fraction=0.135174755 | 16 | SESSION_END |
| imu_toe / RELATIVE_ORIENTATION_CHANGE | 43.782919 | 46.839847 | 179.772119 | direction_angle_deg=2.19598278 | 2 | SESSION_END |
| soil_top / SOIL_ADC_RELATIVE_CHANGE | 46.063157 | 49.557980 | 179.554599 | relative_change_fraction=0.118980283 | 4 | SESSION_END |
| imu_top / RELATIVE_ORIENTATION_CHANGE | 60.272579 | 63.317176 | 75.007169 | direction_angle_deg=0.217019308 | 1 | RECOVERED |

## 各通道全场特征峰值

以下峰值来自完成预热的评估点；不把初始基线/缺测填成 0。全场峰值与“连续满足规则的时段内峰值”可能不同。

| 通道 | 主要指标 | 绝对峰值 | 峰值时刻 s | 峰值处有符号值 | R4 冻结值 |
| --- | --- | ---: | ---: | ---: | ---: |
| imu_toe | direction_angle_deg | 2.19598278 | 140.454110 | 2.19598278 | 0.290243119 |
| imu_toe | tilt_rate_deg_s | 0.178877025 | 57.249358 | 0.178877025 | 0.30717663 |
| imu_toe | vibration_rms_mps2 | 0.100561783 | 58.531014 | 0.100561783 | 0.185417608 |
| imu_toe | sta_lta | 15.1519745 | 164.551866 | 15.1519745 | 291.225574 |
| imu_toe | gyro_rms_dps | 0.908849492 | 58.531014 | 0.908849492 | 1.02583662 |
| imu_top | direction_angle_deg | 0.217019308 | 64.082885 | 0.217019308 | 0.199799696 |
| imu_top | tilt_rate_deg_s | 0.058867878 | 75.267188 | -0.058867878 | 0.448203193 |
| imu_top | vibration_rms_mps2 | 0.10630528 | 75.267188 | 0.10630528 | 0.242709851 |
| imu_top | sta_lta | 19.207666 | 74.497179 | 19.207666 | 351.935813 |
| imu_top | gyro_rms_dps | 1.5838042 | 154.777010 | 1.5838042 | 4.65905994 |
| soil_middle | raw_adc_code | 11800 | 26.576266 | 11800 | — |
| soil_middle | relative_change_fraction | 0.0364102564 | 65.584123 | -0.0364102564 | 0.0153829881 |
| soil_middle | adc_rate_code_s | 207.167172 | 28.576847 | -207.167172 | 25.1423027 |
| soil_toe | raw_adc_code | 13020 | 25.624133 | 13020 | — |
| soil_toe | relative_change_fraction | 0.135174755 | 172.597689 | -0.135174755 | 0.0604722108 |
| soil_toe | adc_rate_code_s | 646.97753 | 37.101531 | -646.97753 | 322.746308 |
| soil_top | raw_adc_code | 12601 | 26.556100 | 12601 | — |
| soil_top | relative_change_fraction | 0.118980283 | 85.566742 | -0.118980283 | 0.0756384529 |
| soil_top | adc_rate_code_s | 829.159501 | 53.561793 | -829.159501 | 193.248846 |

## 质量与同时变化

保留会话标记：`UNCALIBRATED / FIRMWARE_IDENTITY_DECLARED_ONLY`。

| 通道 | 输入观测 | READY 评估点 | WARMUP 评估点 | INVALID / 基线不足 | AIN2 相邻差防护次数 |
| --- | ---: | ---: | ---: | ---: | ---: |
| imu_toe | 17901 | 665 | 44 | 0 / 0 | 0 |
| imu_top | 17997 | 662 | 44 | 0 / 0 | 0 |
| soil_middle | 360 | 339 | 21 | 0 / 0 | 0 |
| soil_toe | 360 | 339 | 21 | 0 / 0 | 0 |
| soil_top | 360 | 340 | 20 | 0 / 0 | 0 |

READY 仅描述该评估点的特征窗口完整；AIN2 防护另外门控事件持续时长，标记点不参与触发。

| 已确认重合开始 s | 重合末端 s | 同时变化通道 | reason mask |
| ---: | ---: | --- | ---: |
| 40.591517 | 46.839847 | soil_middle, soil_toe | 24 |
| 46.839847 | 49.557980 | imu_toe, soil_middle, soil_toe | 26 |
| 49.557980 | 63.317176 | imu_toe, soil_middle, soil_toe, soil_top | 30 |
| 63.317176 | 75.007169 | imu_toe, imu_top, soil_middle, soil_toe, soil_top | 31 |
| 75.007169 | 179.554599 | imu_toe, soil_middle, soil_toe, soil_top | 30 |
| 179.554599 | 179.575864 | imu_toe, soil_middle, soil_toe | 26 |
| 179.575864 | 179.594996 | imu_toe, soil_toe | 18 |

## 解释边界

这些结果只陈述相对方向或原始 ADC 码变化及其时间重合；未证明变化由降雨引起，没有滑移真值，不作滑坡结论。PWM 只保留场次标签，没有换算雨量。所有结果均无生产告警/风险融合资格。振动即使形成候选，也不计入触发和同时变化事件。

TOP 仅形成一段方向角事件，之后满足恢复门限而结束；其余列出的时段持续到场尾。场尾结束不代表已恢复。
