# 土壤基线模型：ESP32-S3 / C99 推理

`include/soil_baseline.h` 是已训练岭回归模型的 C 推理版本，参数由
`ai_training/pretrained/public_sensor_v1/soil_model.json` 导出。JSON 用于保存/导出模型，
开发板编译该头文件即可推理，无需在板上安装 Python、NumPy、PyTorch 或 JSON 解析器。

输入为**同一传感器最近4次有效的体积含水率 VWC**，按旧到新排列，单位为0～1体积比：
`0.32` 表示32% VWC。输出为下一次记录到的 VWC。标准化已合并进参数，调用方不要重复标准化。
本模型没有固定“未来几秒”的预测跨度；公开源数据的原生时间单位尚未确认。

4个 float32 特征系数加1个截距共20字节常量；每路历史缓冲为4个float加一个unsigned计数。
没有动态内存申请，推理只有基本加减乘运算和有效性检查。整个固件的Flash/RAM用量、栈、
板上耗时还需用目标SDK和实板测量，不能从参数大小推断。

## 调用

```c
#include "soil_baseline.h"

/* 每支传感器独立保存；在启动/新实验/缺测/时钟回退/更换标定时reset。 */
static soil_model_state soil_top;

void begin_run(void) {
    soil_model_reset(&soil_top);
}

/* 上游负责真正的ADC->VWC标定、时间顺序、缺测和采样间隔检查。 */
void on_calibrated_vwc(float vwc, int valid) {
    float predicted;
    soil_model_status status = soil_model_push_vwc(&soil_top, vwc, valid, &predicted);
    if (status == SOIL_MODEL_OK) {
        /* predicted可记录/显示；不能直接把它当滑坡概率或告警等级。 */
    }
}
```

第1～3个有效观测返回 `SOIL_MODEL_WARMUP`，第4个开始预测第5次观测。
滚动时仅加入**真实观测**，不要把预测值当成下一次输入。原始窗口调用接口为
`soil_model_predict_vwc(history, SOIL_MODEL_HISTORY, &predicted)`。
仅 `SOIL_MODEL_OK` 会写入输出；其余状态不得读取旧输出当新预测。
无效、NaN、Infinity、越界输入会拒绝；流式缓冲在无效输入时清空。
预测超出物理0～1范围会返回 `SOIL_MODEL_OUT_OF_RANGE`，不会悄悄截断。
保持普通浮点语义，不能使用 `-ffast-math`。

## ESP-IDF 集成

项目现有 NODE-01 为 ESP32-S3 / ESP-IDF 5.5.x，可在顶层 `CMakeLists.txt` 的
`include($ENV{IDF_PATH}/tools/cmake/project.cmake)` **之前**添加：

```cmake
list(APPEND EXTRA_COMPONENT_DIRS
    "${CMAKE_CURRENT_LIST_DIR}/../../ai_training/embedded/soil_baseline")
```

在实际调用模型的组件 `idf_component_register(...)` 中添加 `PRIV_REQUIRES soil_baseline`，
然后 `#include "soil_baseline.h"`。也可以仅复制这个头文件到调用组件的include目录。
上述相对路径针对 `firmware/node01`；独立工程请使用实际路径。

现有 `SoilSample.raw` 是 ADS1115 原始码，不能代入本模型；干湿两点得到的相对湿度指数
也不等于VWC。目前未实现本地ADC->VWC标定适配，没有自动接入现有RiskTask和报警输出。
先在板上回放校验向量，再用真实含水率标定数据验证；本版本不改正式20列CSV或Telemetry。

另有独立算术自检工程 `examples/esp_idf`。在已激活的ESP-IDF 5.5.x环境中，从该目录执行：

```bash
idf.py set-target esp32s3
idf.py build
# 核对实际串口PORT后再执行 idf.py -p PORT flash monitor；Ctrl+]退出monitor。
```

该工程启动后仅对TEST_ONLY输入校验结果，串口应显示 `SOIL_BASELINE_SELF_TEST PASS`。
这是供用户后续构建的自检工程；本机没有ESP-IDF/Xtensa工具链和已连接的ESP32，尚未实际交叉编译或烧录。
自检示例固定为本次4点历史模型；重新训练改变窗口或参数后，应同步更新自检输入与Python参考值。

## 主机编译与重新导出

在本目录执行（主机示例仅验证TEST_ONLY算术，不读取传感器）：

```bash
cc -std=c99 -O2 -Wall -Wextra -Werror -pedantic -Iinclude examples/host_demo.c -lm -o soil_demo
./soil_demo
```

在仓库根目录使用已有Python环境重新导出，新文件不能覆盖：

```bash
PYTHONPATH=ai_training/src python ai_training/scripts/export_soil_c.py \
  --model ai_training/pretrained/public_sensor_v1/soil_model.json \
  --output work/soil_export/include/soil_baseline.h
```

参数导出将训练时的标准化折入权重：`a=coefficients/scale`，
`b=delta_mean-mean@a`，预测为 `最近观测+b+特征@a`。
特征顺序与Python相同：`[最新值, 第2次-第1次, 第3次-第2次, 第4次-第3次]`。
使用float32存在舍入差异；主机C/Python对照检查通过不等于实板运行或迁移精度已经通过。

## 来源

LISA：Laura Longoni、Alessandro Scaioli、Lorenzo Panzeri、Diego Arosio、Monica Corti、
Azadeh Hojat、Monica Papini，Politecnico di Milano及合作机构。
[原始数据 DOI 10.7910/DVN/0H4AVF](https://doi.org/10.7910/DVN/0H4AVF)，CC BY 4.0。
本版本对公开数据清理后拟合岭回归，并将参数标准化折叠、转成float32；未更改原始数据。
