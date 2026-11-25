# Physics-inspired Simulation V0.1.1

当前版本：**0.1.1**。本模块是 **Physics-inspired synthetic time-series generator**。
用途：软件开发、数据链路验证、算法与训练流水线开发、Real + Synthetic 实验，以及未来真实实验校准。

**全部示例数值与动力学/传感器映射均为 SIMULATION_ONLY。NOT REAL-WORLD HAZARD THRESHOLDS。**
本模块不是经过验证的岩土模型、滑坡预测器、安全系数计算器或危险阈值计算器。
未实现训练、风险融合、通信、云服务、部署或遥测适配。

## 项目基线与约束

当前已按 `docs/00_TEAM_SHARED_CONTRACT.pdf`（Single Source of Truth）、负责人 A/B/C 文档及
[V0.1.0 Contract Alignment Review](../outputs/Contract_Alignment_Review_v0.1.0_2026-09-25.md)
核对职责和数据边界。V0.1.1 仍是工作站上的独立模拟器；B 尚未发布可接纳这些观测代理的正式 Training Contract。
原 V0.1.0 开发时缺少上述项目文档的事实保留在 CHANGELOG 的历史记录中。

## 架构与文件职责

```text
YAML -> 严格配置校验 -> timeline / R(t)
                            |
                    hydrology: M(t)
                            |
                slope_state: I, state, v, D
                            |
                sensor_model: 3 Soil + 2 IMU
                            |
              输出校验 -> CSV + metadata JSON
                            |
                   plot_run -> diagnostic PNG
```

物理状态与观测层分离。传感器不能反向控制物理状态；唯一 RNG 由 pipeline 创建并注入传感器。

| 文件 | 职责 |
|---|---|
| `__init__.py` | 版本号唯一代码入口 |
| `simulator/config.py` | 安全 YAML、重复键/未知字段检测、范围/时间网格校验、参数哈希 |
| `simulator/hydrology.py` | 归一化蓄水解析更新 |
| `simulator/slope_state.py` | 不稳定驱动、状态、速度、因果位移积分 |
| `simulator/sensor_model.py` | 空间延迟、土壤与 IMU 观测、噪声 |
| `simulator/pipeline.py` | 时序编排、逐行来源、观测白名单、输出/metadata校验和无覆盖保存 |
| `scripts/run_sim.py` | 仿真 CLI，打印运行摘要 |
| `scripts/plot_run.py` | 八面板离线调试图，包含五类状态刻度与转移线 |
| `configs/*.yaml` | 三个可复现基础场景，所有动力学和传感器参数显式给出 |
| `tests/test_simulator.py` | 场景、因果性、公式、边界、schema、CLI、绘图、复现性及文件保护测试 |
| `requirements.txt` | 本次验证使用的五项直接依赖固定版本 |
| `outputs/.gitkeep`、`.gitignore` | 保留默认输出目录，排除实验结果与缓存 |
| `CHANGELOG.md` | 本次起的实际修改记录；不伪造此前历史 |

`simulator/`、`scripts/`、`tests/` 下的 `__init__.py` 声明包。

## 安装、运行和测试

Python **3.11+**；命令在包含 `physics_sim/` 的父目录执行：

```bash
python3 -m venv work/.venv
source work/.venv/bin/activate
python -m pip install -r physics_sim/requirements.txt
python -m pytest physics_sim/tests -q

python -m physics_sim.scripts.run_sim --config physics_sim/configs/normal.yaml
python -m physics_sim.scripts.run_sim --config physics_sim/configs/rain_no_failure.yaml
python -m physics_sim.scripts.run_sim --config physics_sim/configs/heavy_rain_failure.yaml

# 把 <run_dir> 替换为 CLI 实际打印的目录。
python -m physics_sim.scripts.plot_run --csv <run_dir>/simulation.csv
```

`run_sim --output-dir <path>` 可指定输出根目录；默认 `physics_sim/outputs/`。
每次使用原子目录分配创建 `run_<hash前12位>_<唯一后缀>/`，内有 `simulation.csv` 和 `metadata.json`。
目录名是每次执行的**artifact identity**；CSV/metadata 中的逻辑 `run_id=sim_<完整parameter_hash>`。
同配置和 seed 重跑会得到相同逻辑 run_id、逐行来源和 CSV 字节，但目录不同，避免覆盖已有结果。
唯一后缀仅用于文件安全，不参与仿真 RNG、参数哈希或逻辑 run_id。
`plot_run --output <new.png>` 可指定 PNG；已存在目标明确报错，默认写入 CSV 同目录 `diagnostic.png`。
写入中断可能留下不完整新目录；必须同时存在且校验通过 CSV 与 metadata 才视为完整 run，不自动删除目录。
绘图使用 Agg，无 GUI 依赖。受限环境可设置 `MPLCONFIGDIR=work/matplotlib`。

