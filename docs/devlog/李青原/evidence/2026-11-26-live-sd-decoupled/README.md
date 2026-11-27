# NODE-01 `0.2.2-live-sd-decoupled` 实板原始串口证据说明（2026-11-26 ～ 2026-11-27）

本目录应团队审阅（队员 C 何宇轩 PR #31 复核需求）提供 **5 份未经删改、经扫描确认无任何密码/密钥/凭据的 `COM7` 实板原始串口捕获日志**、只读 `NVS boot_id` 摘录 [nvs_boot_id_readonly_excerpt.txt](./nvs_boot_id_readonly_excerpt.txt) 与仓库 LF 校验清单 [SHA256SUMS.txt](./SHA256SUMS.txt)。

- **换行与校验口径**：本目录通过局部 [.gitattributes](./.gitattributes)（`text eol=lf`）统一以 **LF (`\n`)** 格式入库，[SHA256SUMS.txt](./SHA256SUMS.txt) 亦严格按 **仓库 LF 字节流** 生成，确保 `sha256sum -c SHA256SUMS.txt` 在 Linux / macOS / Windows 检出树下均直接通过。
- **状态与安全边界**：**`TEST_ONLY / REAL_SENSOR_DIAGNOSTIC / NEED_HARDWARE_RETEST`**。原始日志仅作为工程采集、SD 解耦与 `IDLE0 task_wdt` 修复软件/阶段证据，**不代表整机验收、物理标定、Atlas HTTP 入库闭环或批准加载未标定配置**。线上 `RiskTask` / `AlarmTask` 继续维持 `UNARMED`、`hardware_enabled=false`、`risk.* = null`。

---

## 一、被测固件版本与配置对应关系（保留旧版对照）

> **重要配置说明**：仓库根下跟踪的 `firmware/node01/sdkconfig` 仍是**网络关闭的诊断基线配置**；本目录实板联网采集全部使用在**仓库外独立临时目录**通过 `sdkconfig.defaults;config/live-mqtt-r4-fix.defaults` 隔离编译的镜像：

| 版本阶段 | BIN 大小 | BIN SHA-256 | App ELF SHA-256 | 编译配置与关键差异 |
|---|---:|---|---|---|
| 修复前 `0.2.2-live-sd-decoupled` | `867856` B | `e1115dc1ebd183a0c19211d6fb79caa7ea369d82a82ff8a8dd79ca8e7ce1b33b` | `7dcb8cc4b4cd42ad14cac55cb373e453532668bd1e3d01da030b44aecdaf2a21` | `sdkconfig.defaults;config/live-mqtt-r4-fix.defaults`（开启 `CONFIG_NODE01_SD_OPTIONAL_FOR_LIVE=y`） |
| WDT 修复版 `0.2.2-live-sd-decoupled` | `867968` B | `7f410f44f68ac26011d46cdd317594320537232ea86ce5cf199d733006b0947d` | `ad03a533db89b30980d737056bd3e438bc25c286ed3200ad6b72ba3bd79bc751` | 同上 defaults + `sdspi_host.c` 加入 `SDSPI_POLL_FAST_SPIN_US = 2000` 超时后 `vTaskDelay(1)` |

---

## 二、5 份原始串口日志总表（精确按日志数值如实记录）

