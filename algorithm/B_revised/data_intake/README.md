# B 阶段 1：真实实验 CSV 接收初检

本目录按 `00_TEAM_SHARED_CONTRACT.pdf` 与 `02_算法与数据负责人开发文档.pdf` 的正式 v2 实验接口工作。它只检查原始文件结构和可直接观测的质量问题，**不训练模型、不作风险判定、不宣称真实数据已就绪**。旧七字段 JSON 和 `PRE_B_TRAINING_CONTRACT` 仅供旧演示/规则蒸馏，不可作为本程序的正式实验输入。

## PyCharm 运行

使用 Python 3.11+，无第三方依赖。在 PyCharm 打开 `E:\华为ict大赛\ict-2026\algorithm\B_revised`，将运行配置设为：

- Script path：`E:\华为ict大赛\ict-2026\algorithm\B_revised\data_intake\check_experiment_csv.py`
- Parameters：`"<A交付CSV完整路径>" --output "<质量报告输出路径>"`（两个占位符须替换为实际绝对路径；报告放在仓库外）
- Working directory：`E:\华为ict大赛\ict-2026\algorithm\B_revised`

文件尚未从 A 收到时，不要创建貌似实测的 CSV。可先运行自测：

```powershell
cd E:\华为ict大赛\ict-2026
python -m unittest discover -s algorithm/B_revised/data_intake -t algorithm/B_revised -p 'test_*.py' -v
```

正式文件到达后，先只读检查原始文件，再保存报告：

```powershell
python algorithm/B_revised/data_intake/check_experiment_csv.py "<A交付CSV完整路径>" --output "<质量报告输出路径>"
```

退出码 0 表示 CSV 结构和所检查项目通过，2 表示需要复核；**0 不代表数据已校准或可训练**。报告记录 SHA-256、每列空值数、每个 run 的行数/标签/时间重复和倒退、正向间隔中位数与最大间隔。原始 CSV 不会被修改。未知窗口和物理阈值仍为 `TODO_CALIBRATION`。

## A → B 必要交接

1. 原始 CSV 严格 20 列、固定顺序：`run_id,timestamp_ms,top_ax,top_ay,top_az,top_gx,top_gy,top_gz,toe_ax,toe_ay,toe_az,toe_gx,toe_gy,toe_gz,soil_top_raw,soil_middle_raw,soil_toe_raw,flow_lpm,rain_level,label`。缺测留空单元格；`timestamp_ms` 为 UTC Unix 毫秒。实验标签只用 `NORMAL`、`RAIN`、`SLIP` 或留空，不能与风险等级混用。
2. 同批元数据：`device_id`、`boot_id`、`run_id`、`parent_run`、`run_source`、`is_synthetic`、固件/采集版本、原文件 SHA-256、采集开始结束时间、实验操作与人工确认的标签区间。元数据的文件结构尚未由三方冻结，先保留原始记录，不用本初检脚本推断。
3. 时间和传感器元数据：`row_index → uptime` 映射；各通道实际采样时间与 validity/错误标记；IMU 的 ODR、滤波、量程、安装方向；ADS1115 的 PGA/采样设置；各探针与 IMU 的校准记录、单位和版本。重启、设备换装、ODR 改变须显式记录。
4. B 审核标签、缺测、漂移、饱和、采样率、时间可信度后才构建特征表。分组与 `parent_run` 先于窗口和合成增强；同一物理实验的派生数据不得跨 Train/Validation/Test。正式 Training Contract 继续保持 `NOT_READY_FOR_FORMAL_TRAINING`，直到特征、窗口、标签、切分、归一化和合成约束经真实数据核定。

此脚本不检查上述元数据完整性，也不把大幅物理变化自动视为噪声。出现 `REVIEW_REQUIRED` 时，B 人工核对原始记录与 A 的设备日志后决定保留或排除，并记录理由。
