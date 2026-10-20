# TinyQuake：从 ESP32 到智哨平台的实验接入

日期：2026-10-20。适用项目：本仓库。以下命令从仓库根目录执行；本机 Desktop 副本与 GitHub 检出路径可以不同。

## 现在已有的文件

- [原始 CNN17 模型](tinyquake/model/model_17_16_32_32.tflite)：35,760 字节的 `.tflite`，用于解释器，不能单独当 ESP32 固件烧录。
- [可烧录的 USB 参考实验镜像](../../firmware/tinyquake_esp32s3/artifacts/tinyquake_reference_serial.bin)：包含引导程序、分区表、模型和三个官方参考输入，烧录偏移 **0x0**。
- [独立 ESP-IDF 实验工程与队友接入说明](../../firmware/tinyquake_esp32s3/README.md)：默认串口输出；可选 Wi-Fi/MQTT。
- [USB 桥接工具](../../scripts/tinyquake_usb_bridge.py)：读取板端真实串口输出，转发到本机 MQTT，再由后端保存。
- 平台新增 **TinyQuake 实验** 页面，可显示数据流、P/S/Noise 分数、设备上报推理耗时、质量与接收历史。

**已验证的是构建与电脑端软件链路，还没有实际烧录或运行 ESP32。** 当前未检测到 ESP32 USB 串口。本轮独立实验未修改正式固件。同步时最新 main 已包含 [NODE-01 固件框架](../../firmware/node01/README.md)，其状态按原负责人的记录保留，不代表 TinyQuake 已接入该框架。首先使用一块确认型号的备用板运行参考实验，之后再让队友接真实双 IMU。

## 第一步：把参考实验固件放进备用 ESP32-S3

预编译镜像对应 **ESP32-S3-WROOM-1 N8R8：8 MB Flash、8 MB Octal PSRAM**，原生 USB Serial/JTAG 控制台。DevKit 有 USB / UART 两个接口时，使用原生 USB 接口看输出；只接 UART 桥的板需要在 menuconfig 改控制台并重新编译。

烧录会替换板上应用。以下命令只用于确认的备用板，不要刷队友正在使用的生产节点。**本次没有执行下面的烧录命令。**

先在 ESP-IDF **5.5.x** 终端中操作；本次实际构建用 5.5.1。已有 SDK 的队友启用自己的 `export.sh`（Windows 使用自己的 ESP-IDF 终端），不需要复制本机 SDK 或改动 NODE-01 环境。预编译镜像无需重新编译，但烧录终端仍需有 `esptool` / `pyserial`：

```bash
idf.py --version
# 进入你实际克隆的 ict-2026 仓库根目录后继续
```

用数据 USB 线接板，确认出现实际端口后，将 `YOUR_PORT` 替换为端口名：

```bash
python -m serial.tools.list_ports
python -m esptool --chip esp32s3 --port /dev/cu.usbmodemYOUR_PORT \
  --baud 460800 write_flash --flash_mode dio --flash_size 8MB --flash_freq 80m \
  0x0 firmware/tinyquake_esp32s3/artifacts/tinyquake_reference_serial.bin
```

不要把普通 `.tflite` 填入上面的烧录命令。USB 桥和串口监视器不能同时占用同一端口。

默认镜像启动后先用三个参考输入核对模型输出；绝对误差超过工程检查容差 `1e-4` 时停止发布。正常路径才输出 `Reference parity PASS`、实际 `arena_used`，以及每两秒一条 `TINYQUAKE_RESULT {...}`。这些日志尚未在本轮看到，必须在实板上确认；预留 arena=131072 B 只是配置容量，不是测量结果。

## 第二步：启动智哨平台

在另外的终端执行：

```bash
./scripts/run-platform.sh
```

打开 `http://127.0.0.1:8000`。左侧进入 **TinyQuake 实验**，此时没有板端数据时显示等待接入。普通传感器总览与 TinyQuake 是两个独立通道。

## 第三步：把 USB 结果转入平台

首次安装桥接工具的依赖，随后运行：

```bash
platform_backend/.venv/bin/python -m pip install -r scripts/tinyquake-usb-requirements.txt
platform_backend/.venv/bin/python scripts/tinyquake_usb_bridge.py \
  --port /dev/cu.usbmodemYOUR_PORT
```

桥接工具默认仅在 `127.0.0.1:18884` 启动一个本机实验 Broker。收到实际 `TINYQUAKE_RESULT` 后，会在当前本机平台新增或更新它自己的 TinyQuake MQTT 连接配置；不会生成或随机模拟模型分数。默认来源是 **MOCK**，因此参考固件可看到：

```text
TQ-LAB / ESP32-TQ-01 / reference / MOCK
```

如果平台设置了 API Token，请先在桥接终端设置同名 `GEOHAZARD_API_TOKEN`；密钥通过请求头发送，不能填在 URL 中。关闭桥后历史仍保留，连接器会断开；可在“配置与接入”中停用该连接器。18884 端口被占用时，换 `--broker-port 18885`，工具会使用对应的连接配置。

这条链路为：

```text
ESP32-S3 实际执行 CNN17（官方参考输入）
  → 原生 USB 串口
  → 电脑桥接工具 / 本机 MQTT
  → FastAPI 校验并保存 SQLite
  → TinyQuake 实验页面
```

页面展示的“参考波形 · 非实采”是有意保留的事实边界：它能验证板端推理到页面的连接，不能证明 ICM 数据适配完成。接收超过 30 秒或后端失联后不显示实时分数。新鲜度只按后端接收时间判断，不是已校准采集时间证明。

