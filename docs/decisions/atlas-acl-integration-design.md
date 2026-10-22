# 设计：Atlas NPU 推理接入平台运行时（atlas_acl: not_connected → connected）

状态：待评审（2026-10-22）。前置成果：PR #8 已合并（experiments/atlas_public_sensor_v1 含 ONNX/OM 与真机对账记录）。

## 1. 目标与非目标

**目标**：平台运行时真正调用 Atlas 310B4 的 NPU 执行 soil / motion 两个预测模型，`GET /api/v1/health` 的 `capabilities.atlas_acl` 由实时状态驱动，演示页可见「昇腾推理：已连接」与最新预测值。

**非目标（硬边界）**：
- 不改风险融合：不改 `telemetry.py` 的风险重算、不改融合权重、不让预测结果影响任何 risk level；
- 不声称现场校准：两模型仍是研究模型（`deployment_ready=false`），输出是公开数据分布下的趋势预测增量，不是灾害分类、不是风险分；
- 不动节点侧与云上行（cloud 维持 not_connected）。

## 2. 现状证据（2026-10-22 实测）

- `atlas_acl` 是 `main.py` 健康接口中的**硬编码字符串**，`tests/test_api.py` 断言其为 `not_connected`——改状态必须同步改测试语义。
- 板上三套 Python（厂商 3.9 / geo312 / **平台 .venv 3.12**）均可 `import acl`（CANN 7.0.RC1 环境下）→ **进程内集成可行**，无需子进程 worker。但导入依赖 CANN 运行环境变量，服务启动环境需真机确认（见 §7 验收 1）。
- 平台服务模式成熟可仿：`create_app` 构造 `VisionService` / `BackendDemo` / `MQTTManager` 挂 `app.state`，同步端点走 threadpool；视觉结果有独立表与端点，且带 `fusion_eligible: false` + reasons——本设计全盘沿用该范式。
- 遥测结构：`payload.soil` 为 dict（`avg_pct` 等，0–100 百分比）；`payload.imu` 为样本**列表**（每项含 `ax..gz`、`valid` 标记）。演示发生器持续产出这两类字段，演示流即可驱动推理。

## 3. 架构

新增模块 `platform_backend/src/geohazard_platform/inference.py`，`InferenceService` 仿 `VisionService`：

- **构造与降级**：`create_app` 中构造并挂 `app.state.inference`。ACL 初始化（import acl → init → 加载两 OM）**懒执行且全异常隔离**：任何失败只把状态置为 `not_connected` 并记录 reason（如 `acl_import_failed` / `model_missing` / `acl_init_failed`），平台其余功能照常启动。遥测接入路径**永不**因推理异常失败。
- **执行模型**：服务内单条专用推理线程 + 有界队列（满则丢弃并计数，不回压接入）。ACL 调用全程串行（一把锁），单次推理超时熔断：连续失败 ≥3 次 → 状态 `degraded` 并停止尝试，等待进程重启恢复（不做热重试风暴）。
- **窗口组装**：接入成功后按 `(site_id, device_id)` 维护环形缓冲：
  - soil：取 `soil.avg_pct / 100`（百分比→体积含水率分数近似）序列，T=4；
  - motion：取 `imu` 列表中 `valid` 样本的 `(ax, ay, az, gx, gy, gz)` 序列，T=8。
  缓冲满 → 组装 float32 **原始窗口**入队。注：特征构造（末值+增量）与标准化已烘入 OM 图内（见 experiments 的 ONNX 导出与 run_acl.py 用法：喂原始窗口、直接得 predicted_delta），服务侧**不做**特征工程，只负责按 (T,C) 组装原始数值窗口。
- **结果落盘**：新表 `inference_results`（仿 vision_results）：模型名、site/device、source、scope、窗口起止时间、predicted_delta（JSON）、latency_ms、created_at。结果继承来源遥测的 source/scope（演示流即 MOCK/TEST_ONLY，不洗白）。

