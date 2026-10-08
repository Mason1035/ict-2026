# experiments

本目录保存实验设计、run 方案、实验执行记录和证据索引。

第一阶段建议按 run_id 建目录：
- `run_001_normal/`
- `run_002_rain_light/`
- `run_003_rain_medium/`
- `run_004_vibration/`
- `run_005_small_slip/`

每个 run 建议记录：
- 实验目的与步骤
- 环境和土样条件
- 硬件 / 固件 / Calibration 版本
- 安装位置与朝向
- 开始 / 结束时间
- 标签区间及证据
- Notes
- 数据文件、图片、视频及 Hash
- 失败或异常说明

B 负责实验设计、run_id 和标签规则；A 负责真实执行与采集。
首轮实验交接方案见 [`../../algorithm/B_revised/docs/B_EXPERIMENT_PLAN.md`](../../algorithm/B_revised/docs/B_EXPERIMENT_PLAN.md)；方案不是已执行的实验记录。
失败 run 不删除；沙盘实验不得描述为真实山区验证。