## 可选：由 ESP32 直接通过 Wi-Fi 上报

在实验工程 menuconfig 打开 TinyQuake MQTT，填写 Wi-Fi、局域网 Broker URI 和凭据，再重新编译。随后平台 MQTT 连接器选择：

| 字段 | 参考实验配置 |
| --- | --- |
| 消息格式 | TinyQuake 实验结果 |
| 来源 | MOCK |
| Broker | 板卡可访问的局域网 Broker；ESP32 上不能用电脑的 127.0.0.1 |
| 站点 | TQ-LAB（与固件一致） |
| Topic | `zhifang/experimental/tinyquake/v1/TQ-LAB/+/+/result` |
| 启用 | 勾选持续订阅，测试应收到真实 CONNACK/SUBACK |

电脑原来的 localhost 演示 Broker 和 USB 桥 Broker 都只监听 loopback，不能直接供 Wi-Fi 板卡访问。直接 Wi-Fi 路径需另外配置有凭据、受控局域网可达的 Broker。本次只验证该配置能够编译，没有测试板端 Wi-Fi/凭据/收发。

## 队友接真实 ICM-42688-P 时需要什么

当前新增固件没有 ICM 驱动；队友无需丢弃现有工程，可以在备用板完成参考检查后复用 `tinyquake_runner`。需要提供：

1. 两路原始三轴加速度与真实时间戳；量程、单位、ODR、FIFO/缺样状态和安装坐标。低频 tilt/RMS 快照不能替代波形。
2. 校准和方向转换、去趋势/高通、抗混叠及 100/200→40 Hz 重采样。每路 2 秒窗口独立处理，最终按 E/N/Z 交织写入 80×3 float32。
3. 完成官方最终归一化/int16/float32流程；本工程的 `tinyquake_normalize_40hz()` 只覆盖此末段，不是完整传感器适配。
4. 通过单个推理任务串行处理 top/toe。不要在采样 ISR 内调用网络，不堵塞现有采样、SD 和 B 风险任务。
5. 上报 `input_source=SENSOR`、实际 `sensor_id=top/toe`、真实窗口 uptime、`frame_id` 与 `calibration_version`。未交付的元数据保持 null；无效窗 quality_valid=false、probabilities=null，不用零或 Noise 冒充有效观测。

传感器流可选 REAL，**但 TinyQuake 输出仍是 TEST_ONLY、尚未现场验证，不能直接形成生产告警**。P/S/Noise 是窗口类别，softmax×100 不能写入 `sensor_score`；正式 v2 协议、既有风险规则与告警表保持独立。

### 独立结果协议

Schema：`zhifang.tinyquake.result.v1`。Topic 身份必须和消息内站点、设备、传感器一致；retained 回放不作为新观测接收。

| 字段 | 含义 |
| --- | --- |
| schema / model_sha256 | 固定 result.v1 / 已评估 CNN17 SHA-256 |
| site_id / device_id / sensor_id | ASCII 身份；参考默认 reference，真实两路 top/toe |
| boot_id / seq | 每次启动身份和单调序号；重传保持原消息身份与内容 |
| input_source | REFERENCE 或 SENSOR；参考只能进入 MOCK 连接器 |
| sample_rate_hz / sample_count | 固定 40 / 80；每样点含三分量 |
| probabilities | `[P-wave,S-wave,Noise]` 三个有限分数；无效窗为 null |
| inference_us | 设备实际 Invoke 耗时，微秒；不含采样等待或前处理 |
| quality_valid / quality_reason | 窗口是否可用与可读原因标识；不是灾害标定状态 |
| reference_index | 参考窗 NPZ 行号 3/0/2；SENSOR 为 null |
| window_start_uptime_ms / window_end_uptime_ms | SENSOR 的实际采样窗时钟；参考为 null，不伪造采集时间 |
| frame_id / calibration_version | SENSOR 的方向与校准身份；未知为 null，参考为 null |
| preprocessing_id | 实际预处理版本，参考为 tinyquake.reference.preprocessed.v1 |

后端 `GET /api/v1/tinyquake/streams` 列出实验流，`GET /api/v1/tinyquake/results` 查询历史和游标分页。相同身份重复内容去重、不同内容报冲突。HTTP 测试入口仅接收 MOCK- 参考结果，实际硬件走 MQTT。

## 本轮验证状态

| 项目 | 结果 |
| --- | --- |
| ESP-IDF 5.5.1 / ESP-TFLite-Micro 1.4.1 / ESP-NN 1.4.1 | 真实解析依赖并交叉编译通过，锁文件随实验工程提供 |
| 默认串口固件 | 编译通过；应用 372096 B，合并镜像 437632 B，包含原始模型字节及 C 布局参考输入 |
| MQTT 启用配置 | 编译通过；应用 1042032 B；空白网络配置，无实际凭据 |
| 新增后端、桥接协议与实际本机 MQTT | 同步最新 main 后，22 项新增测试与 117 项既有后端测试合计 139 项通过 |
| 页面 | TinyQuake 六项浏览器检查通过；原平台七项浏览器回归及两项 HTTP 检查通过；TypeScript / 生产构建通过 |
| 本轮测试数据 | 使用临时数据库与 Broker；没有在用户数据库植入演示模型输出 |
| ESP32 flash / boot / reference parity | **NOT_RUN** |
| 实测 arena / 板端时延 / 真实 ICM 与并发任务 | **NOT_RUN** |

构建成功意味着已生成可供备用板验证的镜像，不等于已在硬件执行。原始模型科学评估见 [TINYQUAKE_EVALUATION.md](TINYQUAKE_EVALUATION.md)。
