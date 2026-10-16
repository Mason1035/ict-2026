# 智哨防灾 · 本地多模态平台后端

FastAPI + SQLite WAL + Paho MQTT + OpenCV。该模块将真实消息接收、配置保存、历史查询、告警与图像分析连接到现有 Vue 页面。它是本地软件集成版本，不代表真实硬件、正式风险模型、Atlas 或华为云验收完成。

## 启动

需要 Python 3.11+；首次构建页面需要 Node.js 20.19+ 或 22.12+。在仓库根目录执行：

```bash
chmod +x scripts/run-platform.sh
./scripts/run-platform.sh
```

打开 <http://127.0.0.1:8000>，交互式 API 文档为 <http://127.0.0.1:8000/docs>。启动脚本在缺少本地虚拟环境时安装后端依赖，在缺少构建页面时安装并构建前端。现有依赖变更后执行 `platform_backend/.venv/bin/python -m pip install -e ./platform_backend`；前端修改后执行 `npm run build --prefix apps/geohazard-demo`。

开发模式可以使用两个终端：

```bash
# 仓库根目录：后端
platform_backend/.venv/bin/python -m uvicorn geohazard_platform.main:app --host 127.0.0.1 --port 8000

# 另一终端：现有前端，/api 代理到后端
cd apps/geohazard-demo
npm run dev -- --port 5173
```

## 数据与运行模式

- **平台模式为默认入口**：页面每两秒读取后端。数据库和后台任务在页面关闭后仍继续运行；后端不可达时显示连接失败，不回落为伪实时数据。
- **后端演示**：默认生成 `site_id=DEMO / device_id=DEMO-NODE-01` 的 MOCK / TEST_ONLY 消息，场景 A/B/C/D 约为 18/46/72/91。原始协议仍是 v2；演示雨强、裂缝及算法说明只写入接入 sidecar，不添加到冻结 Telemetry。实际 MQTT 连通状态与演示设备的 system 字段分开显示。
- **本地演示**：原有浏览器沙盘作为明确独立模式保留，不承担平台实时状态。
- **真实流**：在 MQTT 接入配置中设置独立站点、设备与 `source=REAL`；正式主入口仍为设备/网关 → MQTT → 后端接入。HTTP `/ingest/test` 只接收隔离的 MOCK-/DEMO- 设备 ID，且可随演示模式禁用。
- `GEOHAZARD_DEMO=0` 停止后端演示和测试注入，设备 MQTT 接收与历史查询继续工作。`GEOHAZARD_DATA_DIR` 指定数据目录，默认 `platform_backend/data`；刷新页面或重启后端不会清空数据库和图片。

## 已实现的接口

以 `/api/v1` 为前缀，准确请求字段、错误码和返回结构见运行中的 `/docs`：

| 接口 | 用途 |
| --- | --- |
| `GET /health` | 数据库、MQTT 会话、演示生产者与未配置能力状态 |
| `GET /sites`、`GET /devices`、`GET /sites/{site}/devices` | 数据来源与设备索引 |
| `GET /dashboard` | 当前值、同源历史、风险、告警、事件与视觉观测 |
| `GET /devices/{device}/telemetry` | 站点/来源/时间过滤、上限和稳定游标分页 |
| `POST /ingest/test` | 明确 MOCK / TEST_ONLY 的受限软件注入 |
| `GET/POST /connectors`、`PUT/DELETE /connectors/{id}` | 连接配置持久化与版本更新 |
| `POST /connectors/{id}/test` | 实际 CONNACK + SUBACK 检查；失败按真实结果返回 |
| `GET /alarms`、`POST /alarms/{id}/ack` | 风险升级告警、幂等人工确认 |
| `GET /events`、`GET /quarantine` | 事件与非法/冲突消息隔离摘要 |
| `POST/GET /evidence`、`GET /evidence/{id}/file` | PNG/JPEG 证据和元数据 |
| `POST /vision/analyze`、`GET /vision/results`、`GET /vision/results/{id}/overlay` | ROI、质量、帧差、SSIM、光流与叠加图 |
| `GET /risk-results` | 引用原始消息的风险投影；当前保持 sensor_only / unavailable |
| `GET /algorithms/capabilities`、`POST /algorithms/sensor/inspect` | B 接收入口的真实候选特征检查与阻塞原因 |
| `POST /demo/scenario`、`/demo/control`、`/demo/step`、`/demo/reset` | 数据库驱动的演示控制 |
| `POST /demo/vision-samples` | 生成显式 MOCK 参考/当前图并执行 OpenCV 基线 |

历史接口以 `cursor=next_cursor` 翻页；`before`、`after` 为 ISO UTC 时间筛选。`received_at` 相同的消息通过 ID 游标区分，不因分页跳过。同一设备身份属于一个站点和数据来源，禁止 MOCK 与 REAL 共享该身份。

## MQTT 接入

连接器配置包括 host、port、site_id、topic、TLS、username/password、client_id、QoS 和 keepalive。Topic 限定为 `zhifang/v2/{site_id}/+/telemetry` 或同站点的指定设备 Topic；回调再次检查 Topic 与 payload 的 site/device 一致性。默认 Telemetry QoS 0。

启用后才启动订阅，连接并获得 SUBACK 后显示已连接；停用会停止客户端。断开后退避重连，状态与错误在 API 中保留。测试连接不会发送设备命令。

电脑没有现成 MQTT Broker 时，可在另一终端运行显式隔离的本地实验源：

```bash
# 安装开发依赖后，在仓库根目录运行
platform_backend/.venv/bin/python scripts/mqtt_demo.py
```