## 4. 特征适配口径（如实标注）

| 模型 | 训练通道（公开数据） | 平台适配 | 已知偏差 |
|---|---|---|---|
| soil (T=4,C=1) | `vwc` 体积含水率分数 | `avg_pct / 100` | 平台百分比是设备标定值，与 VWC 分数近似对应，非同一物理标定 |
| motion (T=8,C=6) | acc/gyr 三轴（原生单位） | `ax..gz` 直取 | 训练集单位与节点上报单位可能不一致 |

因此每条结果固定携带：`fusion_eligible: false`、`calibration: "uncalibrated_research"`、reason 文案（与现有 fusion 的 "No calibrated vision score" 口径一致）。

## 5. API 与前端

- `health.capabilities.atlas_acl`：由服务实时状态驱动——`connected` 仅在**至少一次真实 NPU 推理成功**后出现；此前为 `not_connected`（未启用/初始化失败）或 `degraded`（曾成功后连续失败）。禁止假绿。
- 新增 `GET /api/v1/inference/status`：状态、两模型加载情况、队列深度、累计推理数/失败数、最近一次延迟与时间、降级 reason。
- 新增 `GET /api/v1/inference/results?site_id=&device_id=&limit=`：最新预测列表（仿 vision results 的分页风格）。
- 前端（apps/geohazard-demo）：`Health` 类型补 `capabilities`；平台状态区显示 atlas_acl 状态徽标；设备面板增加「昇腾预测（研究模型，未校准）」小节，读 `/inference/results` 展示 soil/motion 的 predicted_delta。文案必须带未校准标注，不得与风险分混排。

## 6. 风险契约对齐

- 共享契约的融合为 0.65 sensor + 0.35 vision，且当前代码因视觉未校准实际运行 `sensor_only` 并附 reason——**先例明确：未校准信号不进融合**。本设计遵循先例：预测是融合之外的第三路只读信号，不占权重、不改 level、EMERGENCY 不受任何影响。
- 数据诚实：结果保留 MOCK/REAL 与 TEST_ONLY 标记；演示页标注「研究模型」；`deployment_ready=false` 不变，直至另行评审晋升。

## 7. 验收标准（Muse 板上真机执行）

1. 部署环境：板上仓库 `git pull` 至含本实现与 OM 的 main；systemd 单元补 CANN 环境（ExecStart wrapper source `set_env.sh` 或等价 Environment），重启后服务自启正常。
2. **金向量自检**：服务提供自检路径（启动自检或管理端点），用 `golden/*.npz` 各跑 1 窗：soil 绝对差 ≤5e-5（原始实测 1.03e-5，口径同 validation.txt）；motion 尺度相对误差 ≤1e-3 且相关性 ≥0.99999（实测 3.2e-4 / 0.99999996）。不达标 → 不得置 connected。
3. 演示流联跑 ≥30 分钟：inference/results 持续新增，延迟保持毫秒级，平台接入与 TinyQuake 链路不受影响；记录平台+ACL 的 RSS 与 NPU 温度曲线（3.4GB 内存上限内）。
4. 故障注入：改名 OM 文件重启 → 平台照常启动、health 显示 not_connected + reason、遥测接入正常。
5. 回归：`pytest` 全绿（健康断言改为状态语义断言：无 NPU 环境下为 not_connected 且带 reason）；前端构建通过、页面徽标与预测小节真实渲染。

## 8. 待拍板

1. 启用策略：默认 `auto`（有 NPU 则启用、失败自动降级），环境变量 `GEOHAZARD_ACL` 可强制 off/on。**推荐 auto**。
2. 前端呈现：状态徽标 + 设备面板预测小节（本设计 §5）。如只想先通后端，砍前端为独立小步。
3. soil 通道口径：`avg_pct` 单通道（模型本为单通道 vwc）。备选：三层 pct 取均值——与 avg_pct 定义重复，不推荐。