## 时间语义、输入与配置

输入为完整 YAML 配置（含 seed、坡角 θ、M0、土体参数与 R(t) 生成参数）。
V0.1.1 支持无雨与单个常强度雨段；没有外部遥测适配或任意雨量 CSV 导入。
不静默补默认参数；缺失、未知、重复字段和非法值均报错。

时间为 `t_n = n*dt_s`，包含 `0` 和 `duration_s`。`dt_s` 是模拟器的数值积分与合成观测输出步长：
`dt_s=1` 只表示每秒生成一个模拟观测点，**不表示** ICM-42688-P 或 Soil 硬件以 1 Hz 采样。
00 契约中的实验 IMU 为 100/200 Hz、每路 Soil 为 2/5 Hz，Risk Engine 与 MQTT Telemetry 另有频率；
真实多率时间对齐由 B 的数据契约处理。本模块没有生成这些高频原始采样。
duration、雨段端点、土壤延迟必须是 dt 的整数倍（只允许 `1e-9` 网格商绝对浮点误差；不是物理阈值）。
`R_n` 在 `[t_n,t_(n+1))` 生效；雨段 `[start_s,end_s)` 为左闭右开。
第 n 行描述 t_n 的状态；M_n 使用 R_(n-1) 更新，D_n 使用 v_(n-1) 积分。最后一行没有后续积分。

| 配置字段 | 单位、范围与作用 |
|---|---|
| `simulator_version` | 必须为 `0.1.1` |
| `seed` | 非负整数，唯一 numpy Generator 种子 |
| `simulation.duration_s`, `dt_s` | s，有限且 >0；duration≥dt；决定模拟积分/观测输出网格，不等于硬件采样率 |
| `slope.theta_deg` | degree，0–90；驱动中的角度因子 |
| `soil.initial_moisture` | normalized 0–1；不是体积含水率 VWC |
| `soil.infiltration_rate` | `(mm/h)^-1 s^-1`，≥0；把雨强变成储水增长率 |
| `soil.drainage_rate` | `s^-1`，≥0；比例排水系数 |
| `rain.type` | `none` 或 `constant` |
| `rain.start_s`, `end_s` | s；0≤start≤end≤duration，constant 要求 start<end |
| `rain.intensity` | mm/h；none 必须为0，constant 必须 >0 |
| `state_model.saturation_threshold` | 无量纲 I；进入 SATURATION 的下界 |
| `state_model.creep_threshold` | 无量纲 I；进入 CREEP 的下界 |
| `state_model.slip_threshold` | 无量纲 I；进入 INCIPIENT_SLIP 的下界 |
| `state_model.failure_threshold` | 无量纲 I；进入 FAILURE 的下界 |
| `state_model.creep_rate`, `slip_rate`, `failure_rate` | synthetic m/s；严格 0<creep<slip<failure |
| `sensor.imu_noise_std` | degree；每次 tilt 独立高斯噪声标准差，≥0 |
| `sensor.soil_noise_std` | normalized units；土壤独立高斯噪声标准差，≥0 |
| `sensor.vibration_noise_std` | m/s²；RMS proxy 独立高斯噪声标准差，≥0 |
| `sensor.soil_sites.{top,middle,toe}.response_coefficient` | 无量纲 [0,1]；相对 M0 变化增益 |
| `sensor.soil_sites.{top,middle,toe}.delay_s` | s，0–duration；仅回看历史的响应延迟 |
| `sensor.imu_sites.{top,toe}.base_tilt_deg` | degree；初始观测基线，不等于坡角 |
| `sensor.imu_sites.{top,toe}.tilt_gain_deg_per_m` | degree/m，≥0；latent D 到 tilt 的线性增益 |
| `sensor.imu_sites.{top,toe}.vibration_base_mps2` | m/s²，≥0；振动代理基线 |
| `sensor.imu_sites.{top,toe}.vibration_gain_per_s` | 1/s，≥0；速度到加速度幅值代理的增益 |