随后在平台配置 MQTT：host `127.0.0.1`、port `18883`、site_id `MOCK-LAB`、来源 `MOCK`，Topic `zhifang/v2/MOCK-LAB/+/telemetry`，启用且不启用 TLS。该脚本只监听本机、持续发布 `MOCK-NODE-01`，默认场景 C；可用 `--scenario A/B/C/D` 指定。平台收到消息后可从设备选择器切换查看，验证 Broker → Paho → 校验 → SQLite → 网页整条链路。它不是正式设备 Broker 的部署配置。

配置密码单独保存在本地数据库，数据库权限为 0600，读取接口只返回是否已配置，不返回密码；省略更新密码时保留原值。TLS 开启时必须验证证书，不能关闭验证。当前是本地管理员模型，生产密钥管理、用户角色和多租户权限需后续实现。

## ESP32 接入状态

已实现 ESP32 可使用的 MQTT 平台接收端，链路为 `ESP32 → Wi-Fi → MQTT Broker → FastAPI → SQLite → 页面`。本次交付没有包含可烧录的 Arduino / PlatformIO 固件，尚未进行 ESP32 真板联调；`scripts/mqtt_demo.py` 是电脑端软件实验源。

后续 ESP32 固件应按现有 `zhifang.telemetry.v2` 完整 NODE 格式发布到 `zhifang/v2/{site_id}/{device_id}/telemetry`，Topic 与消息内的站点、设备身份必须一致。保留 `device_id + boot_id + seq`；未获得 UTC 时使用 `timestamp_ms=null`、`time_synced=false`。传感器缺测保持 null，振动原始单位为 m/s²；不能用零补齐缺测或把页面演示评分当作正式风险算法。详细接入约束见 [v2 接收边界](../docs/protocols/telemetry_v2_edge_intake.md)。

连接真实板卡时需另外部署或配置可从局域网访问的 MQTT Broker，并按需设置凭据和 TLS。ESP32 的 Broker 地址应填电脑或 Broker 主机的局域网 IP，不能填 `127.0.0.1`。本仓库 MQTT 实验源只监听 loopback，不能直接供板卡连接；同机运行的后端仍可通过 loopback 订阅局域网 Broker。页面中的 REAL / MOCK 来源由连接器配置确定：板卡生成的模拟值仍应使用独立 MOCK 身份，只有真实采集流才使用 REAL。

## 数据完整性与风险边界

`telemetry.py` 在调用既有 `edge_intake.receive_validated_telemetry()` 前验证完整 NODE v2。原文、null、单位和 `device_id + boot_id + seq` 保持不变；振动原始单位 m/s²，页面展示 g 时显式除以 9.80665。LoRa 部分投影和二进制格式未猜测实现。

SQLite 事务先保存原始消息、接入 sidecar、身份与接收路径，再返回本地保存结果。相同身份、相同内容仅新增接收路径记录；冲突内容隔离。已见旧 boot 或旧 seq 作为历史保存，不覆盖当前状态。**从未见过的 boot 且没有可信 UTC 时，首次观察的会话无法证明真实先后**；设备注册/时钟约束仍需硬件联调。

本地 `durable=true` 表示当前 SQLite 事务提交成功，`node_cleanup_authorized=false` 始终保持；没有实现允许 NODE 清理 SD 的正式 Atlas 回执，也没有模拟成功上云。MQTT ACK 与数据库提交、云端确认分开。

告警来自设备上报风险等级的升级，同等级消息不重复告警；未知值、掉线和人工确认不会自动解除告警。保留 source/arrival 时间；未知采集时间明确标为仅接收新鲜度，已知过旧或未来异常时间标 stale。MOCK 演示算法独立标识，不替代 B 正式算法。

## 视觉基线

支持实际 PNG/JPEG 解码、12 MiB 与 12M 像素限制、EXIF 转向、去元数据、UUID 文件存储、ROI 范围检查。比较帧须站点、相机、来源、用途和尺寸一致。分析长边最多 1024 像素，光流统计换算回原图像素/帧对。

输出图像质量、变化面积比、SSIM、光流中位数/P95 和变化叠加图。模糊/曝光阈值只是可解释的技术启发式，不是地灾阈值。`vision_score=null`、`model_version=null`、`fusion_eligible=false`，不会把图片差异直接解释为灾害概率或取消传感器高危状态。

当前接入图片文件；USB UVC 持续采集代理、视频导入、UAV 地理映射、真实摄像头质量评估、校准视觉评分、完整风险融合、ONNX/OM/ACL 和 IoTDA 尚未接入。保留已有 B FeatureRiskRuntime 与上游契约，不通过填写 DRAFT 或修改权重绕过标定。

## 本地访问与测试

默认只接受 loopback，请求 Host 和 Origin 受限。设置 `GEOHAZARD_API_TOKEN` 后所有 `/api/v1` 请求要求 `Authorization: Bearer ...`；前端连接设置可录入该令牌，图片也经认证请求加载。`.env.example` 为说明，不会自动读取。

```bash
# 仓库根目录；开发测试依赖只用于软件验证
platform_backend/.venv/bin/python -m pip install -e './platform_backend[dev]'
platform_backend/.venv/bin/python -m pytest platform_backend/tests
cd apps/geohazard-demo
npm run build
```

测试覆盖存储、协议校验、去重/冲突/补传、真实本地 MQTT Broker、图像处理及 API。只验证此平台的相关软件，不替代正式数据、硬件、云或地质灾害效果验证。

本次本地软件验证：73 项后端测试、9 项平台页面联调通过，前端 TypeScript 检查与生产构建通过。验证包含本地 Broker 的真实 MQTT 握手和收发，不包含 ESP32 真板、Atlas 或云端验证。
