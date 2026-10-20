# 本实验工程第三方归属

模型来自 TinyQuake（Tim Clements, 2022），固定提交 fce74a7027129e721dafe56a5521d1d57b9835f9，CNN/models/model_17_16_32_32.tflite。其原始 35,760 字节嵌入 main/model_data.cc，没有训练、转换或模型量化；完整 MIT 许可见 TinyQuake-LICENSE.txt。

三组预处理参考输入源于 TinyQuake 提供的 STEAD 派生 test.npz，NPZ 行号分别 3/0/2。它们经过上游幅度筛选、归一化和 int16 中间转换；本工程只将其按 C/NHWC 布局编码为 float32 常量。它们不是本项目真实 IMU 数据。

STEAD 归属：S. M. Mousavi, Y. Sheng, W. Zhu, G. C. Beroza, 2019, STanford EArthquake Dataset, IEEE Access, DOI 10.1109/ACCESS.2019.2947848。数据许可 CC-BY-4.0：https://creativecommons.org/licenses/by/4.0/ 。原始来源：https://github.com/smousavi05/STEAD 。

TinyQuake 预处理注明借用 EQTransformer 的函数（S. Mostafa Mousavi, MIT）；本工程只按公开数值流程实现最终归一化，没有提供完整原始传感器处理。ESP-IDF、ESP-TFLite-Micro、ESP-NN 及其第三方内核按各自上游许可证使用，依赖版本见 dependencies.lock。本工程没有复制上游 Arduino sketch。

预编译串口镜像的 ESP-IDF / ESP-TFLite-Micro / ESP-NN（Apache-2.0）、FreeRTOS、newlib、FlatBuffers、gemmlowp 以及 GCC Runtime Exception 许可文本随附于 [licenses/](licenses/)。源码依赖由 IDF Component Manager 按锁文件获取，未把 SDK 或组件构建目录纳入本仓库。
