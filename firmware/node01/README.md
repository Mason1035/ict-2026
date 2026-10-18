# NODE-01 正式 ESP-IDF 固件框架

负责人：李青原。项目位置 `ict-2026/firmware/node01`，属于现有“李青原”分支；目录名是实现约定，不是新增 FROZEN 事实。版本 `0.1.0-framework`。

当前交付是运行时和接口骨架。真实传感器、Risk 标定、SD、MQTT、E220、报警输出均未完成实板验收。没有 Mock/Synthetic 运行模式，没有随机采样数据，没有发送假正常消息。

2026-09-28 最终验证：**Build PASS**（普通 Windows PowerShell，日志/产物已核验）；主机语义测试 PASS；Flash/Serial Boot NOT_RUN（当前环境未访问到 COM7）。最终 BIN 为 181632 bytes，成功构建无 warning/error；新工程实板运行仍未验证。

## 依据、基线与队友接口

- 最高事实源：仓库的 `00_TEAM_SHARED_CONTRACT`，文档基线 1.0 / 2026-09-24。本分支初始提交 `3f45c84` 尚未包含 00 文件；已只读核查 `origin/张鹏飞:00_TEAM_SHARED_CONTRACT.pdf` 与 `origin/何宇轩:docs/00_TEAM_SHARED_CONTRACT.pdf`，两者 Git blob 均为 `340f98c4eadae673f9c99367395d134d069ac221`，SHA-256 均为 `a0a5877b2ad65cd8360e304d0d93a467f6dd8904172f6206cae769bd91769d4d`。没有创建、修改或重新解释 00。
- `docs/reference/01_硬件嵌入式与系统负责人开发文档.pdf` 提供任务基线与模块边界。没有 AGENTS.md，也没有现成 firmware 工程。
- 张鹏飞 `a8e3bdb`：已检查 `algorithm/B_revised/data_intake`、`candidate_features`、`contracts/B_FORMAL_TRAINING_CONTRACT_DRAFT.json` 和 `docs/B_NEXT_STAGE_BOUNDARIES.md`。实验 CSV 为固定 20 列；候选数学函数不代表已标定规则；reason_mask 位表仍 TBD-12。未移植旧七字段演示算法或测试蒸馏阈值。
- 何宇轩 `019a03a`：已检查 `PROJECT_STATUS_AND_READINESS.md` 和 `ai_training/contracts/README.md`；正式训练、端边接入与 Atlas 尚不能视为完成。TEST_ONLY/Synthetic 与正式固件分离。未修改或合并队友分支。
- `git pull --ff-only` 已尝试：自动账号被 Windows 拒绝写 `.git/FETCH_HEAD`，用户普通终端重试遇到连接重置。仅基于已克隆的提交开发，未宣称远程已同步。

## 工程结构与职责

```text
firmware/node01/
├── CMakeLists.txt               # ESP-IDF 5.5.x、C++17、esp32s3 检查
├── sdkconfig                   # 逐字节继承昨天已验证配置；后续由 IDF 管理
├── sdkconfig.defaults
├── main/{CMakeLists.txt,app_main.cpp}
├── components/
│   ├── node_board/
│   │   ├── board.cpp
│   │   └── include/node/board.hpp
│   ├── node_contracts/
│   │   ├── protocol.cpp
│   │   └── include/node/{protocol.hpp,sampling.hpp,ports.hpp}
│   ├── node_logic/
│   │   ├── logic.cpp
│   │   └── include/node/logic.hpp
│   └── node_runtime/
│       ├── runtime.cpp
│       └── include/node/{runtime.hpp,runtime_config.hpp}
├── tests/logic_test.cpp         # TEST_ONLY 主机端语义回归
└── tools/
    ├── Activate-ESP-IDF.ps1     # 固定本机已有 SDK，不下载、不升级
    ├── sdk-safe.gitconfig      # 仅进程内信任指定 SDK 仓库
    ├── environment.lock.json
    ├── Build.ps1               # 实际构建与结果落盘
    └── Test-Host.ps1
```

每个 component 自带 CMakeLists。四个业务组件按依赖组织，不用十二个空 component 假装十二个驱动已实现：

