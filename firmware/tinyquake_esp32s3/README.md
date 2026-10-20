# TinyQuake ESP32-S3 独立实验工程

目标：ESP32-S3-WROOM-1 N8R8（8 MB Flash / 8 MB Octal PSRAM），ESP-IDF 5.5.1。

已完成串口版与 MQTT 启用版的真实交叉编译。**没有刷机或板端运行；arena 实际占用、板端参考输出与时延均未测量。** 构建详情见 [BUILD_STATUS.json](artifacts/BUILD_STATUS.json)。

默认固件只运行三个官方预处理参考窗口，串口每两秒输出一条 `TINYQUAKE_RESULT {...}`。它没有 ICM 驱动，不读取现场传感器，输出必须标记 REFERENCE / MOCK / TEST_ONLY。

可烧录合并镜像：[tinyquake_reference_serial.bin](artifacts/tinyquake_reference_serial.bin)，包括 bootloader、分区表与应用，烧录偏移 **0x0**。只用于确认型号的备用板；它会替换板上应用，不能用于队友正在运行生产固件的板卡。预编译版控制台使用 ESP32-S3 原生 USB Serial/JTAG；DevKit 请使用原生 USB 接口，只有 UART 桥接的板需在 menuconfig 改控制台后重新编译。

从项目根目录建立了 ESP-IDF 环境后可自行构建：

```bash
idf.py -C firmware/tinyquake_esp32s3 set-target esp32s3
idf.py -C firmware/tinyquake_esp32s3 build
# 接好备用板并核对端口后再自行运行（本次未运行）：
idf.py -C firmware/tinyquake_esp32s3 -p /dev/cu.usbmodemYOUR_PORT flash monitor
```

完整的烧录、USB 桥接与平台查看步骤见 [平台接入指南](../../docs/model_evaluation/TINYQUAKE_ESP32_GUIDE.md)。

## 给负责现有固件的队友

不要直接替换生产工程。先在备用板运行本工程，确认启动日志的参考向量检查、实际 arena 与推理耗时；CPU 上的 1e-4 绝对误差检查只是工程一致性检查，不是灾害判定阈值。

本工程可复用的接口：

- `tinyquake_init()`：一次初始化；失败则不启用推理。
- `tinyquake_infer_preprocessed(input_enz[240], scores[3], &invoke_us)`：单个推理任务独占解释器。输入必须是 80×E/N/Z 交织的 float32、40 Hz、2 秒、**已完成预处理**的窗口。
- `tinyquake_normalize_40hz()`：仅实现官方最终归一化/int16/float32步骤，含静默/非正最大值拒识；**不负责 ICM 寄存器读取、校准、坐标、去趋势、高通或重采样，不是完整传感器适配器**。

真实采样适配需要你们现有 ICM-42688-P 驱动的原始三轴数据、实际时间戳、ODR、安装坐标、量程和校准信息；不能用 v2 的 tilt/RMS 快照插值成输入。两路 IMU 分别形成窗口并串行调用，不拼成六通道。现有 B 风险算法和采样/SD任务保持独立。

上报使用独立 `zhifang.tinyquake.result.v1`，Topic：

```
zhifang/experimental/tinyquake/v1/{site_id}/{device_id}/{sensor_id}/result
```

参考数据 `input_source=REFERENCE`，传感器数据才用 `SENSOR`。平台连接器为参考数据选 MOCK，真实采集可选 REAL，但全部仍是 TEST_ONLY，不参与 sensor_score/告警。类顺序固定 P-wave / S-wave / Noise，禁止 softmax×100 写入正式风险分数。未知校准保持 null，无效窗 probabilities=null。协议字段见平台指南。

可选 Wi-Fi/MQTT：`idf.py -C firmware/tinyquake_esp32s3 menuconfig` 中打开 TinyQuake MQTT，填写 2.4GHz Wi-Fi、局域网 Broker URI 和凭据，再重新 build。该路径也仍运行参考窗口。当前 MQTT 配置供受控局域网实验；生产 TLS/证书、设备认证、掉线队列与正式可靠回执需单独设计。本次编译验证用空白网络配置，没有保存真实 Wi-Fi 密码。

131072 字节是可调 arena 初始容量，不是测量需求。arena 在内部 RAM 分配；初始化失败就停止推理。PSRAM 配置不等于板端已经验证。

模型采用官方 CNN17 原始字节，根 MIT 许可证副本随附；参考数据来源 STEAD 的归属与派生处理见 THIRD_PARTY_NOTICES.md 和主项目评估报告。本目录没有重新训练或转换模型。