四个阈值严格满足 `0 < saturation < creep < slip < failure <= 1`，都作用于 I。
全部数值必须有限；布尔值不能充当数值。低层函数供使用已验证参数的 pipeline 调用。
时间设置、seed、版本与文件策略属于软件配置；其余示例物理/观测值均为 **SIMULATION_ONLY**，涉及真实使用时均为 **TODO_CALIBRATION**。

## 实际公式与 Physics assumptions

### 水文

```text
a = infiltration_rate * R_n        [s^-1]
b = drainage_rate                 [s^-1]
dM/dt = a*(1-M) - b*M
q = a+b
q > 0: M_(n+1) = M_n + (a/q - M_n) * (-expm1(-q*dt))
q = 0: M_(n+1) = M_n
```

这是雨强在单步内恒定时的解析积分，替代容易越界的显式 Euler。
结果最后限制到 [0,1]，只保护舍入误差，不用截断掩盖不稳定积分。溢出或非有限数尽早报错。
无雨时 `M_(n+1)=M_n*exp(-b*dt)`；有雨时向平衡值 `a/(a+b)` 演化。
**雨不保证任何初始条件下都增加水分**：当 M 高于该平衡值时仍可排水。示例雨场景选在平衡值以下。
模型没有空间水流、土体守恒质量、蒸发、径流或孔压，不是 Richards Equation 的实现。

### 状态、速度和位移

```text
I_n = M_n * sin(theta_deg*pi/180)
I < saturation                 -> NORMAL
saturation <= I < creep        -> SATURATION
creep <= I < slip               -> CREEP
slip <= I < failure             -> INCIPIENT_SLIP
failure <= I                   -> FAILURE

v_n = 0 / 0 / creep_rate / slip_rate / failure_rate
D_0 = 0
D_(n+1) = D_n + v_n*dt
```

I 是无量纲模拟驱动，**不是真实安全系数**。速度为分段常量，不模拟加速度或应力应变。
失败前允许按驱动回落到较低状态；不使用滞回。FAILURE 吸收，仅重新初始化 run 可解除。
阈值恰好相等时进入较高状态。极大 dt 或高初始 M 可跳过状态；不为补齐状态而人为排队。
提供的重雨参数和 dt 能覆盖全部五态；失败不取决于“下过雨”或计时器。
Failure time 是首次采样到 FAILURE 的网格时间；无失败为 JSON null，初始失败为 0。
它不进行跨步插值，也不是现实灾害发生时间。

## Sensor assumptions

```text
j = max(0, n-delay_s/dt)
soil_site(n) = clip(M0 + response_coefficient*(M_j-M0) + Normal(0,soil_noise_std), 0,1)
tilt_site(n) = base_tilt_deg + tilt_gain_deg_per_m*D_n + Normal(0,imu_noise_std)
tilt_rate_site(n) = (tilt_site(n)-tilt_site(n-1))/dt, n>=1
tilt_rate_site(0) = null, tilt_rate_valid(0) = false
vibration_site(n) = max(0, vibration_base_mps2 + vibration_gain_per_s*abs(v_n)
                           + Normal(0,vibration_noise_std))
```

初始前历史保持 M0。首行没有前一倾角观测，`tilt_rate` 为 CSV 空单元格 / DataFrame null，
对应每个 IMU 的 `tilt_rate_valid=false`，`observation_warmup=true`。从第二行开始后向差分有效，
两处 rate validity 为 true、warmup 为 false。warmup 仅表示当前简化差分尚无历史，
不是 B 正式窗口预热、整枚 IMU 有效性或生产质量判据。
top/middle/toe 采用不同增益与延迟，不简单复制。延迟会同时推迟增湿与排水响应。
tilt 差分使用含噪声观测，因此差分噪声随 dt 变化；没有独立 tilt-rate 噪声。
振动字段采用 m/s² 的合成 RMS 幅值代理，**不是从原始加速度窗口计算的 RMS**。
所有噪声独立、零均值高斯，土壤/振动截断后会产生边界偏差；不模拟相关漂移、缺测或温度效应。
这些均为未标定的 synthetic observation assumptions，不能声称是真实沙盘传播/仪器响应。

## Data Contract Boundaries

