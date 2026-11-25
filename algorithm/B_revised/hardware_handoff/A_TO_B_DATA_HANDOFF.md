# A → B 首批真实实验数据交接清单

本页根据共享契约第 11、13 节和 A 负责人文档第 11 节整理，帮助 A 预留采集与导出接口；**不更改固定 CSV 表头**。B 分配 run_id/实验方案，A 执行和保留成功与失败 run，B 验收质量和标签。受控沙盘结果不能表述为山区实证。

## 原始 CSV

严格 20 列、顺序与拼写均不改：

```text
run_id,timestamp_ms,top_ax,top_ay,top_az,top_gx,top_gy,top_gz,toe_ax,toe_ay,toe_az,toe_gx,toe_gy,toe_gz,soil_top_raw,soil_middle_raw,soil_toe_raw,flow_lpm,rain_level,label
```

一行对应一个 IMU 采样时点；两枚 IMU 的异步对齐误差留证，不伪造同步。低频 Soil/Flow 只在实际新观测时填值，其他行留空；缺测为空单元格，不填 0/NaN。可信 UTC 用 Unix 毫秒；无可信 UTC 时 `timestamp_ms` 留空并在侧表保留单调 `uptime_ms` 与 `row_index`。IMU 加速度 m/s²，角速度 °/s；Soil 为 ADS1115 原始码，Flow 为 L/min。`label` 仅 `NORMAL`/`RAIN`/`SLIP` 或空，实验标签与四级风险分开。受控振动没有滑移证据时不标 SLIP。不要删掉失败、异常或无标签片段。

首批计划：`run_001_normal`、`run_002_rain_light`、`run_003_rain_medium`、`run_004_vibration`、`run_005_small_slip`。这些是计划名；真实文件和观测尚未交付。小滑移仅在安全可控沙盘上进行，保留影像/人工观察和不确定区间。

## 随 run 一起交的元数据（文件格式仍待三方冻结）

- 身份与来源：`device_id`、`boot_id`、`run_id`、`parent_run`、`is_synthetic`、真实/模拟来源、文件 SHA-256、行数、采集起止与操作者、固件/硬件 revision、配置/校准版本。
- 时间侧表：`row_index → uptime_ms`、UTC 同步来源和误差、重启/校时/缺口；每通道实际采样时刻、validity/错误码，不将转发接收时刻冒充采样时刻。
- IMU：top/toe 的安装位置/轴向、量程、ODR、滤波/寄存器版本、静止基线、坐标变换、实际异步对齐误差。
- Soil/ADS1115：A0/A1/A2 与 top/middle/toe 的映射，PGA、转换率、供电、探针逐支干湿标定的原始证据、位置/深度；未经土样标定不称 VWC。
- 实验操作与标签：土样/坡度/泵/水量、真实流量标定和雨级、开始/结束/变更、振动或滑移控制条件、人工/影像证据及文件哈希、标签区间与不确定性。急停/传感器故障/SD 写入失败均记录。

真实数据到 B 时先保留原件和哈希，运行包内只读初检：

```powershell
python data_intake/check_experiment_csv.py "<实际CSV完整路径>" --output "<仓库外质量报告路径>"
```

退出码 0 仅表示程序检查项通过；校准、真实性和正式训练可用性仍需 B 人工复核。A 尚未交付数据时无需编造样例 CSV；若要验证导出程序，可在**单独**的 TEST_ONLY 目录生成明确标注的测试记录，绝不混入正式 run。
