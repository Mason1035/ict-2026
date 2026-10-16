# 智哨防灾 · 多模态平台与数字孪生指挥中心

现有 Vue 3 + TypeScript + Vite + Three.js 页面已接入 FastAPI。默认模式从后端读取 SQLite 中的遥测、历史、告警、MQTT 状态和视觉结果；原浏览器模拟器保留为明确隔离的“本地演示”。

## 启动

在仓库根目录执行 `./scripts/run-platform.sh`，打开 <http://127.0.0.1:8000>。
后端安装、API、MQTT 实验源、数据与权限边界见 [后端 README](../../platform_backend/README.md)。

前端开发：

```bash
cd apps/geohazard-demo
npm ci
npm run dev -- --port 5173
```

Vite 将 `/api` 代理到 `http://127.0.0.1:8000`，后端需单独启动；代理目标可通过 `BACKEND_URL` 配置。前端生产构建使用同源 `/api/v1`，无需把凭据写入打包文件。

```bash
npm run typecheck
npm run build
npm test
```

后端直接托管 `dist/`，修改前端后需重新构建。具体后端请求、响应结构和错误定义见 <http://127.0.0.1:8000/docs>。

## 两种模式

- **后端平台**：站点、设备和来源选择；传感器/视觉/最终风险；三维沙盘；MQTT 配置增删改查和实际握手测试；图像上传、参考帧、ROI、质量与变化分析；告警人工确认；数据库历史与原始消息查看。每两秒更新，后端断开时显示失败，未知数据保持空值。
- **本地演示**：原四场景、滑块、仿真倍速、离线队列和相机交互，仅使用浏览器内存，不自动冒充后端数据。通过页面入口切换，也可使用 `?mode=local`。历史本地演示实现说明见 [原始实现记录](docs/IMPLEMENTATION.md)。

## 建议体验流程

1. 在后端平台切换暴雨/位移/极端场景：观察持久化遥测、历史和告警；刷新网页后记录保留。
2. 进入视觉页，一键生成明确 MOCK 图像样例，或上传同一相机的两张 PNG/JPEG，选择参考图与 ROI 后分析，查看 SSIM、变化面积、光流和叠加图。
3. 按后端 README 启动本机 MQTT 示例源，在接入页配置 `127.0.0.1:18883 / MOCK-LAB / MOCK`，启用并测试后切换到 `MOCK-NODE-01`，观察真实 Broker → 后端 → 页面链路。
4. 查看告警与数据库历史；人工确认只表示已读，不降低风险。连接失败保持明确错误，不退回本地模拟器。

## 文件职责

- `App.vue`：选择后端平台或独立本地演示。
- `PlatformDashboard.vue`：后端监测、来源、风险、告警和历史视图。
- `platform/usePlatform.ts`、`platform/api.ts`：请求、认证、轮询、取消与断连状态。
- `platform/ConnectorPanel.vue`：MQTT 配置和连通性检查。
- `platform/VisionPanel.vue`、`platform/AuthMedia.vue`：图像上传、对比、ROI 与认证媒体加载。
- `DemoDashboard.vue`、`store/useSimulation.ts`、`simulation/`：保留的浏览器演示逻辑。
- `components/TerrainScene.vue`：程序化地形、视图和监测点；无风险值时使用未知状态。

## 边界

后端默认演示数据标记 MOCK / TEST_ONLY，与真实 MQTT 来源分开。程序化地形不是实际 DEM；演示降雨和裂缝不是已经部署的物理传感器。正式湿度为相对湿润度，振动原文为 m/s²，页面 g 值经过显式转换。

OpenCV 图像变化是技术观测，尚未校准为灾害评分；视觉分数保留 null，融合保持 sensor_only / unavailable。真实 Atlas、UVC 持续采集、视频流、UAV、IoTDA、正式模型和完整融合仍需后续接入。原共享契约与团队职责保持不变。
