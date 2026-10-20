# 2026-10-20 队友进度交接：平台与 TinyQuake / ESP32 实验

本次同步以 GitHub `main` 的 `0093f57` 为基础，分支 `codex/tinyquake-esp32-handoff`。保留已合入的 NODE-01 固件框架、土壤/运动公开数据研究模型和平台细节修复。其他开发分支不会因此自动合并；正式共享契约仍以 `docs/00_TEAM_SHARED_CONTRACT.pdf` 为准。

## 现在完成到哪里

| 模块 | 已完成、可交接内容 | 仍未完成 |
| --- | --- | --- |
| 本地平台 | FastAPI / SQLite、可配置 MQTT、图像上传与 OpenCV 基线、告警与历史 API、Vue 后端页面 | 真实 Atlas、云端、现场闭环与正式灾害效果验证 |
| 现有 NODE-01 | 最新 main 已包含队友交付的运行时/接口框架，原记录为 Build/主机语义测试通过 | 按原负责人的验收记录，不能视为真实传感器与整板联调完成 |
| 土壤/运动研究 | main 已合入公开实测序列的双分支辅助预测与证据融合研究 | 自采数据适配、正式标签/阈值、生产部署；本轮未重跑这些研究实验 |
| TinyQuake 模型 | 官方 CNN17 未重训、未转换；完整可用参考集桌面推理和科学评估已完成 | 本项目 ICM 波形与连续现场背景上的有效性 |
| TinyQuake 固件 | 独立 ESP-IDF 实验工程，串口/MQTT 两种配置真实交叉编译通过，提供参考镜像 | 烧录/启动、板端参考一致性、arena、时延、真实 IMU 驱动与完整预处理 |
| TinyQuake → 平台 | 独立协议、MQTT 接收、SQLite 结果表、分页历史与实验页；USB 桥接工具 | 实际 ESP32 USB / Wi-Fi 到平台链路尚未运行 |

版本：平台后端 **0.3.0**，前端 **1.2.0**。TinyQuake 工程结论仍为 **EXPERIMENTAL**。正式 `model_version`、`calibration_version` 仍为 null；外部预训练模型的存在不等于本项目正式模型交付。

## 文件从哪里取

- **模型**：[model_17_16_32_32.tflite](../model_evaluation/tinyquake/model/model_17_16_32_32.tflite)，35760 B。输入 float32 `[1,80,3,1]`，40 Hz、2 秒、E/N/Z；输出 float32 `[1,3]`，顺序 P-wave / S-wave / Noise。完整预处理和模型身份见[评估报告](../model_evaluation/TINYQUAKE_EVALUATION.md)。
- **备用板参考镜像**：[tinyquake_reference_serial.bin](../../firmware/tinyquake_esp32s3/artifacts/tinyquake_reference_serial.bin)，437632 B，已合并 bootloader / 分区 / 应用，偏移 **0x0**。仅适用确认的 ESP32-S3-WROOM-1 N8R8 / 原生 USB 控制台。
- **实验工程**：[firmware/tinyquake_esp32s3](../../firmware/tinyquake_esp32s3/README.md)，与现有 [firmware/node01](../../firmware/node01/README.md) 独立。没有将 TinyQuake 自动塞入 NODE-01 采样或风险任务。
- **接入步骤和完整消息字段**：[TINYQUAKE_ESP32_GUIDE.md](../model_evaluation/TINYQUAKE_ESP32_GUIDE.md)。
- **板端接口**：[tinyquake_runner.h](../../firmware/tinyquake_esp32s3/main/tinyquake_runner.h)；**USB 桥**：[tinyquake_usb_bridge.py](../../scripts/tinyquake_usb_bridge.py)。
- **构建记录**：[BUILD_STATUS.json](../../firmware/tinyquake_esp32s3/artifacts/BUILD_STATUS.json)；**桌面结果**：[baseline_results.json](../model_evaluation/tinyquake/results/baseline_results.json)。

GitHub 下载二进制时使用文件页的 **Download raw file**，避免把网页 HTML 保存为 `.bin` / `.tflite`。`.tflite` 需要推理解释器，不能直接当固件刷入板卡。

## 队友如何拉取和启动

已有本仓库时，先保存自己的本地改动，再切换此分支查看；不要在未保存工作时执行清理命令。

```bash
git fetch origin
git switch --track origin/codex/tinyquake-esp32-handoff
# 已有同名本地分支时：git switch codex/tinyquake-esp32-handoff
./scripts/run-platform.sh
```

