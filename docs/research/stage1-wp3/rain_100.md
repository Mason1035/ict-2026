# WP3 时段报告：R3 rain_100

来源 experiment_id：`NODE01-f9029c8eef460b40-N0000004.CSV`。范围 `RESEARCH`；输入 `REAL/TEST_ONLY/sd_replay`，由 WP2 校验登记接口读取。原件未复制进仓库。

方法 `PROVISIONAL-v1`；配置内容摘要 `baf8b4bec4ab1cbace6f2abef1a76cb2dabcbe0e8cfde8b8b8f06f62f84cb8cd`。冻结生成时间 `2026-11-02T14:33:50.196601+00:00`。全体阈值只来自 R4；本报告未更新配置。

本场研究事件 **5** 个，振动候选 **0** 个。两次 CLI 报告逐字节相同，JSON SHA-256：`66d73045b1ae42c555bbc43e6139f7f938728f947d1cf8b59b64842368dd7984`。完整 JSON 位于 `work/stage1-wp3/rain_100-run1.json`。

时间单位为秒，相对 END.start_us 的 acquired 场内时刻；不是泵启动或可信 UTC 时刻。开始为持续越限起点，确认时刻才形成决定，末端为最后有支持证据的观测。土壤相对变化为无量纲 fraction，正负只表示 ADC 码变化方向。

## 研究事件时段

| 通道 / 分类 | 开始 s | 确认 s | 末端 s | 时段内绝对峰值 | 原因 mask | 关闭原因 |
| --- | ---: | ---: | ---: | --- | ---: | --- |
| imu_toe / RELATIVE_ORIENTATION_CHANGE | 35.775052 | 38.827968 | 179.915563 | direction_angle_deg=2.04446866 | 2 | SESSION_END |
| soil_middle / SOIL_ADC_RELATIVE_CHANGE | 36.558066 | 39.566836 | 149.077518 | relative_change_fraction=0.129752139 | 8 | RECOVERED |
| soil_top / SOIL_ADC_RELATIVE_CHANGE | 87.537530 | 90.556989 | 179.556906 | relative_change_fraction=0.175849057 | 4 | SESSION_END |
| soil_toe / SOIL_ADC_RELATIVE_CHANGE | 104.099524 | 107.111169 | 107.616859 | relative_change_fraction=0.0808842653 | 16 | QUALITY_INTERRUPTION |
| soil_toe / SOIL_ADC_RELATIVE_CHANGE | 163.591508 | 166.596856 | 166.596856 | relative_change_fraction=0.103857824 | 16 | QUALITY_INTERRUPTION |

## 各通道全场特征峰值

以下峰值来自完成预热的评估点；不把初始基线/缺测填成 0。全场峰值与“连续满足规则的时段内峰值”可能不同。

| 通道 | 主要指标 | 绝对峰值 | 峰值时刻 s | 峰值处有符号值 | R4 冻结值 |
| --- | --- | ---: | ---: | ---: | ---: |
| imu_toe | direction_angle_deg | 2.04446866 | 69.783888 | 2.04446866 | 0.290243119 |
| imu_toe | tilt_rate_deg_s | 0.168299557 | 41.375050 | 0.168299557 | 0.30717663 |
| imu_toe | vibration_rms_mps2 | 0.0824411502 | 38.325316 | 0.0824411502 | 0.185417608 |
| imu_toe | sta_lta | 15.1801366 | 26.895077 | 15.1801366 | 291.225574 |
| imu_toe | gyro_rms_dps | 0.813594112 | 28.155061 | 0.813594112 | 1.02583662 |
| imu_top | direction_angle_deg | 0.0872075061 | 50.592501 | 0.0872075061 | 0.199799696 |
| imu_top | tilt_rate_deg_s | 0.0913999067 | 54.922455 | -0.0913999067 | 0.448203193 |
| imu_top | vibration_rms_mps2 | 0.0787021714 | 55.431765 | 0.0787021714 | 0.242709851 |
| imu_top | sta_lta | 30.9087704 | 26.842513 | 30.9087704 | 351.935813 |
| imu_top | gyro_rms_dps | 1.81807814 | 51.618362 | 1.81807814 | 4.65905994 |
| soil_middle | raw_adc_code | 11626 | 10.573170 | 11626 | — |
| soil_middle | relative_change_fraction | 0.129752139 | 123.569263 | -0.129752139 | 0.0153829881 |
| soil_middle | adc_rate_code_s | 2167.26557 | 97.057713 | 2167.26557 | 25.1423027 |
| soil_toe | raw_adc_code | 11952 | 28.119672 | 11952 | — |
| soil_toe | relative_change_fraction | 0.210229736 | 139.091427 | -0.210229736 | 0.0604722108 |
| soil_toe | adc_rate_code_s | 2814.77291 | 139.596974 | 2814.77291 | 322.746308 |
| soil_top | raw_adc_code | 12289 | 35.052597 | 12289 | — |
| soil_top | relative_change_fraction | 0.175849057 | 137.050532 | -0.175849057 | 0.0756384529 |
| soil_top | adc_rate_code_s | 2131.17677 | 137.050532 | -2131.17677 | 193.248846 |

## 质量与同时变化

保留会话标记：`UNCALIBRATED / FIRMWARE_IDENTITY_DECLARED_ONLY / AIN2_JITTER_REVIEW`。

| 通道 | 输入观测 | READY 评估点 | WARMUP 评估点 | INVALID / 基线不足 | AIN2 相邻差防护次数 |
| --- | ---: | ---: | ---: | ---: | ---: |
| imu_toe | 17898 | 666 | 44 | 0 / 0 | 0 |
| imu_top | 17995 | 662 | 44 | 0 / 0 | 0 |
| soil_middle | 360 | 339 | 21 | 0 / 0 | 0 |
| soil_toe | 360 | 339 | 21 | 0 / 0 | 205 |
| soil_top | 360 | 339 | 21 | 0 / 0 | 0 |

READY 仅描述该评估点的特征窗口完整；AIN2 防护另外门控事件持续时长，标记点不参与触发。

| 已确认重合开始 s | 重合末端 s | 同时变化通道 | reason mask |
| ---: | ---: | --- | ---: |
| 39.566836 | 90.556989 | imu_toe, soil_middle | 10 |
| 90.556989 | 107.111169 | imu_toe, soil_middle, soil_top | 14 |
| 107.111169 | 107.616859 | imu_toe, soil_middle, soil_toe, soil_top | 30 |
| 107.616859 | 149.077518 | imu_toe, soil_middle, soil_top | 14 |
| 149.077518 | 179.556906 | imu_toe, soil_top | 6 |

## 解释边界

这些结果只陈述相对方向或原始 ADC 码变化及其时间重合；未证明变化由降雨引起，没有滑移真值，不作滑坡结论。PWM 只保留场次标签，没有换算雨量。所有结果均无生产告警/风险融合资格。振动即使形成候选，也不计入触发和同时变化事件。

AIN2 两段事件均因相邻差防护中断；全场相对变化峰值高于这两段事件内的峰值，不能把被抖动防护排除的点补算为持续触发。TOP 未满足持续方向角规则。
