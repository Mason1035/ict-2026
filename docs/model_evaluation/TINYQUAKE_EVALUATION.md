# TinyQuake 在 ESP32-S3 双 IMU 平台上的可行性评估

> **当前状态（2026-10-20）**：独立 ESP-IDF 5.5.1 / ESP-TFLite-Micro 1.4.1 参考固件的串口版、MQTT 启用版均已编译通过，并新增平台实验通道，见 [ESP32 指南](TINYQUAKE_ESP32_GUIDE.md) 与 [队友进度交接](../team_handoffs/TINYQUAKE_PROGRESS_2026-10-20.md)。真实刷写、板端输出、arena 和时延仍 NOT_RUN。
>
> **以下是首次模型评估快照**：其中“未编译”“平台未修改”“没有推送”仅指首次评估时点。后续编译与平台改动以上方链接为准；桌面基线数据和 EXPERIMENTAL 科学结论保持有效。

评估日期：2026-10-20（Asia/Shanghai）
首次评估主项目：本机 `~/Desktop/ict-2026-main` 副本
目标：ESP32-S3-WROOM-1 N8R8，8 MB Flash / 8 MB PSRAM，双 ICM-42688-P，ESP-IDF 5.5.x，ESP-TFLite-Micro。

## 工程决定

**推荐：EXPERIMENTAL（仅限隔离实验）。**

Phase 1 模型检查与 Phase 2 桌面推理已完成。选定的官方浮点 CNN 可以在桌面 TFLite 加载，17,427 个有效官方参考窗口的三分类 argmax 准确率为 **93.8199%**。固定版本 ESP-TFLite-Micro 中存在其所需的五类 float32 算子实现，未发现明确的静态算子阻断。

目前不能接受为生产检测器：没有 ESP32-S3 编译、刷写、`AllocateTensors()`、板端输出/延迟/arena 实测，也没有本项目双 ICM 的真实连续波形与现场标签。公开地震台站数据与 MEMS 坡面安装数据存在频响、噪声、方向和机械耦合差异，**不能直接把模型接到现有遥测 JSON 上并沿用上述准确率**。

TinyQuake 分类已观测窗口中的 P 波、S 波和噪声，不能据此声称地震预测、滑坡预测或正式地灾风险评估。本轮没有训练、重训、重新量化或修改任何生产固件。

| 阶段 | 本轮完成情况 |
| --- | --- |
| Phase 1 | 官方仓库克隆、固定提交、源码/模型/许可检查、模型哈希完成 |
| Phase 2 | 新建隔离 Python 环境，实际运行完整可用参考测试集并保存逐窗结果 |
| Phase 3 | 官方组件源码及 IDF 版本静态检查完成；固件构建、arena 和板端时延 **NOT_RUN** |
| Phase 4 | 已与实际主项目的规范、接口、配置占位和候选算法比较；真实采样适配 **NOT_RUN** |
| Phase 5 | 条件式工程决定与后续验收要求完成；部署状态保持 **NOT_DEPLOYED** |

## 1. 精确模型、来源与选择理由

上游仓库：<https://github.com/tclements/TinyQuake>。本轮实际克隆并固定提交：

```text
fce74a7027129e721dafe56a5521d1d57b9835f9
```

所选文件：`CNN/models/model_17_16_32_32.tflite`，**35,760 字节**。没有转换、裁剪或更换权重。

```text
SHA-256:
0e1eb00a920ae3daaec7cf142ef8a54373fe1b93b472350e7048b8ae0c1ff1f1
```

