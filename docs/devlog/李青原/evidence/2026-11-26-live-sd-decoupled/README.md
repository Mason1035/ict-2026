# NODE-01 `0.2.2-live-sd-decoupled` 实板原始串口证据说明（2026-11-26 ～ 2026-11-27）

本目录应团队审阅（队员 C 何宇轩 PR 核对需求）提供 **5 份未经删改、经扫描确认无任何密码/密钥/凭据的 `COM7` 实板原始串口捕获日志**，覆盖 `0.2.2-live-sd-decoupled` 修复前基线及 `sdspi_host.c` `IDLE0 task_wdt` 修复版的有卡、无卡、RTS 软复位及真冷启动全部实测现场（均通过 App-only `0x10000` 烧录或零写入读取，未动 Bootloader/分区表/NVS）。

> 状态边界：**`TEST_ONLY / REAL_SENSOR_DIAGNOSTIC / NEED_HARDWARE_RETEST`**。原始日志仅作为工程采集/SD解耦/看门狗修复证据，不构成整机、物理标定或 Atlas 入库闭环验收。线上 `RiskTask` / `AlarmTask` 保持 `UNARMED`、`hardware_enabled=false`、`risk.* = null`。

---

## 一、被测固件版本与产物哈希

| 版本阶段 | BIN 大小 | BIN SHA-256 | App ELF SHA-256 | 关键差异 |
|---|---:|---|---|---|
| 修复前 `0.2.2-live-sd-decoupled` | `867856` B | `e1115dc1ebd183a0c19211d6fb79caa7ea369d82a82ff8a8dd79ca8e7ce1b33b` | `7dcb8cc4b4cd42ad14cac55cb373e453532668bd1e3d01da030b44aecdaf2a21` | `CONFIG_NODE01_SD_OPTIONAL_FOR_LIVE=y` |
| WDT 修复版 `0.2.2-live-sd-decoupled` | `867968` B | `7f410f44f68ac26011d46cdd317594320537232ea86ce5cf199d733006b0947d` | `ad03a533db89b30980d737056bd3e438bc25c286ed3200ad6b72ba3bd79bc751` | `sdspi_host.c` 加入 `SDSPI_POLL_FAST_SPIN_US = 2000` 超时后 `vTaskDelay(1)` |

---

## 二、5 份原始串口日志总表（完整保留全部现场，不挑拣）

| 序号 | 原始日志文件名 | 时长 / 字节 | App ELF | `boot_id` | 关键实测结果（逐实测如实记录） |
|---:|---|---|---|---:|---|
| 1 | [uart_022_pre_wdtfix_with_sd_45s.log](./uart_022_pre_wdtfix_with_sd_45s.log) | 45.00 s / `55850` B | `7dcb8cc4...` | — | 插卡冷稳运行：SD 挂载/开文件早于 Wi-Fi；`IMU_TOP 100.00 Hz / TOE 99.46 Hz (err=0)`，`SOIL 63/63/63 err=0`，`I2C errors=0`，`FLOW queue_drop=0`，`SD active=1 files_verified=1 errors=0`（首段 `N0009470.CSV` 4000 行校验过），`COMM wifi=1 mqtt=1 enqueued=30 rejected=0`，`WDT=0`。 |
| 2 | [uart_022_pre_wdtfix_no_sd_35s.log](./uart_022_pre_wdtfix_no_sd_35s.log) | 35.14 s / `49278` B | `7dcb8cc4...` | — | 拔卡基线：`t=6877 ms` 进入 `SD_STARTUP_DEGRADED`，`MQTT enqueued=16 rejected=0`，`IMU 99.60/99.08 Hz err=0`，`I2C errors=0`；**但 `t=21397 ms` 录得 1 次非致命 `IDLE0 task_wdt` 告警**（直接触发本轮根因修复）。 |
| 3 | [uart_022_wdtfix_no_sd_45s.log](./uart_022_wdtfix_no_sd_45s.log) | 45.00 s / `65166` B | `ad03a533...` | `17` | **WDT 修复后拔卡 45 s**：**`WDT=0`（零看门狗/Panic/Backtrace）**；`t=6866 ms` 进入 `SD_STARTUP_DEGRADED`；`COMM enqueued=25 rejected=0`；`IMU_TOP 3741 (100.00 Hz, max_gap_us=14988)`、`IMU_TOE 3720 (99.44 Hz, max_gap_us=15760)`（较修复前 `68025/67925 us` 明显收敛）、`SOIL 75/75/75 err=0`、`I2C errors=0`、`FLOW queue_drop=0`。 |
| 4 | [uart_022_wdtfix_with_sd_rts_reset_45s.log](./uart_022_wdtfix_with_sd_rts_reset_45s.log) | 45.00 s / `68529` B | `ad03a533...` | `19` | **WDT 修复后 RTS 软复位（未给旧金士顿卡冷断电）**：`t=2416 ms` 挂载 `SD32G` 并开 `/sdcard/N0009509.CSV`，但 `t=3506 ms` 首次 `CMD24 lba=1169` 后 `CMD13` 返回 `SD_R1_MISSING rx=ff rc=0x107`（该拆机旧卡软复位不掉电常见 SPI 掉线/接触问题）；`t=6866 ms` 解耦兜底切换 `SD_STARTUP_DEGRADED`，保住 `IMU 100.00/99.45 Hz err=0`、`SOIL 76/76/76 err=0`、`I2C errors=0`、`MQTT enqueued=25 rejected=0`，**`WDT=0`**，`SD active=0 errors=9`。 |
| 5 | [uart_022_wdtfix_with_sd_cold_boot_45s.log](./uart_022_wdtfix_with_sd_cold_boot_45s.log) | 45.05 s / `62153` B | `ad03a533...` | `21` | **WDT 修复后真冷启动（拔电再插、无 RTS 软复位）**：旧卡首次 `SD_MOUNT` 超时（`errors=1`）于 `t=6866 ms` 触发 `SD_STARTUP_DEGRADED`；**`t=8376 ms` `StorageTask` 后台自动挂载恢复 `SD32G` 成功**，与 Wi-Fi/MQTT/100Hz 采集并发写 `/sdcard/N0009518.CSV` 并滚动到 `N0009519.CSV`（`4000` 行 `crc32=d4b7a294` 正在 `SD_VERIFY_BEGIN` 回读中，45 s 截断时刻 `verifying=1, files_verified=0`）；累计写入 **`5008` 行（恢复后 `append=5008 fail=0, flush=18 fail=0, verify_4KiB=63 fail=0`）**，`queue_drop=0`（PSRAM 队列峰值 `2772/16384`），`IMU_TOP 100.05 Hz err=0`、`TOE 99.50 Hz err=0`、`SOIL 76/76/76 err=0`、`I2C errors=0`、`COMM enqueued=24 rejected=0`、**`WDT=0`**。（注：拆机旧卡在该轮记录到 `append over100ms=122`，系旧卡慢写叠合 `2 ms` 后 `vTaskDelay(1)` 的如实观测。） |