| 数据类型 | 定义与用途 | 本模块当前状态 |
|---|---|---|
| Simulator Observation CSV | 含合成来源、物理隐变量/阶段和 2 IMU + 3 Soil 观测代理的调试/验证产物 | 本模块输出；`observation_schema_version=physics_sim.observation.v0.1.1` |
| Experiment CSV | A 采集的真实实验原始数据；00 契约固定最小表头为 `run_id,timestamp_ms,top_ax,top_ay,top_az,top_gx,top_gy,top_gz,toe_ax,toe_ay,toe_az,toe_gx,toe_gy,toe_gz,soil_top_raw,soil_middle_raw,soil_toe_raw,flow_lpm,rain_level,label` | 本模块不生成；Synthetic CSV 不得冒充它 |
| `zhifang.telemetry.v2` | NODE/GW/Atlas 正式运行时消息，使用 `device_id + boot_id + seq` 身份及契约规定的 null/validity/单位 | 本模块不生成；其 schema 名不能用于本 CSV |

未来若需要接入 B 的训练数据，应由独立 adapter 根据 B 发布的 Features、Labels、Window、Split、Leakage、Metrics、Synthetic Constraints 完成
`Simulator Observation -> Adapter -> Training Dataset`。正式设备消息测试也需要独立 Test Adapter 和 A/C 的验证样例；
本模块没有生产 Telemetry Adapter。当前 `contract_status=PRE_B_TRAINING_CONTRACT` 表示这些观测代理尚未被 B 的正式训练契约接纳。
它不表示 `training_ready` 或 `production_ready`。`soil_*` 为归一化合成值，不是 ADS1115 raw、0–100 相对湿润度或 VWC；
当前 tilt 是 D 的有符号线性代理，`vibration_rms` 是速度相关幅值代理，不能与 B 的倾角/动态加速度窗口 RMS 定义直接等同。

## 输出、单位与泄漏边界

CSV 有26列；它是带来源、标签和 latent 变量的**调试/合成数据集，不可整表当作部署模型输入**。

| 字段 | 单位与用途 |
|---|---|
| `run_id` | `sim_<完整parameter_hash>`，确定性的逻辑 synthetic run 身份；不是设备身份 |
| `row_index` | 从 0 连续递增的行号；与 `run_id` 联合唯一定位一个观测 |
| `is_synthetic`, `generator_version`, `seed`, `parameter_hash`, `parent_run` | 逐行来源；当前 `true`、`0.1.1`、非负整数、规范化配置 SHA-256、空值；均非模型输入 |
| `time_s` | second；时间索引，不在观测特征白名单内 |
| `rain_intensity` | mm/h；合成驱动，不在 NODE-01 观测白名单内 |
| `state` | 五态 synthetic label，不作输入 |
| `moisture_latent` | normalized 0–1；latent，不是 VWC |
| `instability_drive` | 无量纲 latent |
| `displacement_latent` | synthetic metre；NODE-01 没有直接测量 D，不作传感器输入 |
| `velocity_latent` | synthetic m/s；latent |
| `soil_top`, `soil_middle`, `soil_toe` | normalized 0–1；合成观测，不是 VWC |
| `imu_top_tilt_deg`, `imu_toe_tilt_deg` | degree；合成观测 |
| `imu_top_tilt_rate_dps`, `imu_toe_tilt_rate_dps` | degree/second；因果后向差分；首行空值表示未知 |
| `imu_top_vibration_rms`, `imu_toe_vibration_rms` | m/s²；合成幅值代理 |
| `observation_warmup` | boolean；仅首行为 true，表示当前差分观测尚无历史 |
| `imu_top_tilt_rate_valid`, `imu_toe_tilt_rate_valid` | boolean；仅首行为 false，其余为 true；仅对应当前模拟角速度差分 |

`pipeline.observation_features(frame)` 是 V0.1.0 保留的兼容 API 名称，**仅返回九个 Soil/IMU 观测代理值**，
不表示这些列是 B 的正式训练 Feature；首行 rate 仍为空。使用者需同时读取上述 validity/warmup 字段。
该白名单排除来源、state、所有 latent、rain、time 与 metadata。不得使用 `select_dtypes` 等方式将整个 CSV 数值列作为输入。
观测只读取当前/历史状态，不读取 failure_time、未来雨量、未来水分或未来标签。
下游窗口/训练划分仍须独立保证因果窗口与按 run 划分；V0.1 不实现训练或部署适配。

