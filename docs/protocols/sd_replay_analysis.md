# 阶段 I WP2：SD 原始回放与内部分析格式

入口是仓库外的一场只读 `BEG/CSV/END`，出口是独立研究登记和五条原始观测序列。实现只使用 Python 标准库，不经过完整 Telemetry v2 校验器或旧 soil/motion 推理入口；不产生规则结论。

## CLI

在仓库根目录执行。`--registry` 必须指向原始数据目录之外的专用研究 SQLite 文件；不要指定平台数据库。以下命令会登记元数据并向 stdout 输出 JSON 统计：

```bash
PYTHONPATH=platform_backend/src python3 -m geohazard_platform.research_sessions \
  "$HOME/Desktop/ICT-2026/数据/2026-11-02重测与无雨300秒/相同降雨量/50档pwm" \
  --type rain_50 \
  --registry "$PWD/work/replay/research.sqlite3"
```

类型标签为 `rain_50`、`rain_70`、`rain_100`、`post_rain_static`。目录内只有一份大写 `.CSV` 时自动选择；有多份时必须用 `--csv N0000001.CSV` 指定，与同 stem 的 `.BEG/.END` 配对。已知本批四个完整 experiment_id 的标签固定，标签不符拒收，避免把 R4 登记成降雨样本。

成功退出码为 0。失败退出码为 1，stderr 为包含 `status=rejected`、错误原因和可用校验报告的 JSON；登记库记录拒收审计。CLI 不启动平台、MQTT、前端或硬件服务。

## 完整性与身份

解析器在返回任何观测前检查：

- BEG/END 的 record_type、完整 experiment_id、逻辑 CSV 名和固件 SHA-256 声明一致；CSV 文件头的固件声明一致，存在 experiment_id 文件头时也比对。
- CSV 严格为既定 22 列，传感器类型/通道、数值和布尔字段可解析，数值非 NaN/Inf；错误行仍须符合记录结构。
- CSV **原始全字节**的长度、CRC32、数据行数等于 END 的 `csv_bytes/csv_crc32/verified_rows`，并核对存在的 `accepted`。
- 全表 `acquisition_index` 从 0 连续，包含传感器错误行；核对 END 的 TOP/TOE 和三路 soil 有效计数。

校验失败抛 `ReplayValidationError`，不会返回部分场次。结构错误的报告可能没有完整计数，其原因仍被记录。文件完整性通过与传感器正常是两回事：`validity != Valid` 不作为正常样本，单独统计并保留其原始 `validity/error`。

登记库只有 `research_sd_sessions` 和 `research_sd_attempts` 两张元数据/审计表，不持久化原始观测、不复制原件。登记键为 `(experiment_id, adapter_version)`，不是 N000000x 文件名。首次登记生成持久 UUID 回放身份；同字节、同类型重导复用该身份，原登记路径不变，本次路径另记审计。同身份异字节（包括 BEG/END）或改标签拒收并记录冲突，不覆盖原登记。适配器版本变化另立登记。

每次注册仍重新校验原件，登记库不替代原件归档。已有其他业务表的数据库会被拒绝使用；登记库位于输入场次目录内也会在写入前被拒绝。

## 内部格式与 WP3 消费

`parse_sd_session()` 返回 `ParsedSDSession`；`to_analysis_session()` 定义转换；对外消费宜使用完成持久登记的 `register_session()`：

```python
from geohazard_platform.research_sessions import register_session

session = register_session(capture_directory, "rain_50", research_registry_path)
for series in session.channels:
    # 每个 series 属于唯一 sensor_id，含本通道有效、缺测和错误观测。
    for sample in series.observations:
        row = sample.raw
        # WP3 根据 sample.usable、sample.quality_flags、series.quality_flags
        # 和实际微秒时间管理各自窗口；不可将不同 series 拼窗。
```

内部格式版本为 `research-raw-session-v1`，适配器版本为 `node01-sd-longtable-v1`。

