# 四场工程数据探索分析

本次在已有原始数据上完成描述统计和人工回查索引，不依赖尚缺的烘干/称重/六面校准记录。
原始 ZIP 不变，正式标定、阈值和训练仍按 REAL_DATA_REVIEW_2026-11-03.md 的门禁等待材料。

## 输出及含义

本地输出：`E:\华为ict大赛\四场工程探索分析_2026-11-03`。
报告入口：该目录 `plots/index.html`，可用浏览器离线打开。PNG 可单独查看或交接。

每场目录有 summary.csv、bins.csv、largest_changes.csv、largest_intervals.csv 和 excluded_observations.json。
summary 保留逐指标样本数、原始范围、中位数、均值和总体标准差。Soil 用 ADC 原始码，IMU 用固件
换算的 m/s²、°/s，不冒充经过物理校准的加速度/角速度。没有转换成角度或真实位移。

默认一秒箱为左闭右开，原始实际采样时刻相对 END.start_us 定位；箱内同时给出中位数、最小值、
最大值和计数。这个箱宽只决定可视化汇总，不是 Feature/Risk 窗口；空箱不填零或连接成连续曲线。
原始尖峰不删除，图中用 min/max 包络保留，完整原件仍由 ZIP 哈希定位。

变化与间隔索引各取每通道/指标排名前 20 个，提供 from/to acquisition_index、相对时间与前后原始值。
同幅度按较早记录优先；这是显示排名，不是异常阈值或事件检测。有效性错误会切断相邻比较，不跨失效观测
制造“相邻跳变”；有效观测间的长间隔另列，不能默认为真实快速变化。

## 本次人工复核入口

以下为 Soil 最大相邻有效原始码变化，单位均为 ADC 码；时间相对各自设备侧采集起点。

| 场次 | 通道 | from → to index | to 相对秒 | 绝对变化 |
|---|---|---|---:|---:|
| N0000005 雨后静置 | AIN2 | 45108 → 45214 | 220.104691 | 172 |
| N0000004 100 PWM | AIN2 | 1458 → 1556 | 7.598190 | 2058 |
| N0000001 50 PWM | AIN0 | 7915 → 8018 | 39.052221 | 1037 |
| N0000002 70 PWM | AIN0 | 10895 → 10998 | 53.561793 | 419 |

这些跳变可能涉及接触、电气干扰、水分过程或现场操作，应请 A 对照已有日志/影像复核；现有记录不能
仅凭幅度确定原因，不能事后凭记忆补写。不同初始湿润状态与未标定探头不能按曲线幅度比较雨量或灾害风险。
TOP 三轴角速度的背景偏移只能作为待校准问题线索，不将统计均值直接应用为正式零偏修正。
R4 图的 min/max 包络也显示约 80 秒及 240 秒附近有短时 IMU 幅值变化；中位数曲线不能代替逐点检查。
须对照同场次原始 index 和已有现场证据排查，当前不能确认是人工触碰、线缆、盒体移动或其他原因。

## 复现

分析核心仅用标准库，PyCharm 可选择项目 `.venv/Scripts/python.exe`：

```powershell
python -B -X utf8 algorithm/B_revised/data_intake/engineering_analysis.py 'E:\华为ict大赛\数据.zip' --output 'E:\华为ict大赛\新的探索目录'
```

可选绘图模块依赖 Matplotlib（版本见 data_intake/requirements-plot.txt），与标准库分析解耦。
本机已在 E 盘项目虚拟环境安装，无须改系统 Python。队友可在自己的 Python 3.11+ 环境安装后运行：

```powershell
python -m pip install -r algorithm/B_revised/data_intake/requirements-plot.txt
python -B -X utf8 algorithm/B_revised/data_intake/render_engineering_analysis.py 'E:\华为ict大赛\新的探索目录'
```

分析目录和 plots 目录均拒绝覆盖；如需重跑请选择新目录。分析 manifest 记录输入 ZIP、CSV 和源码哈希；
绘图程序核对分析输入，另记 plot_manifest。原始数据、图表和完整局部分析保留 E 盘，不自动发布到仓库。
GitHub 只上传必要代码、测试、依赖说明和本说明，避免把工程原件误混入训练材料。

下一步仍需 A 的修复/标定/新干土基线与 C 的口径确认，才能进入正式拟合、阈值候选及历史物理量回算。
