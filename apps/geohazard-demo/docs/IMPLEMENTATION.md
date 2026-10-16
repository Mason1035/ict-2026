> 历史记录：本文描述 2026-10-08 的独立本地演示。2026-10-16 新增后端平台模式，当前运行与接口说明见 [应用 README](../README.md) 和 [后端 README](../../../platform_backend/README.md)。

# 独立 Demo 实现记录

日期：2026-10-08。范围：`apps/geohazard-demo/`。最高依据为仓库 `docs/00_TEAM_SHARED_CONTRACT.pdf`；本记录不是新正式硬件、算法或协议契约。

## 实施选择

检查本地基线 commit `7ada9fb084cc40975a2ef8bba6387635c54ce240`：已有 Python 合成模拟、训练骨架和最小 Intake，没有可升级的 Web 工程。隔离新增应用采用共享契约规定的 Vue 3 + TypeScript + Vite。Three.js 直接构建地形和监测点，不使用 React Three Fiber；SVG 承担精简趋势图，减少图表依赖。正式文档、原算法、原硬件工作区及各模块成熟度不变。

远端仓库获取未完成。基线来自本地同一仓库的相关副本，不声称代表 GitHub 当前最新内容。00 SHA256 为 `a0a5877b2ad65cd8360e304d0d93a467f6dd8904172f6206cae769bd91769d4d`。

## UI 与统一数据流

| 组件 | 职责 |
| --- | --- |
| `src/store/useSimulation.ts` | 唯一状态、dispatch、时钟、倍速与页面可见性控制 |
| `App.vue` | 顶层组合、播放控制与对话框；将用户命令交给统一 store |
| `TerrainScene.vue` | 程序化地形、风险着色、监测点、相机与 WebGL 生命周期 |
| `RiskTrend.vue` | 历史分数 SVG、坐标、悬停和历史清空 |
| `SensorCard.vue` | 当前聚合遥测、单位、来源与小趋势 |
| `NetworkPanel.vue` | NODE、Wi-Fi、LoRa、GW、MQTT、Atlas、云、SD / queue 的链路状态与通信开关 |
| `EventCenter.vue` | 事件、告警、队列及记录详情 |
| `SimulationPanel.vue` | 场景选择、传感器滑块与数值输入 |

模拟引擎与 UI 分离；引擎按确定的命令更新传感器、风险、网络、历史、告警和记录。地形接收同一实时值，只对视觉插值，不改变业务分数。历史在仿真采样时积累，不随组件渲染随机重建。事件与告警创建发生在状态转换或新的明确采样记录中，不由 render 触发。

## 风险计算边界

`src/simulation/risk-engine.ts` 的 `calculateDemoRisk(sensorState)` 处理五输入：相对湿润度、倾角、振动 `g`、场景雨强、场景裂缝。每项按控制范围 `0–100% / 0–45° / 0–2g / 0–100 mm/h / 0–20 mm` 归一化并夹限到 `0–1`，以正权重组合：

| 输入 | 权重 |
| --- | ---: |
| 湿润度 | 0.16 |
| 倾角 | 0.28 |
| 振动 | 0.20 |
| 雨强 | 0.12 |
| 裂缝 | 0.24 |

加权值经同一单调分段线性函数校准，锚点为 `(0,0)`、A 原始加权值 → 18、B → 46、C → 72、D → 91、`(1,100)`。函数限制总分到 `0–100`。各输入增加不会降低分数；手动输入与预设场景共用此函数。原始分解按归一化加权比例分配总分，最后一项承担浮点残差，使原始分解之和等于总分；UI 两位小数使用最大余数法分配到分，保持可见分解合计与可见总分相同。校准只服务产品演示，不是训练或真实危险阈值。

四级风险边界遵循 00，使用未取整分数分类，主风险整数向下取整显示，避免 29.9 显示为 30 而等级仍为低风险。正式 `sensor_score` 对应 tilt、vibration、moisture、growth 及双 IMU 一致性，不将本应用五输入 Demo 函数替换为正式实现。正式曲线、窗口、异常判据、缺测、滞回及视觉新鲜度仍为 `TODO_CALIBRATION`。

## 通信、身份与队列

有效 Wi-Fi 主链路需 NODE Wi-Fi、MQTT、Atlas 等模拟服务可用；有效 LoRa 备用需 NODE LoRa、GW-01 上行及相关 MQTT / Atlas 服务可用。LoRa 不直接连云。云服务不可用时不显示成功上云。链路判定与恢复统一由引擎负责。

