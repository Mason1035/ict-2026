# NODE-01 framework / 2026-09-28 / 真实执行记录

对象：`firmware/node01`，版本 `0.1.0-framework`，ESP-IDF v5.5.3。分支“李青原”，初始 HEAD `3f45c84`；本次新增内容尚未提交/推送。不是实测传感器或灾害预警验收。

## 最终结果

| 检查 | 结果 | 证据与边界 |
|---|---|---|
| ESP-IDF Build | **PASS** | 用户普通 PowerShell 运行仓库脚本，2026-09-28 22:24:12 +08:00；原始日志和本机产物已由自动环境直接核验 |
| C++17 | **PASS** | compile_commands.json 中 5 个应用 .cpp 的最终 -std 均为 c++17；协议头还有编译期断言 |
| 最终构建 warning/error | **0** | 检查成功构建完整日志，不掩盖之前失败 |
| Flash/PSRAM 配置 | **PASS（配置检查）** | sdkconfig 与昨天已验证基线完全一致；不等于本工程实板 PASS |
| 分区表 | **UNCHANGED** | partition-table.bin 与昨天基线逐字节一致 |
| 主机语义测试 | **PASS / TEST_ONLY** | GCC 16.1.0，C++17、Wall/Wextra/Werror/pedantic；不是 RTOS 或硬件测试 |
| Flash | **NOT_RUN / FLASH_NOT_RUN** | 当前环境串口枚举 []，COM7 直接打开返回 FileNotFoundError(2) |
| Serial Boot | **NOT_RUN / SERIAL_BOOT_NOT_RUN** | 当前执行环境未访问到实板/串口，没有新工程启动日志 |
| 远程同步 | **未确认** | 自动账号无法写 .git/FETCH_HEAD；用户 pull 连接重置，基于已克隆提交开发 |

固件 `build/zhishao_node01.bin`：181632 bytes，SHA-256 `1bb7e286aa42d04cec8734224eecd9033cf3e81d9033b36790de2439632b179f`。

ELF：3522316 bytes，SHA-256 `c8376ca2e37f94b86062b6a3326b29010f3cd5d6abae77f4d9d8285f712bd235`。

sdkconfig：SHA-256 `15c4b8755f035ad03dfa8316a0844692d6365d496e66520f2d48043294371b6e`。

## 实际命令与操作

在仓库根目录核查：

```powershell
git rev-parse --show-toplevel
git branch --show-current
git remote -v
git status
git branch -a
git log -6 --oneline --all --decorate
git pull --ff-only
git ls-tree -r --name-only origin/张鹏飞
git ls-tree -r --name-only origin/何宇轩
git show origin/张鹏飞:algorithm/B_revised/docs/B_NEXT_STAGE_BOUNDARIES.md
git show origin/张鹏飞:algorithm/B_revised/candidate_features/README.md
git show origin/张鹏飞:algorithm/B_revised/contracts/B_FORMAL_TRAINING_CONTRACT_DRAFT.json
git show origin/张鹏飞:algorithm/B_revised/data_intake/README.md
git show origin/何宇轩:PROJECT_STATUS_AND_READINESS.md
git show origin/何宇轩:ai_training/contracts/README.md
git diff --check
git diff --exit-code
```

00 PDF 从 Git blob 只读读取并用 pypdf 提取全文，核验两个分支 blob 与 SHA-256 相同。没有检出/覆盖队友文件。当前原本就在“李青原”分支，所以无需 switch；没有创建新分支、重新 clone 或在 main 开发。

固定环境激活后实际执行：

```powershell
idf.py --version
cmake --version
ninja --version
python -m serial.tools.list_ports -v
idf.py -B build build
```

构建入口（同一项目，未另造工程）：

```powershell
powershell -NoProfile -ExecutionPolicy RemoteSigned -File "C:\Users\LQY\Documents\GitHub\ict-2026\firmware\node01\tools\Build.ps1"
```

主机测试入口：

```powershell
& ./firmware/node01/tools/Test-Host.ps1 -Compiler 'C:\msys64\ucrt64\bin\g++.exe'
```