| 文档边界 | 实际位置 | 当前能力 |
|---|---|---|
| board | node_board / board.hpp、board.cpp | 唯一 GPIO、保留脚、总线参数、板卡身份、高阻启动 |
| protocol | node_contracts / protocol.hpp、protocol.cpp | v2 类型、三元身份、缺测、四级区间；序列化/身份分配抽象接口 |
| drivers | node_contracts / ports.hpp | ICM、ADS、MicroSD 抽象接口；无具体实例或初始化成功 |
| sampling | node_contracts / sampling.hpp + node_runtime | 双 IMU/三 Soil 原始结构、逐通道时间/validity、一致快照、ISR 通知入口 |
| features | node_logic / logic.hpp、logic.cpp | 未配置结果；等待张鹏飞公式、窗口、有效性规则 |
| risk_runtime | node_logic + RiskTask | 20 Hz 执行框架；无配置时 score/level/reason_mask 全部 null |
| alarm | node_logic + AlarmTask | 本地风险/故障消费、未校准拒绝、已锁存高危不被缺测清除；硬件禁用 |
| storage | ports.hpp / storage | append、事件类别边界；event window/offline_queue 未实现 |
| mqtt_client | ports.hpp / **app_mqtt** | app_mqtt 对应文档 mqtt_client；避免与 IDF 名称混淆；无密码/地址 |
| lora | ports.hpp / lora | LoRaFrameV2 不完整类型和 transport 接口；无宽度、字节序、CRC、flags 定义 |
| comm_supervisor | ports.hpp + node_runtime | 链路/路由类型、阻塞任务；fallback/reconnect 尚未实现 |
| diagnostics | node_runtime / runtime.cpp | uptime、实际进度计数、队列深度/溢出、I2C 错误/锁超时、Risk deadline misses、栈高水位入口；reset reason 由 app_main 输出 |

依赖：`main → node_runtime → node_logic → node_contracts`，`main/node_runtime → node_board`。驱动后续引用 board，禁止各自写 GPIO 数字。

## FreeRTOS 与数据所有权

| Task | Core | Priority | Stack bytes（PROVISIONAL） | 当前行为 |
|---|---:|---:|---:|---|
| ImuTask | 1 | 7 | 4096 | 创建后阻塞等通知；未安装 GPIO ISR，不产生样本 |
| RiskTask | 1 | 6 | 4096 | xTaskDelayUntil 50 ms；一致快照 → 未配置 Feature/Risk |
| AlarmTask | 1 | 6 | 3072 | 阻塞等有限 Risk/Fault Queue；没有云 ACK 依赖 |
| SlowSensorTask | 1 | 5 | 3072 | DISABLED；后续 ADS 每路 2/5 Hz 调度 |
| CommSupervisorTask | 0 | 5 | 3072 | 创建后阻塞等通知；未注册网络 transport |
| LoRaTask | 0 | 4 | 4096 | DISABLED；TBD-11 |
| StorageTask | 0 | 3 | 4096 | DISABLED；未接 SD |
| UiHealthTask | 0 | 2 | 4096 | 每 10 秒一组健康日志；不假装阻塞任务应持续计数 |

所有 stack、queue 长度、mutex 超时集中在 `runtime_config.hpp`，均注明 PROVISIONAL / TBD-15。尚未通过 stack high-water mark、queue pressure、PSRAM、最坏 latency 压测。栈高水位只有运行到实板日志时才有实际数值。

```text
未来真实 IMU ISR ── notification ──> ImuTask（目前无 ISR）
未来 ImuTask / SlowSensorTask ── 短事务 I2C mutex ──> drivers
        └── 按通道发布 ──> SensorSnapshot（短临界区复制）
RiskTask 20 Hz ── 一致副本 ──> features/risk ──> RiskSnapshot
        └── 仅状态改变 ──> Queue[8] ──> AlarmTask（独占 Controller）
UiHealthTask ──> 原子计数 / Queue 深度 / 栈高水位 / Risk 副本
```

- System EventGroup 预留 WIFI_UP、MQTT_UP、LORA_READY、SD_OK、TIME_SYNCED、EDGE_ONLINE、IMU_TOP_OK、IMU_TOE_OK、SOIL_OK；本版全部保持 0。内部启动 gate 不代表任何外设就绪，也不会混进对外诊断位。
- 启动 gate 在全部已启用任务创建成功后释放；任何内存/任务创建失败会清理并返回错误，不输出 started。
- I2C mutex 带优先级继承；`with_i2c_transaction` 只允许短事务。ADS 等转换必须释放锁再等，当前没有创建 I2C 总线或执行事务。
- Sensor/Risk 通过短临界区复制，不把可变指针跨任务传递；Alarm Queue 按值拷贝并做 trivially-copyable 编译期检查。逐通道时间戳保留，内存一致不等于两 IMU 同步采样。
- Queue 容量固定 8，Risk 发送不阻塞，满时计数并重试未成功投递状态。本版永远无有效危险输入；正式规则启用前还须实现并压测关键事件保留/溢出策略，不能声称任意突发状态都不会丢失。
- ISR 入口只通知/请求调度，不访问 I2C/SD/MQTT/JSON；当前没有安装 ISR，也不声称其 IRAM/延迟已验证。
- 不新增无条件喂狗定时器；完整任务健康 watchdog 策略未实现。

## 协议、校准和启动安全

