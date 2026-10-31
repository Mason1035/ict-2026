# NODE-01 SANDBOX-01_STABLE_CAPTURE_V1

状态：**SANDBOX_CAPTURE_STABLE_CANDIDATE / UNCALIBRATED / INTEGRATION_NOT_READY**。这是未标定工程采集稳定候选，不是整机、风险算法或突然断电验收通过。

## 被测试固件的准确身份

来源：ESP-IDF v5.5.3 / C++17，既有构建 `build-v01-fifteenth-board-diag-output-wdt-fix`；本次只整理并提交已有代码，没有重新编译或烧录。

| 产物 | 字节数 | SHA-256 |
|---|---:|---|
| zhishao_node01.bin | 386256 | `2be566f0195877656610ae2ebf17437ae41fdae280457f7b914e4dd64fadd422` |
| zhishao_node01.elf | 6160688 | `288e76253c36efcc1939959443c2ae58c245eb2ea0f7ba667e950d9d2372119d` |

本地冻结档案位于仓库相对路径 `docs/test_records/NODE-01/sandbox-01-stable-capture-v1/`。入口为 README_zh.md、freeze-manifest.json、FINAL_FREEZE_REPORT_zh.md 和 tools/Verify-FrozenCapture.ps1。完整原始证据、二进制和源码快照保留本地，本次不上传。普通clone不会得到这些文件，不能把本说明当作原始证据本身。

138份声明源码在本次提交前匹配冻结Manifest、源码快照和当前工作区。发布范围包含稳定生产实现、对应Host测试和PC控制台Python模块；含个人绝对路径的本机PowerShell入口、旧工程README及历史分析报告不随本次提交发布，原件不修改。已跟踪旧文件仍保留历史，不通过删除提交重写它们。新默认配置摘录和本文仅作为公共说明，不是额外实板验证。

## 冻结能力与运行约束

- 模式 SANDBOX_EXPERIMENT_CAPTURE；日志来源 REAL_SENSOR_EXPERIMENT_UNCALIBRATED，BEG/END原始source=REAL_SENSOR；不使用模拟数据替代实测。
- `EXP START <seconds>`，配置支持30..300秒；实际测试30、120、300秒，不能推断中间每个时长均经过实测。
- `EXP STOP` 有安全提前停止的设备验收证据；`one_per_boot=1`，每次启动一场，下一场需用户重新启动并确认固件身份和READY。
- TOP 0x68 / INT1 GPIO4；TOE 0x69 / INT1 GPIO5；SDA GPIO8、SCL GPIO9；ADS1115 0x48。IMU ODR100Hz、I2C100kHz、SD SPI10MHz、Queue512、4KiB缓冲、256行同步不变。
- 保留IMU_FIRST初始化顺序、DRDY与显式fallback、生产者停止/排空、CSV length/actual_rows/CRC/EOF和END元数据校验。

## 已有真实测试及证据范围

四场的固件ELF身份均MATCH，设备FINALIZED与PC会话SUCCEEDED已在本地归档重新核对。本次未运行任何新的实板测试。

| 场次 | 实验ID | 实际时长 | 验证范围与限制 |
|---|---|---:|---|
| 30s TIME_LIMIT | NODE01-dfa24d7fe6628a21-N0000011.CSV | 30.001480s | 设备验收及完整PC会话；SD三原件未独立核验 |
| 120s TIME_LIMIT | NODE01-42092cdfecd1ac44-N0000012.CSV | 120.001424s | 设备验收及完整PC会话；SD三原件未独立核验 |
| USER_STOP（请求30s） | NODE01-4f953b927982721b-N0000013.CSV | 16.528617s | 设备采集验收及完整PC会话；SD三原件未独立核验；Trace不完整 |
| 300s TIME_LIMIT | NODE01-66ad3aa6b8103f8b-N0000014.CSV | 300.002046s | 设备验收、完整PC会话与真实BEG/CSV/END独立字节/行级核验 |

300秒：CSV 8555116字节、61631行、22列，CRC32 `97b3ee9c`，SHA-256 `20ca92b537a3d2c1353a2da59ec2c5482c8c184faea7c60395c20c1631cb51a2`。acquisition_index为0..61630连续。TOP29997、TOE29834、Soil三路各600，全部Valid/error=0；produced=enqueued=dequeued=accepted=verified_rows=61631，queue_drop=0，internal_drop=0。Queue峰值155/512；I2C errors/local timeout=0；日志未观察到Task Watchdog。原session的HOST_FILES_NOT_VERIFIED未改写，300秒离线核验另行记录。

## 仍然存在的限制

- 300秒 `imu_deadline_misses=1`、`work_over_10ms=1`、`cycle_max_us=51917`；精确发生位置及根因未确认，不能写成全程miss=0。
- MicroSD append最大729.314ms、flush_periodic最大691.905ms；这是包含调度/等待的墙钟耗时，不能直接认定卡硬件根因。当前零丢失不等于无长尾或突然断电安全。
- USER_STOP Trace `missing_links=1 / integrity=INCOMPLETE`，不等于该场采集失败，也不能隐去该诊断缺口。
- 300秒Trace仅所保留关联链完整；anomalies_total=2816 / outside_window=2812不是2816次传感器失败，不保证全程完整历史。
- calibration_status=NOT_READY；ADC原始值不是湿度百分比。CSV保留 `not experiment CSV; not training data`，不能直接作为已标定正式风险训练集。
- timestamp_ms为空、time_synced=false；PC目录和BEGIN观察时间不是逐行设备UTC。
- risk=null；LoRa、报警与完整预警联动未验收。历史I2C根因不是100%唯一证明。最大连续实测300秒，未验证写入中突然断电或更长时长。

## 配置与PC控制台使用边界

`firmware/node01/sdkconfig.defaults` 是通用硬件基线；新增 `config/sandbox-capture-v1.defaults` 只摘录被冻结配置中的应用模式、时钟和控制台选项，原值未变，不含凭据。可在已激活的ESP-IDF v5.5.3环境中为**全新独立目录**组合两份defaults，并使用该目录自己的SDKCONFIG；不得覆盖原受测build目录。该摘录不是完整sdkconfig，不保证重编译哈希相同；新构建必须单独核对配置与测试，不能借用上方旧固件身份。

PC模块需要Python3.11+和 tools/experiment_console/requirements.txt 中的依赖，安装到独立PC虚拟环境，不装入固定ESP-IDF环境。在 `firmware/node01/tools` 下可调用：

```powershell
python -B -m experiment_console.console --help
python -B -m experiment_console.console --port <实际COM口> --manifest <本机原候选manifest.json> --timezone Asia/Shanghai
python -B -m experiment_console.archive --sd-dir <实际SD目录> --session <实际session.json> --manifest <本机原候选manifest.json> --dry-run
```

上述硬件相关命令仅供用户之后手动使用，本次未执行。串口必须独占，不能与烧录器/其他监视器同时打开。console启动会实际核对Manifest所列产物；请使用原候选Manifest及它指向的本机文件，不能把公开说明或freeze-manifest当作同一种输入。新clone没有本地LATEST.json或完整产物，应显式提供有效Manifest；不能跳过身份检查。

对应Host Tests保留在 tests/，其TEST_ONLY测试不是实板PASS。本机Test-Host.ps1包含个人SDK路径，此次不发布该未提交版本；已有历史脚本不代表全部新增测试的可移植入口。可移植Host入口和构建环境治理另行处理，本轮不修改冻结代码或声称完成可复现构建。