| 序号 | 原始日志文件名 | 时长 / LF字节数 | App ELF | `boot_id` | 关键实测结果（不虚高口径，精确按日志实值） |
|---:|---|---|---|---:|---|
| 1 | [uart_022_pre_wdtfix_with_sd_45s.log](./uart_022_pre_wdtfix_with_sd_45s.log) | 45.00 s / `55429` B | `7dcb8cc4...` | — | 修复前插卡：SD 挂载/开文件早于 Wi-Fi；`IMU_TOP valid=4223 (100.00 Hz, err=0)`、`IMU_TOE valid=4201 (99.46 Hz, err=0)`，`SOIL valid=63/63/63 (err=0, t=34.23s, ~1.84 Hz uptime / ~1.95 Hz active)`，`I2C errors=0`，`FLOW queue_drop=0`，`SD active=1 files_verified=1 errors=0`（`N0009470.CSV` 4000 行校验通过），`MQTT_CONNECTED; Atlas receipt unverified` + 本机 `enqueued=30 rejected=0`，`WDT=0`。 |
| 2 | [uart_022_pre_wdtfix_no_sd_35s.log](./uart_022_pre_wdtfix_no_sd_35s.log) | 35.14 s / `48878` B | `7dcb8cc4...` | — | 修复前拔卡：`t=6877 ms` 进入 `SD_STARTUP_DEGRADED`；`IMU_TOP valid=2451 (99.60 Hz, err=0)`、`IMU_TOE valid=2437 (99.08 Hz, err=0)`，`SOIL valid=50/50/49 (err=0, t=31.82s)`，`I2C errors=0`，`MQTT_CONNECTED; Atlas receipt unverified` + 本机 `enqueued=16 rejected=0`；**但 `t=21397 ms` 录得 1 次非致命 `IDLE0 task_wdt` 告警**。 |
| 3 | [uart_022_wdtfix_no_sd_45s.log](./uart_022_wdtfix_no_sd_45s.log) | 45.00 s / `64676` B | `ad03a533...` | `17` | **WDT 修复后拔卡 45 s**：**`WDT=0`**；`t=6866 ms` 进入 `SD_STARTUP_DEGRADED`；`IMU_TOP valid=3741 (100.00 Hz, max_gap_us=14988, err=0)`、`IMU_TOE valid=3720 (99.44 Hz, max_gap_us=15760, err=0)`、`SOIL valid=75/75/75 (err=0, t=44.65s, ~1.68 Hz uptime / ~1.95 Hz active)`、`I2C errors=0`、`FLOW queue_drop=0`、`MQTT_CONNECTED; Atlas receipt unverified` + 本机 `enqueued=25 rejected=0`。 |
| 4 | [uart_022_wdtfix_with_sd_rts_reset_45s.log](./uart_022_wdtfix_with_sd_rts_reset_45s.log) | 45.00 s / `67969` B | `ad03a533...` | `19` | **WDT 修复后 RTS 软复位（未给旧金士顿卡冷断电）**：`t=2416 ms` 挂载 `SD32G` 并开 `/sdcard/N0009509.CSV`，但 `t=3506 ms` 首次 `CMD24 lba=1169` 后 `CMD13` 返回 `SD_R1_MISSING rx=ff rc=0x107`；`t=6866 ms` 解耦切换 `SD_STARTUP_DEGRADED`，`IMU_TOP valid=3762 (100.00 Hz, err=0)`、`IMU_TOE valid=3741 (99.45 Hz, err=0)`、`SOIL valid=76/76/76 (err=0, t=44.88s, ~1.69 Hz uptime)`、`I2C errors=0`、`MQTT_CONNECTED; Atlas receipt unverified` + 本机 `enqueued=25 rejected=0`，**`WDT=0`**，`SD active=0 errors=9`。 |
| 5 | [uart_022_wdtfix_with_sd_cold_boot_45s.log](./uart_022_wdtfix_with_sd_cold_boot_45s.log) | 45.05 s / `61752` B | `ad03a533...` | `21` | **WDT 修复后真冷启动（拔电再插、无 RTS 软复位）**：旧卡首挂载超时仍保留 **`errors=1`**，于 `t=6866 ms` 触发 `SD_STARTUP_DEGRADED`；**`t=8376 ms` `StorageTask` 后台自动挂载恢复 `SD32G` 成功**，写入 `N0009518.CSV`（4000 行 `crc32=d4b7a294` 滚动到 `N0009519.CSV`），恢复后累计 **`5008` 行零写/刷/读错**（但 45 s 截断时刻正处于 `SD_VERIFY_BEGIN` 回读第 63/132 块，因此 **`verifying=1, files_verified=0`**，同时旧卡记录到 `append over100ms=122`）；`IMU_TOP valid=3780 (100.05 Hz, err=0)`、`IMU_TOE valid=3759 (99.50 Hz, err=0)`、`SOIL valid=76/76/76 (err=0, t=45.04s, ~1.69 Hz uptime / ~1.96 Hz active)`、`I2C errors=0`、`FLOW queue_drop=0`、`MQTT_CONNECTED; Atlas receipt unverified` + 本机 `enqueued=24 rejected=0`、**`WDT=0`**。 |

---

## 三、实板发布身份、`boot_id` 主机侧摘录与网络边界

1. **实板发布身份与局域网 Broker 状态**：
   - `site_id`：`NODE01-STAGE23-TEST`
   - `device_id`：`NODE-01-REAL-TEST`
   - `topic`：`zhifang/v2/NODE01-STAGE23-TEST/NODE-01-REAL-TEST/telemetry`
   - LAN Broker URI：`mqtt://10.75.156.148:1883`（五份日志均为 **`MQTT_CONNECTED; Atlas receipt unverified`** + 本机 `enqueued`，**仅证明连上局域网 Broker 并完成板端入队，不代表已核对 Atlas HTTP 入库**；仓库零凭据/无 NVS 二进制）。
2. **`boot_id` 递增核验与可复核摘录**：
   - 因串口输出本身不打印 `boot_id`，已在本目录补充 [nvs_boot_id_readonly_excerpt.txt](./nvs_boot_id_readonly_excerpt.txt)，给出四次本机只读 `0x9000..0xf000` `nvs_parser` 脱敏解析结果（`13 -> 16 -> 17 -> 19 -> 21`），确认未复用此前已消耗的 `1 / 3 / 4`。

---

## 四、明确未完成与待复测边界（`NEED_HARDWARE_RETEST`）

1. **WDT 修复版还缺一趟干净的有卡 `45s+` 且 `files_verified >= 1`（`errors = 0`）**：第 5 份真冷启日志恢复属实，但因 45 s 截断仍在校验且保留启动首挂载 `errors=1`；待 11 月 28 日左右换用新闪迪/铠侠 SD 卡后补跑完整有卡回读闭环（并视新卡实测评估 `SDSPI_POLL_FAST_SPIN_US`）。
2. **Atlas HTTP 入库核对未测**：运行期间本机 `127.0.0.1:8000` 隧道关闭（`UNREACHABLE`），`Atlas receipt unverified`。
3. **会签与装盒后续**：会签前线上维持 `UNARMED`、`hardware_enabled=false`、`risk.* = null`；三档水泵 30 s 称重、7 场沙盘 Run 与 `GPIO6/GPIO14 hardware_profile` 按计划约 11 月 28 日装盒后补齐。