Metadata 包含与 CSV 行一致的逻辑 `run_id`、`is_synthetic=true`、`generator_version`、`seed`、`parent_run=null`、
`parameter_hash`、`failure_time_s`、完整校验后 `config`、`created_by`、`generator`、科学边界声明、
行数、全部输出单位、观测列名、Python/五项依赖版本、CSV 字节 SHA-256，
以及 `artifact_kind=simulator_observation_csv`、`observation_schema_version=physics_sim.observation.v0.1.1`、
`contract_status=PRE_B_TRAINING_CONTRACT`。保存前校验 metadata 与 CSV 的来源一致；CSV 切分/拼接后仍须保留
`run_id + row_index` 和逐行来源。该机制不提供真实数据或 B Training Table 的转换器。
parameter_hash 是规范化配置 JSON（排序键、固定分隔符、禁 NaN）的 SHA-256；包含 seed/version，排除时间与文件路径。
连续数值 1 和 1.0 规范化为同值；YAML 格式、注释和键顺序不影响哈希。

## 可复现性与验证

唯一随机源为 `numpy.random.default_rng(seed)`；固定 Soil/IMU 站点与抽样顺序。
同 config+seed 在同代码/依赖/运行环境下，DataFrame 核心数值、来源字段和 CSV 字节相同。
逻辑 run_id 相同，执行目录不同；同环境重复执行的 metadata 和 CSV 字节 hash 也相同。
不同平台/依赖版本不承诺逐位一致，因此保留运行版本与 CSV hash；跨环境比较时不得只凭逻辑 run_id 假定观测字节相同。
需求中的8类测试之外，还覆盖解析公式、时间语义、延迟、状态等号/恢复/吸收、初始失败、噪声隔离、
未来降雨前缀不变、延长 run 前缀不变、字段白名单、YAML 错误与参数边界、非有限输出、非1秒采样单位、错误 CLI 不创建结果、CLI 与绘图及防覆盖。
实际验收结果记录在 CHANGELOG 和随交付的验证报告，不把未运行测试写成通过。

## 三个基础场景

共同配置：600s，dt=1s，seed=42，θ=45°，M0=0.2。

| 配置 | 雨量设置 | 要求 |
|---|---|---|
| `normal.yaml` | 无雨 | 始终 NORMAL；排水、D=0、无失败 |
| `rain_no_failure.yaml` | [30,450)s，10 mm/h | 增湿、允许 SATURATION，绝不失败 |
| `heavy_rain_failure.yaml` | [30,600)s，60 mm/h | 按五态顺序覆盖并最终 FAILURE |

## TODO_CALIBRATION

必须通过真实受控实验确定或重新设计：

- 土壤传感器读数与归一化水分的对应关系；未标定前禁止称为 VWC。
- 入渗、排水、初始储水状态，以及雨强到水分响应的单位转换与适用时间尺度。
- 坡角/含水状态/材料特性到驱动的结构及阈值；当前阈值不能直接迁移现实。
- 蠕变/滑移/失败速度与位移尺度；真实实验需要独立位移真值，不能用模拟 D 充当测量。
- 三处水分响应增益、延迟与空间传播机制。
- IMU 基线、安装姿态、位移到倾角增益、噪声、漂移及不同采样率影响。
- 振动幅值与速度/状态的关系，真实 RMS 窗口定义、频率响应和仪器单位。
- 状态标签与 failure ground truth 的实验判据、时间分辨率、可恢复性。

## 当前限制与维护规则

没有真实预测能力、真实危险阈值、安全系数或已验证物理参数。
仅单体蓄水、静态坡角、离散速度、线性观测；不表示多维滑面、几何变形、真实破坏机制或传感器全部误差。
FAILURE 后持续匀速和 D 到 tilt 的无限线性关系仅适用于软件场景；长时间外推可能不具物理意义。
一次 run 在内存中保存全量历史，内存使用随 duration/dt 增长；调用者应合理控制样本数。
CSV 必须与观测白名单区分使用；外部使用者错误选取字段仍可能泄漏。
已取得 00 及 A/B/C 项目文档；B 的正式 Training Contract 与 A 的真实实验 CSV 尚待交接，不能据此声称已完成集成验收。

每次有意义修改均更新本 README 的当前状态，并在 CHANGELOG 添加实际记录。
公式、阈值、状态、传感器映射、随机性、单位、schema、bug fix 和测试变化必须记载，不能伪造历史。
修改遵循 Understand → Inspect → Plan → Implement → Test → Review → Document；先测试再声明完成。
