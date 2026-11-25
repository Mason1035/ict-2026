# Changelog

仅记录实际发生的修改；无此前项目记录，本文件从本次独立 V0.1 实现开始。

## [0.1.1] - 2026-09-25

### Added

- 增加逐行来源字段：`run_id`、从0连续递增的 `row_index`、`is_synthetic`、`generator_version`、`seed`、`parameter_hash`、`parent_run`。逻辑 `run_id=sim_<完整参数哈希>`，同配置和seed重跑保持一致；每次执行仍分配独立输出目录以防覆盖。
- metadata 增加 `artifact_kind=simulator_observation_csv`、`observation_schema_version=physics_sim.observation.v0.1.1`、`contract_status=PRE_B_TRAINING_CONTRACT`。`observation_columns` 明确为合成观测代理清单，不代表B正式训练特征。
- CSV 增加 `observation_warmup` 与双IMU的 `tilt_rate_valid`；首行角速度为空单元格/null，后续按因果后向差分计算。输出校验仅允许首行两个角速度为空，拒绝其他非有限值及不一致来源。
- 保存前校验CSV与metadata中的run身份、seed、参数哈希、版本、行数和schema状态；CLI摘要显示逻辑run ID及契约状态。

### Changed

- 三个场景的 `simulator_version` 更新为 `0.1.1`；物理公式、阈值、状态和传感器数值参数未改。`dt_s` 注释明确是模拟数值/输出步长，不是硬件采样率。
- CSV由16列变为26列。V0.1.0的 `observation_features()` 名称为兼容保留，但文档和docstring明确它只返回观测代理，不是B的Feature Contract。
- README更新为当前契约状态，区分Simulator Observation CSV、A真实Experiment CSV和 `zhifang.telemetry.v2`，并说明独立adapter及A/B待交接内容。V0.1.0 Contract Alignment Review保持原样作为历史审查证据。

### Tests

- 保留原有场景、物理、因果、哈希、CLI、绘图与防覆盖测试；按首行null及来源字段更新原schema相关断言，新增逐行身份/连续性/重跑一致、metadata一致、时钟无关哈希、错误来源拒绝、validity/warmup和Infinity拒绝测试。
- 本轮最终完整运行：`54 passed in 21.77s`，0 failed；`compileall`通过。
- 三个场景由CLI实际运行，均601行、26列，除首行两个有解释的角速度空值外无NaN，且无Infinity。normal：final=NORMAL、max M=0.2、max D=0、failure_time=null。rain_no_failure：final=SATURATION、max M=0.46197034836346235、max D=0、failure_time=null。heavy_rain_failure：final=FAILURE、max M=0.959374624464318、max D=0.5144500000000003 synthetic m、failure_time=357 s。
- heavy_rain_failure 相同配置和seed再次运行：逻辑run ID、逐行来源、参数哈希及CSV SHA-256完全一致，输出目录不同且原结果保留。
- 重雨输出再次由绘图CLI生成 `diagnostic.png`，证实新增来源/空值列不破坏原诊断绘图。

### Assumptions / TODO_CALIBRATION

- 所有物理参数、状态阈值、速度和观测代理仍为 `SIMULATION_ONLY`；真实参数、传感器映射、噪声/漂移/缺包、雨强与泵流量关系均为 `TODO_CALIBRATION`。当前未生成真实六轴信号、B正式Feature Table或生产Telemetry。
- `PRE_B_TRAINING_CONTRACT` 表示等待B发布并接纳具体Features/Labels/Window/Split/Leakage/Metrics/Synthetic Constraints。A真实实验CSV及相关Calibration Metadata也尚未接入。

## [0.1.0] - 2026-09-24

### Added

- 新建独立 `physics_sim` 包；开始时工作目录为空且无 Git 仓库、共享契约或负责人 C 文档。
- 新增归一化蓄水模型：`dM/dt = k_in*R*(1-M) - k_out*M`，常雨量单步采用解析积分与 `expm1`，明确单位、边界保护与非有限数报错。
- 新增 `I=M*sin(theta)` 的 SIMULATION_ONLY 驱动、五个状态、失败前恢复和 FAILURE 吸收态；阈值等号进入较高状态。
- 新增分段恒定 synthetic m/s 速度及 `D_(n+1)=D_n+v_n*dt` 左端积分；初始 D=0，不把它声明为 NODE-01 测量值。
- 新增三处 Soil 增益/历史延迟映射、两处 IMU 的线性 tilt、后向 tilt_rate 与 velocity→vibration RMS proxy；记录噪声单位与截断偏差。
- 新增唯一 `numpy.random.Generator` 的 seed 注入及固定抽样顺序；传感器不反向控制物理层。
- 新增完整 YAML schema、三个场景，以及缺失、未知、重复键、范围、阈值顺序和采样网格校验。
- 新增16列调试 CSV、九列观测特征白名单、metadata JSON；失败时间只作为首次网格采样 synthetic ground truth。
- 新增规范化完整配置 SHA-256、CSV SHA-256、依赖版本记录及不覆盖已有实验的独立 run 目录。
- 新增 CLI 与含七类变量面板和状态面板的绘图 CLI；PNG 独占创建，拒绝覆盖既有图片。
- 新增 README 当前状态、单位、公式、时间语义、使用说明、校准任务及已知限制；新增忽略规则和输出目录占位文件。

