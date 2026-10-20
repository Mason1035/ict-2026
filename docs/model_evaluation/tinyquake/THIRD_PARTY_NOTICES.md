# 第三方来源与派生处理说明

## TinyQuake

来源：https://github.com/tclements/TinyQuake
固定提交：`fce74a7027129e721dafe56a5521d1d57b9835f9`
版权：Tim Clements，2022；根许可 MIT，完整副本见 `TinyQuake-LICENSE.txt`。

`model/model_17_16_32_32.tflite` 是该提交 CNN 模型的未修改副本。没有训练、重新导出或量化权重。桌面脚本从该提交 AST 提取四个纯 NumPy 预处理函数执行，以保持原数值行为；没有运行训练脚本或反序列化 pickle 执行代码。

## STEAD

S. M. Mousavi, Y. Sheng, W. Zhu, G. C. Beroza (2019), “STanford EArthquake Dataset (STEAD): A Global Data Set of Seismic Signals for AI”, IEEE Access, DOI: [10.1109/ACCESS.2019.2947848](https://doi.org/10.1109/ACCESS.2019.2947848)。

原始来源：https://github.com/smousavi05/STEAD
原数据源许可：[Creative Commons Attribution 4.0](https://creativecommons.org/licenses/by/4.0/)，见 [STEAD LICENSE](https://github.com/smousavi05/STEAD/blob/master/LICENSE)。

本次没有重发完整 STEAD 或 TinyQuake `test.npz`。`golden_vectors.npz` 的三个波形来自 TinyQuake 已提交的 `data/test.npz`，再按其幅度筛选、归一化、int16 中间转换和 float32 归一化得到；索引为 3、0、2，按 P/S/Noise 顺序保存。`outputs` 与 `predictions.csv` 是本次桌面模型推理生成的派生分数，非 STEAD 原始标签之外的新实采事实。这些输入与结果不是智哨设备采集数据，也不是新的训练集。

## 其他归属

TinyQuake `src/dataprep.py` 注明部分函数借自 [EQTransformer](https://github.com/smousavi05/EQTransformer)，其[官方许可证](https://github.com/smousavi05/EQTransformer/blob/master/LICENSE)为 MIT / S. Mostafa Mousavi。本次不分发 EQTransformer 源码；后续复制其源代码时须同时保留对应版权与许可。

TinyQuake `EEW_detection.ino` 自带 TensorFlow Authors / Apache-2.0 头。本次不复制该 sketch，也不把其嵌入数组当成本次模型；未来复用该代码应保留相应许可。

首次模型评估对 ESP-TFLite-Micro 仅克隆并静态阅读，没有复制其源码进入生产项目。后续独立固件构建使用 Component Manager 获取的 1.4.1，见固件锁文件与第三方说明。固定提交 `dd4085950a119d9e33a6de1d7be1fc7fe29e0cfc`。其组件和第三方内核归属应在未来独立构建时按上游各许可证保留。