[固定提交模型页面](https://github.com/tclements/TinyQuake/blob/fce74a7027129e721dafe56a5521d1d57b9835f9/CNN/models/model_17_16_32_32.tflite) · [直接下载原始 TFLite](https://raw.githubusercontent.com/tclements/TinyQuake/fce74a7027129e721dafe56a5521d1d57b9835f9/CNN/models/model_17_16_32_32.tflite)。本地相同字节副本：[model_17_16_32_32.tflite](tinyquake/model/model_17_16_32_32.tflite)。

仓库含 CNN 20 个、DNN 10 个、RNN 11 个 TFLite 文件。选择 CNN17 的理由是[官方测试脚本直接使用它](https://github.com/tclements/TinyQuake/blob/fce74a7027129e721dafe56a5521d1d57b9835f9/src/test.py#L65-L77)，模型约 35 KB、只有常见前馈算子，可先复现已有明确测试路径。**模型在本轮测试前固定，没有根据本轮测试准确率挑选“最佳模型”。** 不声称它在精度、延迟或功耗上最优。

根许可证为 [MIT / Tim Clements 2022](https://github.com/tclements/TinyQuake/blob/fce74a7027129e721dafe56a5521d1d57b9835f9/LICENSE)，副本见 [TinyQuake-LICENSE.txt](tinyquake/TinyQuake-LICENSE.txt)。根许可证没有单列权重专用授权清单；代码、模型和数据的上游归属应分别保留。STEAD 数据源是 CC-BY-4.0，TinyQuake 预处理注明借用了 EQTransformer 函数，Arduino sketch 自带 TensorFlow Apache-2.0 头；具体归属与修改说明见 [THIRD_PARTY_NOTICES.md](tinyquake/THIRD_PARTY_NOTICES.md)。

## 2. 输入、输出、结构和量化契约

以下形状、类型、算子与常量信息来自本轮实际解析的 FlatBuffer 和桌面解释器，完整字段见 [baseline_results.json](tinyquake/results/baseline_results.json)。

| 项目 | 实际契约 |
| --- | --- |
| 输入张量 | `serving_default_input_28:0`，index 0 |
| 实际分配形状 | `[1,80,3,1]`，float32；shape signature `[-1,80,3,1]`，本次 batch=1 |
| 维度含义 | batch × 时间 × E/N/Z 三分量 × 单通道；NHWC / C 连续排列 |
| 每窗 | 三分量各 80 点，40 Hz，覆盖 2 秒采样区间；最后一点相对首点为 1.975 秒 |
| 输入字节 | `80×3×4=960 B`，一个 IMU 的一个预处理窗 |
| 输出张量 | `StatefulPartitionedCall:0`，index 21，`[1,3]`，float32，12 B |
| 类别顺序 | `0=P-wave`，`1=S-wave`，`2=Noise` |
| 输出解释 | 三分类 softmax 分数；不是经过本项目校准的危险概率 |
| 模型量化 | **未做整数量化**；输入、输出和浮点权重均无量化 scales/zero_points |
| 量化字段 | I/O `quantization=(0.0,0)`、`scales=[]`、`zero_points=[]`；不能套用整数反量化公式 |
| Schema | TFLite schema version 3，无自定义算子 |

类别语义来自[训练标签赋值](https://github.com/tclements/TinyQuake/blob/fce74a7027129e721dafe56a5521d1d57b9835f9/src/dataprep.py#L412-L430)和[类别名定义](https://github.com/tclements/TinyQuake/blob/fce74a7027129e721dafe56a5521d1d57b9835f9/src/train.py#L64-L65)，并非从张量位置猜测。

推理图为 7,875 个浮点参数、10 个节点：

| 节点 | 类型 / 版本 | 输出形状（省略 batch） | 关键参数 |
| --- | --- | --- | --- |
| 0 | CONV_2D v1 | 78×3×16 | 核 3×1，步长 1×1，VALID，dilation=1，融合 ReLU |
| 1 | MAX_POOL_2D v1 | 26×3×16 | 3×1，步长 3×1，VALID |
| 2 | CONV_2D v1 | 24×3×32 | 同类配置，融合 ReLU |
| 3 | MAX_POOL_2D v1 | 8×3×32 | 同类池化 |
| 4 | CONV_2D v1 | 6×3×32 | 同类配置，融合 ReLU |
| 5 | MAX_POOL_2D v1 | 2×3×32 | 同类池化 |
| 6 | RESHAPE v1 | 192 | 常量 int32 shape；不是运行时可任意改变的输入长度 |
| 7 | FULLY_CONNECTED v1 | 16 | 融合 ReLU |
| 8 | FULLY_CONNECTED v1 | 3 | 线性 logits |
| 9 | SOFTMAX v1 | 3 | beta=1 |

训练时还使用 Dropout，转换后的推理图没有 Dropout 节点。卷积核宽度为 1，不能把它描述成每层卷积都已经融合三轴。结构来源：[train.py](https://github.com/tclements/TinyQuake/blob/fce74a7027129e721dafe56a5521d1d57b9835f9/src/train.py#L26-L38)。

## 3. 所需预处理及易错点

### 3.1 原始数据到参考窗

官方生成流程读取 STEAD 三分量台站记录，以 E/N/Z 顺序、原采样 100 Hz 构造 ObsPy Stream。先在线性去趋势和 taper 后做 **0.5 Hz 高通**，再下载站点仪器响应并执行 `remove_response(output='ACC', taper=False)`；其输出单位是 m/s²。随后围绕 P/S 到时截取 2 秒窗，使用 SciPy FFT `signal.resample` 变为 40 Hz / 80 点。噪声窗来自噪声记录。[TinyQuake 数据流程](https://github.com/tclements/TinyQuake/blob/fce74a7027129e721dafe56a5521d1d57b9835f9/src/dataprep.py#L258-L374)；[STEAD 原始 counts、ENZ 及物理单位说明](https://github.com/smousavi05/STEAD#how-to-convert-raw-waveforms-into-acceleration-velocity-or-displacement)；[ObsPy ACC 单位](https://docs.obspy.org/packages/autogen/obspy.core.trace.Trace.remove_response.html)。

本轮使用的是上游已经提供的 `test.npz`，**没有重新下载完整 STEAD HDF5、响应元数据或重新生成这些原始窗**。NPZ 只有 Xtest/Ytest，没有逐窗 trace ID、事件/台站身份、采样率和单位元数据；其语义依赖源码说明，无法反向逐样本验证全部原始处理。源码在 `augmentation=False` 时仍可能进行到时位置抖动，因此也不能声称从原始数据重新生成一定得到同一 NPZ。

### 3.2 已提供的 NPZ 到网络输入

本轮逐项复现 [test.py:56–62](https://github.com/tclements/TinyQuake/blob/fce74a7027129e721dafe56a5521d1d57b9835f9/src/test.py#L56-L62)：

1. 对每窗全部时间/三轴取 maxabs，严格保留 `>1e-8` 且 `<2×9.81` 的窗。
2. 除以每窗 `np.max(data,axis=(1,2))`；分母为零时替为 1。**这里是普通最大值，不是绝对值最大值，也不是每轴独立归一化。**
3. 按每窗 maxabs 将数值缩放到 int16 最大值 32767，然后转 `np.int16`。
4. 转回 float32，再做一次步骤 2 的普通最大值归一化。
5. 保留 E/N/Z 顺序，以 `[1,80,3,1]` 的 C 连续布局交织写入。

`dataprep.quantize()` 的注释写 `[-127,127]`，但默认类型实际为 **int16**；这与模型 int8 量化是两回事。`normalize()` 注释声称 `[-1,1]`，实际不保证负侧边界；本轮网络输入整体范围实测 **[-18.7884178, 1.0]**。不能自行裁到 `[-1,1]`、改成 maxabs 或删掉临时整数步骤，再引用原基线成绩。[具体实现](https://github.com/tclements/TinyQuake/blob/fce74a7027129e721dafe56a5521d1d57b9835f9/src/dataprep.py#L19-L31)、[normalize](https://github.com/tclements/TinyQuake/blob/fce74a7027129e721dafe56a5521d1d57b9835f9/src/dataprep.py#L137-L144)。

实际传感器适配还必须处理 NaN、无穷、无效窗、非正/极小归一化分母和饱和；异常窗应拒识并报告质量，不能补出“可信分数”。这些现场策略尚未校准，不能据公开窗的少量边界处理认定已完成适配。

## 4. 桌面实际推理结果

### 环境与测试方法

新建独立 `.venv`，实际运行环境为 macOS ARM64、Python **3.11.9**、TensorFlow **2.16.2**、NumPy **1.26.4**、SciPy **1.13.1**、scikit-learn **1.5.2**。完整环境见 [requirements-lock.txt](tinyquake/requirements-lock.txt)。上游环境是 Python3.10/TF2.11 的 Windows conda 导出，本轮没有照搬为 MCU 依赖。

推理使用 `tf.lite.Interpreter`、单线程、`BUILTIN_WITHOUT_DEFAULT_DELEGATES`，默认 delegates 关闭；预热 50 次后逐窗 `set_tensor → invoke → get_tensor`。不训练、不执行上游训练入口，也不运行会在测试集上挑阈值的完整上游绘图脚本。预处理从固定提交的四个纯 NumPy 函数 AST 提取，未导入会拉起 ObsPy/训练依赖的整个 `dataprep` 模块。

参考数据：[固定版本 data/test.npz](https://github.com/tclements/TinyQuake/blob/fce74a7027129e721dafe56a5521d1d57b9835f9/data/test.npz)。

```text
test.npz SHA-256:
34abb38e09818421a07e4fed307d77386d54b082453d631b13e1212f27976ebd
```

| 数据环节 | P-wave | S-wave | Noise | 总数 |
| --- | ---: | ---: | ---: | ---: |
| 原始 NPZ | 5,312 | 5,312 | 7,092 | 17,716 |
| 按官方幅度条件保留 | 5,312 | 5,312 | 6,803 | **17,427** |

本次 289 个 Noise 窗因幅度过小被排除；大幅度筛选没有再排除窗口。所有原始值、标签和输出经有限性检查，标签为有效三类 one-hot。**没有用随机输入生成分类准确率。**

### 默认 argmax 基线

行是真实类别，列是预测类别：

| 真实 \ 预测 | P-wave | S-wave | Noise |
| --- | ---: | ---: | ---: |
| P-wave | 5,087 | 212 | 13 |
| S-wave | 174 | 4,976 | 162 |
| Noise | 34 | 482 | 6,287 |

正确分类 `16,350 / 17,427`，accuracy **93.8199%**，macro F1 **0.937765**。

| 类别 | Precision | Recall | F1 |
| --- | ---: | ---: | ---: |
| P-wave | 0.960718 | 0.957643 | 0.959178 |
| S-wave | 0.877601 | 0.936747 | 0.906210 |
| Noise | 0.972919 | 0.924151 | 0.947908 |

6,803 个保留 Noise 窗中有 **516 个被判为 P/S（7.5849%）**。这只是该筛选测试集的噪声窗误分类比例，不能换算成现场每小时误报数，也不代表连续事件检测误报率。

另固定 `threshold=0.8` 仅作判决行为比较，规则完全跟随上游：P/S 分数低于阈值置零，Noise 不变，再取 argmax。没有遍历阈值并根据本次标签选最优。其 accuracy **91.3410%**；P precision/recall **0.991827/0.891002**，S **0.953987/0.862575**；Noise 被判 P/S 为 `200/6803=2.9399%`。更高阈值会减少一些噪声窗误判，同时漏掉更多相位窗；**0.8 不是已标定部署阈值**。

前三个类别示例均取该类在原 NPZ 中第一个有效窗，选择不依赖预测是否正确：

| 原 NPZ index | 真实类 | 输出 `[P,S,Noise]`（约值） | argmax |
| --- | --- | --- | --- |
| 3 | P-wave | `[0.99934906,0.00065099,0.000000006]` | P-wave |
| 0 | S-wave | `[0.00007022,0.99799722,0.00193254]` | S-wave |
| 2 | Noise | `[0.00000408,0.09720625,0.90278971]` | Noise |

完整逐窗分数见 [predictions.csv](tinyquake/results/predictions.csv)，用于未来设备数值对齐的三个输入/输出见 [golden_vectors.npz](tinyquake/results/golden_vectors.npz)。这些都是公开参考窗的派生结果，不是本项目真实采集。

## 5. ESP32-S3 / ESP-TFLite-Micro 兼容性

本轮另克隆并静态检查官方 `espressif/esp-tflite-micro`，固定提交 `dd4085950a119d9e33a6de1d7be1fc7fe29e0cfc`、组件版本 **1.4.1**。其 [manifest](https://github.com/espressif/esp-tflite-micro/blob/dd4085950a119d9e33a6de1d7be1fc7fe29e0cfc/idf_component.yml) 要求 IDF≥5.1，[CI](https://github.com/espressif/esp-tflite-micro/blob/dd4085950a119d9e33a6de1d7be1fc7fe29e0cfc/.github/workflows/ci.yml#L20-L24) 包含 `release-v5.5` 与 `esp32s3`。这是版本声明与静态依据，不是本机编译证明；实际构建还需固定具体 IDF 5.5.x patch 和解析后的依赖锁。

| 所需算子 | 注册方法 | 固定组件中的 float32 实现 |
| --- | --- | --- |
| CONV_2D v1 | `AddConv2D()` | [esp_nn/conv.cc](https://github.com/espressif/esp-tflite-micro/blob/dd4085950a119d9e33a6de1d7be1fc7fe29e0cfc/tensorflow/lite/micro/kernels/esp_nn/conv.cc#L302)，reference Conv |
| MAX_POOL_2D v1 | `AddMaxPool2D()` | [esp_nn/pooling.cc](https://github.com/espressif/esp-tflite-micro/blob/dd4085950a119d9e33a6de1d7be1fc7fe29e0cfc/tensorflow/lite/micro/kernels/esp_nn/pooling.cc#L203)，float MaxPool |
| RESHAPE v1 | `AddReshape()` | [reshape.cc](https://github.com/espressif/esp-tflite-micro/blob/dd4085950a119d9e33a6de1d7be1fc7fe29e0cfc/tensorflow/lite/micro/kernels/reshape.cc)，常量形状重排 |
| FULLY_CONNECTED v1 | `AddFullyConnected()` | [esp_nn/fully_connected.cc](https://github.com/espressif/esp-tflite-micro/blob/dd4085950a119d9e33a6de1d7be1fc7fe29e0cfc/tensorflow/lite/micro/kernels/esp_nn/fully_connected.cc#L121)，reference FC |
| SOFTMAX v1 | `AddSoftmax()` | [esp_nn/softmax.cc](https://github.com/espressif/esp-tflite-micro/blob/dd4085950a119d9e33a6de1d7be1fc7fe29e0cfc/tensorflow/lite/micro/kernels/esp_nn/softmax.cc#L110)，float Softmax |

可用 `MicroMutableOpResolver<5>` 注册五类，无需 AllOpsResolver 或 Flex。融合 ReLU 已包含在 Conv/FC 中。上述参数未发现静态阻断，但算子名称与源码分支存在不等于逐版本实机认证；仍须以固定依赖的 `AllocateTensors()` 和 `Invoke()` 成功、输出对齐为准。此模型走浮点参考核，**不能套用 ESP-NN int8/person-detection 的性能数字**；开启 ESP-NN 选项不会自动量化它。

### 内存与 Flash：已知大小不等于运行需求

| 项目 | 字节 / 数量 | 性质 |
| --- | ---: | --- |
| 模型文件 | 35,760 B | 实际文件大小；不含固件库/驱动/OTA 分区开销 |
| 浮点参数 | 7,875 个 / 31,500 B | FlatBuffer 静态统计，含 bias |
| 常量 tensor buffer 合计 | 31,508 B | 另含 8 B int32 reshape 常量 |
| 最大非恒定浮点 tensor | 14,976 B | 第一层 Conv 输出的逻辑大小 |
| 所有非恒定浮点 tensor 逻辑大小之和 | 37,144 B | **不是峰值 RAM，也不是 arena**；规划器可复用，另有对象/scratch/对齐 |
| Conv + Dense 运算量 | 180,240 MAC/窗 | 从形状计算，未包括池化/Softmax/预处理，不是时延测量 |
| 双 IMU 2 秒、200 Hz 三轴 float32 缓冲 | 9,600 B | 仅样点静态计算；不含时间戳、质量、锁、FIFO、SD 缓冲及复制 |
| 双 IMU 各一个 40 Hz 模型输入窗 | 1,920 B | 不代表两次推理共享所有运行内存 |
| TFLM arena / 实际固件 Flash / 板端堆峰值 | **NOT_MEASURED** | 本轮未在 TFLM 或 ESP32 执行 |

8 MB PSRAM 不能视作全部内部可用 RAM。模型可作为对齐的只读常量放 Flash；arena 优先比较内部 RAM 与显式 PSRAM 分配两案，检查连续块和剩余内部堆。该固定 Conv wrapper 即使 float32 也申请输出通道相关持久数组，三层两组 int32 的请求量合计 640 B，尚不含对齐和其他对象，进一步说明不能把激活大小直接当 arena。[分配源码](https://github.com/espressif/esp-tflite-micro/blob/dd4085950a119d9e33a6de1d7be1fc7fe29e0cfc/tensorflow/lite/micro/kernels/esp_nn/conv.cc#L93-L100)。

ESP-IDF 文档说明 PSRAM 有缓存、DMA 描述符、访问带宽及通常不放任务栈等限制；须测 Wi-Fi、MicroSD、Flash/NVS/OTA 等并发路径，不能由容量标称值认定运行安全。[ESP-IDF 5.5 PSRAM 约束](https://docs.espressif.com/projects/esp-idf/en/v5.5/esp32s3/api-guides/external-ram.html#restrictions)。

### 本机执行能力与未执行项

当前 PATH 未找到 `idf.py`、Xtensa 编译器、cmake/ninja；`IDF_PATH`/`IDF_TOOLS_PATH` 未设置，检查的标准 `~/esp`、`~/.espressif` 目录不存在。这只说明本次 shell 中没有可用工具链，不断言所有磁盘都没有安装。

因此**没有执行** `idf.py build`、flash、monitor，也没有产出声称已编译的固件 PoC。用户主目录也未发现自有 ESP-IDF `CMakeLists.txt/sdkconfig/驱动源码`；不能确定生产固件 revision。下述固件工作仅为未来建议。

## 6. 与本项目 ICM-42688-P 的适配差距

核查的是本次指定 Desktop 主项目，而非之前工作区副本。主目录是无 `.git` 的文件目录。现有 [MQTT/ESP32 状态说明](../../platform_backend/README.md#esp32-接入状态)、[B 原始批次交接](../../algorithm/B_revised/telemetry_v2_intake/RUNTIME_HANDOFF.md)、[DRAFT 参数](../../algorithm/B_revised/telemetry_v2_intake/RUNTIME_CONFIG_DRAFT.json)和 `00_TEAM_SHARED_CONTRACT.pdf` 是主要证据。

共享契约第 4 页规定 NORMAL 目标 100 Hz、其他风险状态 200 Hz，原始 IMU 进入 RAM ring/SD；网络 Telemetry 为 1/2/5 Hz 快照。第 6 页规定原始加速度为**含重力 m/s²**。B 交接第 50–87 行也明确低频 v2 不能恢复高频波形。`odr_hz/frame_id/calibration_version`、滤波和窗口正式参数仍有 null/DRAFT，不能认定已经取得相应真实 run。

| 方面 | TinyQuake 条件 | 实际项目证据 / 缺口 | 必需适配与验证 |
| --- | --- | --- | --- |
| 物理单位 | 台站 counts 经仪器响应校正为 m/s²，再归一化 | ICM 原始含重力三轴 m/s²；实际量程/scale/bias 未交付 | 从真实寄存器配置和校准换算；若驱动输出 g，显式转 m/s²；保留原值与校准版本，不填写猜测的零偏 |
| 数据形态 | 每个位置的三轴连续波形 | v2 仅 tilt/RMS 等快照；候选 raw batch 接口另有定义 | 从原始 ring/FIFO 取窗；**不能**重复、插值低频 RMS/倾角制造 80 点 |
| 频率 | 40 Hz / 80 点 / 2 秒 | 规范目标 100/200 Hz，实测 ODR/抖动未确认 | 对真实时间轴验证；100→40 比率 2/5、200→40 比率 1/5。先抗混叠，记录群延迟；ODR 切换分段并重新暖机 |
| 坐标 | E/N/Z，维持三分量相对幅度 | top/toe 安装轴向、极性和 `frame_id` 待定 | 每 IMU 确认到 ENZ 的旋转/极性并记录；不能默认 XYZ=ENZ，也不能只交换列就证明兼容 |
| 双路输入 | 模型只接一个位置的三轴 | 两个独立安装位置 | 两路各自预处理并串行调用同一解释器；不要直接拼成六通道或先平均；双路判决融合另行验证 |
| 噪声/频响 | 高 SNR、近场台站筛选数据 | MEMS 噪声、温漂、重力/姿态变化、安装耦合未知 | 测静置/温度/长时 PSD、传感器互差、饱和与机械干扰；无实测噪声阈值可直接采用 |
| 滤波 | 长记录去趋势+taper+0.5 Hz 高通+响应校正 | 已有候选重力 LPF/RMS；不等于 TinyQuake 预处理 | 保留现有 B 路径，新增隔离预处理支路；检查片内滤波与抗混叠；不可把 ICM 套用地震台站响应文件 |
| 重采样 | 官方使用窗内 FFT resample | 设备流式实现未给出 | FFT 截窗有周期边界假设；流式 FIR/polyphase 是不同实现，须用固定回放检验频响、相位和输出差异；本轮 NPZ 无原始高频窗，尚不能验证此段 |
| 归一化 | 全窗跨轴 max→int16→float→max | 现有特征评分输入不是此分布 | 单独实现精确数值/截断/交织布局；不改为逐轴标准化或 [-1,1] 裁剪。先做 Python/C 数值对齐 |
| 缺样 | 准备好的定长窗；训练含一些缺通道增强 | FIFO/总线错误、缺样率和时钟漂移未交付 | 检测时间戳跳变、重复、溢出、无效位和饱和；缺样/启动/切频窗先拒识并重建窗口，不补零或补旧值冒充连续采样 |
| 标签 | P / S / Noise | 地灾场景还含雨、泵、冲击、交通、松动、倾倒 | 采集真实安装条件背景/干扰及可信参考事件标签；不训练也必须做独立回放和持续误报验证 |

[TDK 官方产品页](https://www.invensense.tdk.com/en-us/products/6-axis/icm-42688-p)列出可选量程、可编程滤波、FIFO 和典型加速度噪声 70 μg/√Hz。这是器件规格，不是本项目实测噪声或校准值；本报告未据此推算本板阈值或检测下限。

B 已有因果重力低通和窗口完整性参考，但其 DRAFT 参数与真实接线仍待交付，不能以“存在 Python 参考实现”证明实际 FIFO、滤波或漏样处理已完成。原始批次/坐标/ODR/校准变更时，应与现有分段和缺测策略保持一致。

## 7. 未来所需固件与接口改动（本轮未实施）

1. **独立实验工程先行**：固定 IDF 5.5.x patch、ESP-TFLite-Micro 提交及组件锁；从本次选定文件生成对齐模型数组，保留许可与哈希。先仅跑参考输入，输出三类分数及模型身份。
2. **MicroInterpreter 初始化**：注册上述 5 类算子；检查 schema、dtype、维度；`AllocateTensors()` 任一步失败即不启用推理。不要复用上游不一致的嵌入模型数组。
3. **采样旁路**：给每个 IMU 独立、带时间戳与质量标记的原始窗快照。保留已有 B 特征/本地报警任务，不让模型推理堵塞采样 ISR、FIFO 读取或 SD 写入。
4. **预处理与参考向量对齐**：先对 `golden_vectors.npz` 做纯推理对齐，再对真实 100/200 Hz 回放验证滤波/重采样/坐标/量纲。前者成功不能代替后者。参考向量容差须结合实际内核数值差异制定，不能凭空标“完全一致”。
5. **任务调度**：用单一任务持有解释器，两路串行 Invoke；初始化只做一次，有界队列交接拥有明确生命周期的窗。可先以每 2 秒一个不重叠窗验证工程链路；更小滑动步长只是待评估方案，不是已验证模型契约。双路预处理/推理总耗时加调度余量必须小于该步长。
6. **健康与输出接口**：实验 sidecar 记录 `model_sha256/sensor_id/window_start/window_end/sample_rate/frame_id/calibration_version/quality/[P,S,Noise]/latency`。缺样、暖机、饱和、过期时返回不可用原因，不伪装 Noise 或零风险。未经会签不改变冻结 `zhifang.telemetry.v2`，不把 softmax×100 填入 `sensor_score`，也不替换现有四级风险规则。

IDF 的 FPU 任务/ISR 和核亲和行为应按[官方 FreeRTOS 说明](https://docs.espressif.com/projects/esp-idf/en/v5.5/esp32s3/api-reference/system/freertos_idf.html#floating-point-usage)验证；不能以绑定某个核心就声称实时性达标。

上游示例有三项不能直接搬用：README 指向的 `FC_detection.ino` 实际不存在，当前文件是 `EEW_detection.ino` / Nano33 BLE Arduino 工程；`motion_model.cpp` 内嵌数组为 65,880 B，字节不匹配本次 CNN17；`test2input()` 使用 `flatten(order='F')` 导出，与应送入网络的 C/NHWC 交织布局不同，直接 memcpy 会改变通道/时间顺序。示例预留的 `100 KiB+676 B` arena 不能当成本模型在 ESP32-S3 上的测量值。[导出逻辑](https://github.com/tclements/TinyQuake/blob/fce74a7027129e721dafe56a5521d1d57b9835f9/src/test.py#L11-L37)、[嵌入示例](https://github.com/tclements/TinyQuake/blob/fce74a7027129e721dafe56a5521d1d57b9835f9/src/EEW_detection.ino)。

## 8. 已测延迟与尚未测量的资源

下表均为本次单次完整桌面基线的实际记录，不是 ESP32 或 TFLM 数据。未锁 CPU 频率、未提供长时实时性保证。

| 桌面项目 | 结果 |
| --- | ---: |
| 创建解释器+AllocateTensors | 0.312917 ms（一次） |
| 预热 | 50 次，不计入后续时延统计 |
| 计时窗数 | 17,427 |
| Invoke mean / P50 / P95 / max | 0.010788 / 0.010459 / 0.012000 / 0.045625 ms |
| set+invoke+get mean / P50 / P95 / max | 0.011778 / 0.011417 / 0.013404 / 0.063625 ms |
| 原始滤波/重采样耗时 | NOT_MEASURED（输入是已准备 NPZ） |
| TFLM arena 实际占用 | NOT_RUN |
| ESP32-S3 推理与预处理时延/功耗 | NOT_RUN |
| 双 IMU + Wi-Fi + SD 并发抖动/漏样 | NOT_RUN |

未来应在隔离板端工程使用 [RecordingMicroInterpreter](https://github.com/espressif/esp-tflite-micro/blob/dd4085950a119d9e33a6de1d7be1fc7fe29e0cfc/tensorflow/lite/micro/recording_micro_interpreter.h) 记录分配，再用普通解释器测 `arena_used_bytes()` 和可用容量；记录器本身有额外开销。用 `esp_timer_get_time()` 分别测预处理、Invoke、端到端窗龄，暖机后报告 P50/P95/最坏值、内部/外部剩余堆、最大连续块与任务栈余量，再在 Wi-Fi/SD/Flash 操作下重测。没有这些结果前，不给出“需 X KB arena / Y ms 即可部署”的结论。

## 9. 科学局限与接受条件

- 这是已发生波形的分类器，不提供未来地震时间、地点或震级；P/S 检测也不自动构成具备可用提前量的预警系统。
- 官方选择数据包含近场、高 SNR、较高到时置信度条件。不能推广到弱震、所有地震台站、MEMS 地表安装或坡体滑动。
- 当前公开 NPZ 没有事件/台站身份；源码以时间切分，没有证据证明事件与台站完全独立。训练验证也未证明按事件隔离；本轮不宣称重新审计了训练数据无泄漏。
- 上游测试脚本在测试标签上扫描阈值，再选测试 accuracy 最大者画矩阵；本报告使用固定模型的 argmax 与预先指定的 0.8 比较，不报告挑选后的“最优测试成绩”。
- 低幅 Noise 窗经过筛选，真实静置背景分布可能不同。三类 softmax 无设备质量/未知扰动类别；高置信输出不保证输入来自训练分布，归一化还可能放大微小噪声。
- 窗口级准确率不等于连续事件检测 recall、误报/小时、提前量、风险等级有效性。需有与实际安装一致的连续背景和独立标注参考事件，冻结拒识/投票策略后评价。
- 两个 MEMS 位置的观测及相互一致性尚未验证，不能简单平均分数降低风险。正式阈值、坐标矩阵、噪声门限、插值容忍度和滤波参数均未凭空填写。

要从 EXPERIMENTAL 升级为 ACCEPT，至少需要：固定 IDF/组件的目标构建；N8R8 实板参考向量数值对齐；实测 arena/Flash/堆和并发时延满足原任务；真实连续双 IMU 的时间、单位、方向、质量与预处理验证；独立现场背景/干扰和参考事件回放；明确分数用途、许可归属和故障降级策略。**不要求重训即可做这些验证，但本轮均未用缺失证据替代完成状态。**

## 10. 复现与交付文件

本轮实际隔离工作目录：

```text
work/TinyQuake
work/tinyquake-evaluation/.venv
work/esp-tflite-micro
```

主项目仅新增本目录下的评估报告、选定模型和许可、复现脚本、环境锁及结果。没有更改现有 `algorithm/`、`platform_backend/`、生产固件或正式风险配置；没有推送 GitHub。

主项目根目录可按下列方式建立新的隔离复现环境（这段是后续复现指令，不表示在 Desktop 主目录再次执行过）：

```bash
mkdir -p work/tinyquake-evaluation
git clone https://github.com/tclements/TinyQuake.git work/tinyquake-evaluation/TinyQuake
git -C work/tinyquake-evaluation/TinyQuake checkout fce74a7027129e721dafe56a5521d1d57b9835f9
python3.11 -m venv work/tinyquake-evaluation/.venv
work/tinyquake-evaluation/.venv/bin/python -m pip install \
  -r docs/model_evaluation/tinyquake/requirements-lock.txt
work/tinyquake-evaluation/.venv/bin/python \
  docs/model_evaluation/tinyquake/desktop_baseline.py \
  --repo work/tinyquake-evaluation/TinyQuake \
  --output work/tinyquake-evaluation/rerun-results
```

环境锁记录本轮 macOS ARM64 安装结果，其他 OS/架构不保证全部相同版本 wheel 可用；原始模型和数据哈希必须保持一致。重新运行不需要训练集，不执行训练或转换；时延随主机而变。`predictions.csv` 的 index 是 NPZ 行号，不是事件 ID。

| 文件 | 用途 |
| --- | --- |
| [desktop_baseline.py](tinyquake/desktop_baseline.py) | 固定版本检查、模型解析、官方预处理、完整参考集推理与结果输出 |
| [requirements-lock.txt](tinyquake/requirements-lock.txt) | 实际桌面环境版本 |
| [baseline_results.json](tinyquake/results/baseline_results.json) | 本次真实 I/O、算子/量化、计数、指标与主机时延 |
| [predictions.csv](tinyquake/results/predictions.csv) | 全部 17,427 窗的原行号、标签和三类分数 |
| [golden_vectors.npz](tinyquake/results/golden_vectors.npz) | 每类首个有效参考输入及桌面输出，供未来板端核对 |
| [选定模型](tinyquake/model/model_17_16_32_32.tflite) | 未修改的官方字节副本，SHA-256 见第 1 节 |
| [第三方说明](tinyquake/THIRD_PARTY_NOTICES.md) | 模型、代码与数据源归属及派生处理说明 |

最终结论：**官方 CNN17 值得继续做独立 ESP32-S3 工程实验；尚无证据支持直接集成生产监测或宣称完成部署。**