`chooseActivePath` / `isPathUsable` 判定的是完整演示上行，MQTT、Atlas、Cloud 任一失败都会进入 `OFFLINE`。这是本应用简化，不把云失联解释为真实射频也失联。正式架构允许 Atlas 继续可靠接收，再独立缓存等待云恢复；本应用不实现分层 durable store / cloud spool。

离线时采样、风险和本地告警继续。消息身份为 `device_id + boot_id + seq`；重试 / 转发 / 补传保持原身份。恢复先处理当前新事件，再按优先级发送历史高危记录和普通采样；队列逐步下降。记录区分 `Pending`、`Sending`、`Synced`、`Failed`，中断发送保留可重试项。同一记录不可重复创建；历史发送不会覆盖当前数据。

引擎命令包括 `tick`、`step`、`set-scenario`、`set-sensor`、`set-link`、`set-running`、`set-speed`、`clear-history`、`reset`、`clear-demo-data`。每次 tick 推进 1 秒模拟时间；外部时钟间隔为 `1000 / speed` 毫秒。风险和传感器历史保留 120 个采样点，事件 UI 保留 160 条、最近发送保留 120 条；离线队列不随这些显示上限裁剪。预设场景没有随机噪声，不会因随机波动重复触发告警。

本应用中的发送、确认、MicroSD 与离线缓存均为浏览器内存模拟。`Synced` 表示本引擎完成模拟接收，不是 MQTT PUBACK、LoRa 链路 ACK 或可允许真实 NODE 删除文件的 Atlas 可靠持久化回执。队列真实容量、保留策略、断电恢复和云 durable receipt 未实现。

## 三维、性能与可访问性

地形为程序化沙盘，标注模拟来源。Three.js 的模式、着色、裂缝和位移表现使用统一状态。相机旋转 / 缩放、节点详情与复位只改变视图。WebGL 不可用时应保留其他面板并提供静态地形说明。

控制几何复杂度和像素比，复用几何 / 材质，组件卸载时释放资源。遵循 reduced-motion，页面隐藏时停止非必要更新；历史 UI 可限制显示数量，不能通过日志裁剪改变真实演示队列。响应式布局优先桌面与 MacBook，不等于完整移动端产品。

## 事实、数据与职责

- NODE-01 当前双 IMU / 三 Soil 实验拓扑不变；最终单 Sentinel 目标不用于删减当前平台。
- 雨强与裂缝是场景值，不暗示新增实体传感器。电量与链路状态亦为模拟元数据。
- Soil % 是相对湿润度；振动显示 `g` 需明确按 `9.80665` 转换到正式 `m/s²`。
- UAV 不是正常主通信；本应用不表示真实 LoRa 吞吐 / 距离、实飞数据摆渡或真实边缘部署。
- 正式模型、AI / 视觉、Atlas、云、真实危险阈值及端到端验证不因前端 Demo 完成而升级状态。
- 李青原：硬件、嵌入式、系统；张鹏飞：算法与数据；何宇轩：AI、视觉、Atlas、云、Web。职责不变。

## 验证与交付记录

2026-10-08 实际完成依赖安装、`npm run typecheck`、`npm run test`（12 / 12）、`npm run build`（含最终变更后的 `vue-tsc` 与 Vite Build）和 `DEMO_URL=http://127.0.0.1:5174 npm run test:browser`（19 / 19）。主 Chrome 页面 runtime errors、console errors、warnings 为空。实际浏览器输出保存在 [verification-results.json](verification-results.json)。

浏览器覆盖正常与三种灾害场景、输入 / 节点数据一致性、六项链路 / 服务门控、离线逐步积累、高危优先恢复及 ID 保留重试、历史清空、完整状态 / 相机 / 模式 / 节点重置、可见分解总分一致、原生 guide / 告警详情 / 清空对话框焦点及 Escape、标签 roving keyboard、1440×900 / 1280×800 / 960×800 / 390×844 无页面溢出、reduced-motion 下 4× 真实采样，以及强制 WebGL 不支持时的可交互 SVG 后备（独立检查中的预期 Three.js context 创建诊断不计入正常页面错误，无 runtime error）。最终 1440×900 截图见 [正常](screenshots/overview.png) 与 [紧急](screenshots/critical.png)。Safari 与真实设备长时性能未独立验证；未执行无关全仓回归。

交付文件主要为独立应用的配置、Vue 组件、模拟引擎、样式、测试和文档；根 README 仅添加导航指针。`PROJECT_STATUS_AND_READINESS.md`、`project_status.json` 和正式 PDF 保持原有事实。