打开 `http://127.0.0.1:8000` → **TinyQuake 实验**。没有硬件数据时显示等待接入，不会自动生成模型分数。后端/前端安装与 Windows 手动启动方式按[后端说明](../../platform_backend/README.md)使用。

确认备用板并自行完成刷机、启动检查后，按[接入指南](../model_evaluation/TINYQUAKE_ESP32_GUIDE.md)启动 USB 桥；示例使用 macOS/Linux 的虚拟环境路径，Windows 使用同一环境的 `Scripts/python.exe`。默认桥仅监听本机 `127.0.0.1:18884`，读到实际串口结果后才配置 MQTT 订阅并转发。

以下链路是下一步的实板验收目标，**尚未实际执行**：

```text
备用 N8R8 运行官方参考向量 → USB 串口 → 本机桥 / MQTT
→ FastAPI 校验 → SQLite → TinyQuake 实验页
```

默认固件只跑三个官方参考窗口，没有 ICM 驱动。输出的 REFERENCE / MOCK / TEST_ONLY 是参考推理身份；即使在板上执行，也不能称为真实传感器测量。

## 给嵌入式、算法与平台队友的下一步

1. **嵌入式先验收备用板**：核对型号/USB 口；记录真实 boot、三个参考输出、`arena_used` 和 `Invoke` 耗时。编译环境固定为 ESP-IDF 5.5.1、ESP-TFLite-Micro 1.4.1、ESP-NN 1.4.1；队友现有 NODE-01 的 IDF 配置和 SDK 不在本轮更改。
2. **嵌入式交付连续波形**：两枚 ICM 各自的三轴原始值、单位/量程/ODR、时间戳、FIFO/丢样/饱和状态、安装坐标和实际校准记录。低频 tilt / RMS 遥测不能恢复原始模型输入。不能凭空补标定值。
3. **算法与嵌入式共同确认适配**：真实物理单位、方向、去趋势/滤波、抗混叠、40 Hz 重采样和官方末段归一化；每枚 IMU 独立 80×3 窗口，不拼成六通道。`tinyquake_normalize_40hz()` 仅覆盖最终归一化段。
4. **平台联调实验结果**：使用独立 `zhifang.tinyquake.result.v1` 和 `zhifang/experimental/tinyquake/v1/{site}/{device}/{sensor}/result`；连接器选 `tinyquake_v1`。传感器输入需 SENSOR、top/toe、真实窗口 uptime；未知校准保持 null。无效窗 probabilities=null。
5. **完成信号与系统验收后再讨论接入正式工程**：单个推理任务独占解释器，双 IMU 串行排队，不阻塞 ISR / 原采样 / SD / B 风险任务；记录并发丢样和最坏时延。正式告警用途须另行评估。

## 实际验证与必要边界

本次同步最新 main 后，实际重新运行：

```bash
PYTHONPATH=platform_backend/src platform_backend/.venv/bin/python -m pytest platform_backend/tests -q
cd apps/geohazard-demo
npm run build
npm run test:tinyquake
npm run test:platform:regressions
```

结果：**139 项后端测试通过**（含 22 项新增 TinyQuake 测试及本机实际 MQTT Broker 收发）；TinyQuake 6 项浏览器检查、原平台 7 项浏览器回归、2 项 HTTP 检查、TypeScript 和生产构建通过。测试用临时数据库，没有往用户运行库植入参考分数。此次同步未重新编译未改动的实验固件；随附源代码与两种编译通过的记录来自前一轮已执行构建。

桌面参考基线为 17427 个有效官方参考窗口，argmax 93.8199%。这不是本地 MEMS 的准确率，不代表事件误报率、滑坡预警或地震预测能力。

**尚未执行**：ESP32 刷写/启动、板端输出对齐、实际 arena/时延、双 ICM 输入、硬件 USB/Wi-Fi 到平台、Atlas/云端与现场验证。131072 B 是初始 arena 配置容量，实测需求未知。

所有 TinyQuake 记录均为 **TEST_ONLY / risk_eligible=false**；参考只允许 MOCK，实采可标 REAL 但仍属实验。模型结果使用单独表，不写入正式遥测和告警；P/S/Noise softmax 不能乘 100 充当风险评分。本次没有重训模型，没有修改现有生产固件，也没有更改正式科学契约。
