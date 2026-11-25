# B 真实实验质量报告模板（待 A 数据）

> 当前没有 A 的正式实测交接；本模板不得填入 TEST_ONLY 演示数值冒充实测。

- 原始文件 / SHA-256：`WAITING_FOR_A`
- run_id / parent_run / device_id / boot_id：`WAITING_FOR_A`
- 数据来源与实验日期、操作/标签证据：`WAITING_FOR_A`
- 固件、IMU ODR/滤波/量程/坐标、ADS1115 PGA、探针/IMU calibration_version：`WAITING_FOR_A`
- UTC 与 `row_index→uptime` 的对应、重启/时钟校正与各通道 sample time：`WAITING_FOR_A`

| 通道 | 原始行数 | 有效行数 | 空值 | validity 错误 | 饱和 | 漂移/偏置 | 实际采样间隔 | 时间可信度 | 处置依据 |
|---|---:|---:|---:|---:|---:|---|---|---|---|
| top IMU 六轴 | 待填 | 待填 | 待填 | 待填 | 待填 | 待填 | 待填 | 待填 | 待填 |
| toe IMU 六轴 | 待填 | 待填 | 待填 | 待填 | 待填 | 待填 | 待填 | 待填 | 待填 |
| soil top/middle/toe 原始 ADC | 待填 | 待填 | 待填 | 待填 | 待填 | 待填 | 待填 | 待填 | 待填 |
| flow / rain_level | 待填 | 待填 | 待填 | 待填 | 待填 | 待填 | 待填 | 待填 | 待填 |

记录每个连续片段的开始/结束 row 与 uptime、缺口/倒退/重复时刻、校准或 ODR 切换、保留与排除理由。对大幅变化先查实验日志，不自动删除为噪声。另记录正常/降雨/振动/受控滑移各区间的人工或影像证据、标签不确定范围与未标注行。

结论分别填写：`CSV 结构通过？`、`元数据足够？`、`可计算候选特征？`、`可用于正式 split？`。任何一项未核实都写 `unknown/待交接`，不写“已验证”。