`TelemetryDraft` 表达 schema、site_id、device_id+boot_id+seq、timestamp_ms/unknown、uptime_ms、time_synced、双 IMU、Soil、experiment、risk、system。字符串使用借用视图，调用者必须保证生命周期；目前不跨 Queue 传递 TelemetryDraft。它是内部待组装对象，**不是已通过校验或可以发布的正式消息**。

本版没有 durable boot allocator、原始记录 seq 分配、NVS 恢复或 JSON serializer。identity 默认不存在；启动日志明确 boot_id=UNAVAILABLE、publication=DISABLED；不以固定 0 或随机 ID 冒充跨掉电唯一性。将来 serializer 必须校验完整 identity、site、非有限数、UTC/null 关系并输出所有 v2 顶层字段。内部 uint64 类型不是新的冻结线协议；不能输出超过 JSON 安全整数范围的值。

`classify` 只落实 00 的 [0,30)、[30,60)、[60,80)、[80,100]；null、NaN、Infinity、越界均返回 null。评分数学/物理阈值没有实现；features 和 risk_runtime 保持未配置。reason_mask 永远空，未定义任何位号。

BUZZER、SIREN_OUT、LoRa M0/M1/AUX/TX/RX 配置为输入高阻、无内部上下拉，不发送 E220 模式命令。这只表示固件不主动驱动，**不证明外部电路已经安全关闭**。驱动极性、外部偏置、上电瞬态仍 TBD_HARDWARE_TEST；12V 声光负载必须经合适驱动与供电，不能接 GPIO 直驱。

## 配置来源与复现

复用原路径 `C:\Users\LQY\Documents\Codex\2026-09-27\esp32-s3-windows-esp-idf-5\outputs\esp32s3_env_test` 的 sdkconfig/defaults、环境激活方法；未修改昨天工程或日志。

初始 sdkconfig SHA-256：`15c4b8755f035ad03dfa8316a0844692d6365d496e66520f2d48043294371b6e`。8 MB Flash、Octal 80 MHz PSRAM、启动内存测试和默认分区配置来自该已验证基线，没有猜测 Kconfig、修改分区表或升级依赖。**昨天板卡 PASS 不代表新项目 PSRAM/调度已实测 PASS。**

本机固定：ESP-IDF v5.5.3，SDK commit `2c211b236707889e8400c4dc5644dd5c4ee071e0`，Python 3.12.14，CMake 3.30.2，Ninja 1.12.1，Xtensa GCC 14.2.0 / esp-14.2.0_20251107。项目接受 5.5.x，附带本机激活脚本锁定现有 5.5.3，不做自动升级。

普通 PowerShell，仓库根目录：

```powershell
powershell -NoProfile -ExecutionPolicy RemoteSigned -File .\firmware\node01\tools\Build.ps1
```

或已激活的 ESP-IDF 终端：

```powershell
cd firmware\node01
idf.py --version
idf.py build
```

当前 sdkconfig target 已为 esp32s3，因此没有运行会清理配置的 `idf.py set-target esp32s3`。只在目标尚未正确设置且已核对配置时才执行它。

主机语义测试：`powershell -File .\firmware\node01\tools\Test-Host.ps1`。其 TEST_ONLY 数学输入不是 Mock 三人预联调数据，更不是真实灾害实验；测试不验证 FreeRTOS 调度或硬件。

实板可访问且 Build PASS 后，允许 `idf.py -p COM7 flash`，随后用 115200 捕获 10～20 秒启动日志。禁止 erase-flash、改分区、无限 monitor。当前未发现 COM7 时记录 FLASH_NOT_RUN / SERIAL_BOOT_NOT_RUN，不记实板 FAIL。

## 执行证据和下一步

真实结果以 [测试记录](../../docs/test_records/NODE-01/2026-09-28-framework/README.md) 和 [今日开发日志](../../docs/devlog/李青原/2026-09-28.md) 为准。自动环境的 build 已实际执行，曾在编译器路径权限检查失败；不得将 host test 或昨天的 Build PASS 冒充本工程构建结果。

下一阶段先做 **Priority 2：明确标记 Mock 的李青原 → 张鹏飞 → 何宇轩接口预联调**，复用 B 的固定 CSV 初检与 C 的 v2 接口要求；独立目录、明确来源、未知值留空，不进入实测数据集。

随后真实硬件顺序：裸板新框架启动/栈与周期记录 → 单 ICM 0x68 身份/中断/读数 → 第二枚 0x69 → ADS 已知电压/PGA 决策 → 三 Soil 逐支校准 → SD 20 MHz 读写及并发/掉电测试 → 低压报警与驱动极性 → MQTT 测试 Broker/真实 Atlas → 按具体 E220 手册与黄金帧验证备用链路。B 规则只能在版本化配置、黄金向量和标定条件满足后接入。