| 部分 | 字段与语义 |
| --- | --- |
| 会话元数据 | experiment_id、类型、固件声明、原目录/CSV 名、三件套 SHA-256、完整性报告、逐通道有效/无效计数、质量标记 |
| 来源用途 | 固定 `REAL / TEST_ONLY / sd_replay`，`generated_replay_identity=true`；`replay_id=capture_or_replay_id` |
| 未知身份与版本 | 没有原生 boot/site 身份时为 `None`；本包的 rule/reference version 为 `None`；不将 acquisition_index 当成原生 seq |
| 通道序列 | `imu_top`、`imu_toe`、`soil_top`、`soil_middle`、`soil_toe` 各自独立；无观测的通道仍返回空序列 |
| 原始观测 | 源 CSV 物理行号、acquisition_index、attempted/acquired uptime、timestamp/time_synced、validity/error、六轴 raw、加速度 m/s²、角速度 °/s、soil ADC raw |
| 场内时间 | `relative_time_us = acquired_uptime_us - END.start_us`；缺 acquired 保持 `None`，不拿 attempt/登记时间代替；保留原 timestamp/null 和 time_synced/false |
| 观测质量 | 非 Valid、非零 error、缺值、缺 acquired、早于 attempt/场次起点、同通道采样时间重复/回跳均标记，`usable=false`；不前向填旧值、不补 0 |

TOP/TOE 的时间检查各自独立，且每次转换新建场内状态。错误行不被删除，消费方可立即让对应通道失效。合法 ADC=0 保持数值 0。三路 soil 只保留 ADC 原码，未定义百分比、VWC、降雨量或风险分。

R3/R4 的完整 experiment_id 对应 `AIN2_JITTER_REVIEW`，同时放在会话和 `soil_toe` 通道上；该复查标记保留原值，不删除尖峰。R4 标 `POST_RAIN_NOT_DRY_BASELINE`。所有会话标 `UNCALIBRATED`、`FIRMWARE_IDENTITY_DECLARED_ONLY`，固件本体尚未独立验收；有非 Valid 行或非零 error 的会话另标 `SENSOR_ERRORS_PRESENT`。`sample.usable` 只描述本条结构、传感器和时间质量，消费方仍须检查通道/会话复查标记，不据此宣称已标定或可作干土基线。

`fusion_eligible=false/risk_eligible=false`，研究数据不写 `telemetry`、生产当前态、boot_sessions 或 alarms。WP1 的 scope、生产告警资格与默认查询不变；旧 `inference.py` 的历史双 IMU 混窗入口不被此路径调用。

## 统计口径

`AnalysisSession.summary()` 和 CLI 按通道输出：

- `count`：所有尝试记录；`valid_count/invalid_count`：仅按原始 validity 判定，与 END 有效计数口径一致。
- `usable_count`：通过本条质量检查的记录；`missing_value_count`：本通道主载荷有缺值的记录。
- `duration_s`：首末 usable acquired 时间之差，不代表连续覆盖率；无 usable 数据为 `null`。
- `median_interval_us`：本通道相邻两条原始记录均 usable 时的 acquired 时间差中位数；不跨越错误行/缺测行连接间隔，无可用间隔为 `null`。

使用实际采样时标，不重采样、不填造等间隔点、不跨场拼接。长缺口的阈值、窗口清理、覆盖率、静态参考和规则判断由 WP3 实现；本包的时长/中位间隔不是窗口质量验收。当前实现单场读入内存，适用于本批最大 61,629 行的离线回放。

## 回归

在具备平台开发依赖的 Python 3.11+ 环境运行全量 pytest。新增模块只需标准库，也可单独执行：

```bash
PYTHONPATH=platform_backend/src python3 -m unittest discover \
  -s platform_backend/tests -p 'test_sd_replay*.py' -v
```

`test_sd_replay.py` 使用合成数据，覆盖校验、隔离、缺测、合法零值、身份冲突和 CLI。`test_sd_replay_data.py` 固定断言四场的 experiment_id、行数、字节数、CRC、五通道计数、时间语义和质量标记，并重算原件前后指纹验证只读。

默认原件位于仓库同级 `数据/2026-11-02重测与无雨300秒/`，可用 `ICT_REPLAY_DATA_ROOT` 指定其他只读根目录。真实数据未交付的环境明确 skip；显式设置了路径却找不到数据则失败，避免配置错误变成静默跳过。

旧 N0000002 回归默认查历史评估附录 A 的 `数据/相同降雨量/70 pwm挡位/1（I2C错误）/N0000002.CSV`，也可用 `ICT_REPLAY_LEGACY_N2` 指定确切 CSV。固定旧 SHA-256、CRC `311660b9`、36,020 行、771 条错误和各通道有效计数；原件缺失时明确 skip，不会以零错误的新 N0000002 代替。任务执行时实际可见的 `数据/相同降雨量/70档pwm/N0000002.CSV` 与新批 experiment_id/指纹相同，不能作为这个故障回归样本。