### Changed

- 无既有业务代码可修改；未重构或触碰训练、部署、通信、风险融合、云服务模块。
- 相对需求中的显式步进思路，使用同一蓄水微分方程的解析单步解，避免大 dt 下数值越界；这是此次初始设计，不是此前版本变更。

### Fixed

- 本次无既有版本缺陷修复；未伪造历史 bug 或此前发布记录。

### Tests

- 首轮实际执行：`48 passed in 17.60s`，0 failed。
- 复审后新增非1秒采样角速度/位移积分验证、错误配置 CLI 不创建 run 验证。
- 最终实际执行：`50 passed in 1.80s`，0 failed；pytest 文本日志与 JUnit XML 保存于交付验证目录。
- 测试覆盖要求的8类行为，并增加解析水文/大 dt、阈值等号、恢复/吸收、初始失败、延迟传播、差分单位、seed/噪声隔离、因果前缀、白名单、哈希、schema、文件保护及 CLI/绘图。
- 三个场景均通过独立 CLI 运行，各601行、16列；所有数值有限，无 NaN/Inf。
- normal：final=NORMAL；failure_time=null；max M=0.2；max D=0 m。
- rain_no_failure：final=SATURATION；failure_time=null；max M=0.46197034836346235；max D=0 m。
- heavy_rain_failure：final=FAILURE；failure_time=357 s；max M=0.959374624464318；max D=0.5144500000000003 synthetic m。
- 强雨首次状态时间：NORMAL 0 s → SATURATION 66 s → CREEP 134 s → INCIPIENT_SLIP 219 s → FAILURE 357 s。
- 三个场景分别再次由独立 CLI 运行：对应 CSV 字节相同、parameter_hash 相同、metadata 除 run_id 外相同；原文件保留。
- 三个绘图 CLI 成功，逐一打开并检查七类变量、状态转移、单位和科学边界声明，无标签裁切。
- 编译检查通过；`pip check` 报告 `No broken requirements found`。
- 验证环境：Python 3.11.9；numpy 2.4.3、pandas 3.0.1、PyYAML 6.0.3、matplotlib 3.10.8、pytest 9.0.2。

### Review

- 已复审关键数值来源、随机性、真实/合成边界、D 的 latent 身份、未来泄漏、普通降雨不失败、单位、依赖、重复逻辑、复杂度、文档一致性、核心注释与测试行为。
- 阈值、速度、噪声、传播与观测增益均来自 YAML；代码中的0/1边界、原点、初始差分与浮点网格容差已说明含义。
- 本次未发现需修改核心实现的失败测试或复审缺陷；补充了上述两项验证，没有降低测试断言。
- 外部共享契约一致性仍未验证，不能将独立模块验收等同于现有项目集成验收。

### Assumptions

- 全部物理、阈值、速度、传播、映射与噪声参数为 SIMULATION_ONLY；NOT REAL-WORLD HAZARD THRESHOLDS。
- moisture 是 normalized 0–1 而非 VWC；D/v 为 synthetic latent；振动字段是 m/s² 幅值代理，而非原始波形 RMS。
- 雨段左闭右开；采样行表示该时刻，下一状态只积分当前已知雨量/速度，不使用未来值。
- 初始土壤历史恒为 M0、D=0、首次 tilt_rate=0；失败后持续配置速度，仅供软件覆盖。
- 同配置/seed的逐位复现限于同软件与运行环境；run_id 唯一性不参与数值 RNG 或参数哈希。

### TODO_CALIBRATION

- 真实含水量定义、传感器标定、入渗与排水响应、坡角与材料特性的驱动关系。
- 状态阈值、速度/位移尺度、failure ground truth 实验判据及恢复行为。
- 空间响应增益/延迟、IMU安装基线与位移→倾角映射、振动窗口/频响/幅值关系、各噪声与漂移参数。
- 未经实验验证，不将任何默认参数迁移为真实灾害预测或部署阈值。