此外使用 Python 读取 compile_commands.json、计算 SHA-256、比较分区二进制，并用 pyserial 在 DTR/RTS 预设 false 的条件下直接打开 COM7 检查可访问性。没有执行 flash、erase-flash、monitor 或改分区表。

sdkconfig 已正确设置 esp32s3，因此按要求未运行 `idf.py set-target esp32s3`，避免破坏配置。

## 失败过程与修复

1. 自动执行 `idf.py build` 在 CMake 编译器探测阶段失败：Xtensa 包装程序路径查询 Error code 5。没有绕过权限或伪造编译器检测结果。自动环境限制仍存在。
2. 用户普通终端运行脚本后进入实际交叉编译。ISR 的空参宏在严格 C++17 下失败；改为 `portYIELD_FROM_ISR(wake)`。
3. 精简组件集漏掉 esp_psram，首次 Kconfig 发出未知 SPIRAM 警告。显式补 main 的 esp_psram 依赖，从昨天已验证 sdkconfig 恢复，不猜新配置。
4. 修复后用户再次执行，真实编译/链接 PASS；最终日志无 warning/error，产物与配置已独立读取核验。

## 文件索引

- `build.log`、`build-result.json`：最终成功构建及退出码。Windows PowerShell 5 的 Tee 日志使用 UTF-16 LE BOM。
- `environment.log`：IDF/CMake/Ninja 与 IDF_PATH。
- `build-sandbox-failed.log`、`build-sandbox-result.json`：保留自动账号环境失败。
- `build-first-source-failed.log`、`build-first-source-result.json`：保留首次实际源码构建失败；旧脚本受 PowerShell stderr 行为影响 exit_code 为空，但失败原因和原始日志完整可追溯。
- `artifact-verification.json`：C++17、分区一致性、最终日志检查、BIN/ELF/config 哈希。
- `hardware-result.json`：本次串口检查事实与 NOT_RUN，不能套用昨天 hardware PASS。
- `host-test.log`：主机端 TEST_ONLY 软件测试通过。

## 状态矩阵

| 项目 | 状态 | 完成范围 / 限制 |
|---|---|---|
| Framework | BUILD_PASS；IMPLEMENTED_NOT_HARDWARE_VERIFIED | CMake/C++17/component/启动框架已编译链接 |
| Board definitions | CONFIRMED；BUILD_PASS；IMPLEMENTED_NOT_HARDWARE_VERIFIED | 与 00 对齐，唯一引脚/总线定义；外部电气未实测 |
| FreeRTOS runtime | BUILD_PASS；IMPLEMENTED_NOT_HARDWARE_VERIFIED | 5 个启用任务 + 3 个禁用任务、同步/诊断；未取得实板调度日志 |
| ICM driver | NOT_STARTED；TBD_HARDWARE_TEST | 只有接口与 ISR 通知位置，没有寄存器驱动 |
| ADS1115 | NOT_STARTED；TBD_HARDWARE_TEST | 只有拆分转换接口，PGA 未定 |
| Soil | TODO_CALIBRATION；NOT_STARTED | 原始码/validity 结构，无采集或标定 |
| MicroSD | NOT_STARTED；TBD_HARDWARE_TEST | mount/storage 边界，无读写/掉电恢复 |
| MQTT | NOT_STARTED | app_mqtt transport 接口，无连接、凭据或 Broker 地址 |
| LoRa | TBD_HARDWARE_TEST；NOT_STARTED | TBD-11 接口，无 E220 模式控制/正式字节布局 |
| Risk algorithm | TODO_CALIBRATION；NOT_STARTED（正式接入） | Runtime BUILD_PASS；未加载任何 B 演示阈值，输出 null |
| Alarm hardware | TBD_HARDWARE_TEST | 软件消费边界 BUILD_PASS；高阻，未驱动负载 |
| Atlas integration | NOT_STARTED | 无真实端边通信 |

CONFIRMED 表示已核对契约，不是实测 PASS。下一步为明确 Mock 的 Priority 2 三人接口预联调，以及新框架裸板启动/资源压测；真实硬件接入顺序见 firmware README。
