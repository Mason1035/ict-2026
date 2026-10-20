# Atlas 部署验证结果（2026-10-20）

对象：`ai_training/pretrained/public_sensor_v1` 的 soil / motion 研究模型
（`zhifang.public-sensor-forecaster.v1`，下一次观测增量预测；**不是**滑坡分类器、
风险或视觉评分，`deployment_ready=false` 不变。本记录仅为工程流水线验证。）

链路：JSON 权重 → ONNX（图内特征构造+标准化+线性层）→ ATC（板上，310B4）→ OM → pyACL NPU 推理 → 黄金向量对账。

## 各阶段结果

| 阶段 | soil | motion |
|---|---|---|
| 基准实现 vs 仓库原模型（float64 最大差） | 3.4e-17 | 2.2e-16 |
| ONNX（onnxruntime） vs 基准（最大差） | 3.1e-09 | 9.5e-06 |
| ATC 转换（板上 root 运行） | 成功，约 11 分钟 | 成功，约 9 分钟 |
| OM 大小 | 64,394 B | 67,815 B |
| NPU 推理 vs 黄金（最大绝对差） | 1.03e-05 | 8.08e-03 |
| NPU 尺度相对误差（最大差/输出量级） | 1.8e-04 | 3.2e-04 |
| NPU 输出与基准相关性 | — | 0.99999996 |
| NPU 平均单次执行延迟（10 窗口） | 0.29 ms | 0.18 ms |

## 关于 motion 的绝对差

motion 输出量级达 ±25（陀螺通道系数大），绝对差随量级放大；与 CPU fp32
（onnxruntime）交叉对比显示：ORT 与 float64 基准差 9.5e-06，而 NPU 与 ORT 差
8.1e-03——差距全部来自 310B 的 fp32 MatMul 数值路径（48 维点积、宽动态范围），
不是图翻译错误（相关性 0.99999996，误差随量级成比例）。判定：以尺度相对误差
3.2e-04 通过流水线验证；若未来正式模型对绝对精度有要求，需在契约中约定
相对容差或改用更高精度计算路径，并重新标定。

## 板上运行要点（实测踩坑）

- ATC 必须以 **root** 运行：普通用户读不到 `opp/vendors/customize` 下的算子实现文件；
- ATC 的 Python 必须是厂商 conda（`/usr/local/miniconda3/bin` 置于 PATH 首位），
  系统 python3 缺 numpy/decorator 等 TBE 依赖（EC0010）；
- ATC 无 `--version` 参数；
- 板上同时只能跑一个 ATC：多个并发会把 3.4G 内存抢光、编译近乎停滞；
- pyACL 运行模式为 ACL_DEVICE（200I DK 板载 CPU）；`acl.rt.get_run_mode()` 返回 1；
- ATC 产物默认权限 600/root，ACL 以普通用户运行前需 `chmod 644`。

产物位置（板）：`/home/HwHiAiUser/ict-2026/experiments/atlas_public_sensor_v1/`
（`soil_forecaster.om`、`motion_forecaster.om`、`*_acl_result.npz`）。
平台状态自报的 `atlas_acl` 仍为 `not_connected`——本次仅证明模型可在 NPU 上
正确执行，尚未把推理接入平台运行时。