---

## 三、实板发布身份与 `boot_id` 非复用证明（无凭据上传）

1. **实测发布身份（直接见各日志 `MQTT_PROVISIONED` 行）**：
   - `site_id`：`NODE01-STAGE23-TEST`
   - `device_id`：`NODE-01-REAL-TEST`
   - `topic`：`zhifang/v2/NODE01-STAGE23-TEST/NODE-01-REAL-TEST/telemetry`
   - `uri`：`mqtt://10.75.156.148:1883`（仅局域网端点，仓库不包含任何 NVS 二进制镜像、Wi-Fi 密码或 MQTT 账号口令）
2. **NVS `node01_id/last_boot` 单调递增核验（本机只读 `0x9000..0xf000` 解析计数键，未读取/输出 `node01_net` 凭据）**：
   - `13`：2026-11-26 首次烧录 `0.2.2` 前基线
   - `16`：2026-11-26 烧录 WDT 修复版前基线
   - `17`：WDT 修复版无卡 45 s（日志 3）
   - `19`：WDT 修复版带卡 RTS 软复位 45 s（日志 4 结束只读回读 `[(2, 19)]`）
   - `21`：WDT 修复版带卡真冷启动 45 s（日志 5 结束只读回读 `[(2, 21)]`）
   - **确认完全未复用历史已消耗 `boot_id` `1 / 3 / 4`。**

---

## 四、明确未完成与待复测边界（`NEED_HARDWARE_RETEST`）

1. **Atlas HTTP 入库数量核对未完成**：运行期间 `192.168.31.225:1883` TCP 可达，但本机 `127.0.0.1:8000` SSH 隧道关闭（`UNREACHABLE`），串口日志保留 `Atlas receipt unverified`。
2. **新闪迪/铠侠 SD 卡长时完整回读闭环**：当前使用的是拆机旧金士顿 32GB 卡，且第 5 份真冷启日志停在 45 s 截断窗口（第 1 段已写完滚动并处于 `verifying=1`，尚未跨过第 132 块 `SD_READBACK verified`）。待 11 月 28 日左右新 SD 卡与 Plan A+ 装盒到货后，将补跑完整装盒有卡验证（同步评估是否将 `SDSPI_POLL_FAST_SPIN_US` 从 `2000 us` 适当放宽至 `50000~200000 us` 以减少健康/老化卡长写让步开销）并同步推进标定补测与 7 场沙盘 Run。
3. **安全/告警边界**：会签与物理标定冻结前，实板线上严格维持 `UNARMED`、`hardware_enabled=false`、`risk.* = null`。
