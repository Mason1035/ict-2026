# 阶段 I WP4：研究只读 API 与回放视图

此层只读消费 [WP2 登记](sd_replay_analysis.md) 与 [WP3 执行器](research_rules.md)。不登记新会话、不冻结配置、不保存规则结果，不调用接收、推理、告警或生产数据库写入口。研究响应统一带 `scope: RESEARCH`、`uncalibrated: true` 和三个资格字段 `production_alarm_eligible / risk_eligible / fusion_eligible: false`；输入的 REAL / TEST_ONLY / sd_replay 语义保持原样。

## 准备与连接

先在原件目录之外，用 WP2 CLI 把四场登记到专用 SQLite；API 不自动登记，也不创建不存在的研究库。沿用已有 WP3 登记库时可在**本地开发进程**启动前设置：

```bash
export GEOHAZARD_RESEARCH_REGISTRY="$PWD/work/stage1-wp3/research.sqlite3"
# 使用已有平台开发环境；不在 Atlas 上执行。
GEOHAZARD_DEMO=0 platform_backend/.venv/bin/python -m uvicorn \
  geohazard_platform.main:app --app-dir platform_backend/src --host 127.0.0.1 --port 8000
```

不设置时研究库默认是 `work/replay/research.sqlite3`。路径支持 `~`，不能与 `Settings.database_path` 相同或指向同一文件。研究库必须恰含 WP2 的两张研究表；SQLite 使用 URI `mode=ro` 与 `PRAGMA query_only=ON`，不追加登记审计。错误库/未配置库返回 503，不退回生产库。

冻结配置只使用仓库 `platform_backend/config/research_rules/provisional-v1-r4.json`，校验现有配置契约和内容摘要；没有 HTTP 路径或参数可替换、修改、重新生成配置。

## HTTP 契约

独立前缀 `/api/research`，与 `/api/v1` 的生产资源分开；全部只有 GET。沿用平台的 loopback / Bearer Token、Origin、TrustedHost 和 `Cache-Control: no-store` 边界。

| GET | 数据 | 错误 |
| --- | --- | --- |
| `/api/research/sessions` | `items` 按 R1–R4 标签及完整身份排序；每项含 experiment_id、replay_id、类型/显示标签、采集跨度、五通道 valid/invalid 计数、质量标记、固件声明哈希与其未独立验收状态 | 未配置/非专用库 503；登记元数据损坏 409 |
| `/api/research/sessions/{experiment_id}?max_points=600` | `session` 摘要；`channels` 的 WP2 统计、WP3 通道摘要及曲线；`provenance` 配置来源 | 未登记 404；原件缺失/完整性/指纹/元数据/配置校验失败 409；点数非法 422 |
| `/api/research/sessions/{experiment_id}/rules` | WP3 原有 events/candidates/coincidences、通道贡献、临时原因 mask/codes；另附 `reason_decode` 中文解码表与 `provenance` | 未登记 404，数据校验失败 409 |

experiment_id 必须 URL 编码；只匹配当前 WP2 adapter 版本的完整登记身份，不能传入目录、CSV 文件名、设备 ID 或告警 ID 来搜索其他来源。研究前缀没有 alarms 资源，生产 alarms 的 scope 参数不接受 RESEARCH。未授权为 401，非允许的 Origin 或无 Token 的远程请求为 403。错误响应不暴露本地路径或原始内容。

列表反映**登记时元数据**；不声称列表读取就重验了所有原件。详情/规则每次重新调用 WP2 解析与转换，核对三件套指纹及完整元数据，再调用未修改的 `run_rules()`；任何失败均拒绝整场展示。原件不在时，列表仍可列出已有登记，详情明确报错。

`provenance` 包含 `method_version`、`rule_version`、`reference_version`、来源会话/类型/回放身份/三件套哈希、`generated_at`、`config_sha256`、临时原因定义版本/位表。前端还核对详情与规则结果的 experiment_id 和配置摘要一致。

## 曲线与时段

每次先在完整输入上计算 WP3 特征与规则，再对**每条曲线**降采样；`max_points` 范围 16–2000，默认 600。采用分桶极小/极大点，保留首尾、实际 acquired 场内微秒时间；不插值、不补零。每点为 `{time_us, value, break_before}`；缺指标为 null，隐藏缺口通过 segment/break_before 保留，图中不跨缺测连线。该降采样不改变任何规则结果，显示图不能替代逐点因果轨迹复验。

| 通道 | 曲线 | 单位 |
| --- | --- | --- |
| imu_top / imu_toe | 相对方向角、动态振动 RMS、STA/LTA | °、m/s²、ratio |
| soil_top / soil_middle / soil_toe | 原始 ADC 码、相对变化 | ADC code、fraction |

土壤相对变化完全复用 WP3 的起始 10 秒基线和处理副本定义；AIN2 原码与滤波副本区分，未丢弃抖动尖峰。0 仍是合法数值，基线不足不显示为 0。统计中的通道观测跨度、usable_count 和原始 valid_count 含义不同，沿用 WP2 协议。

图中浅色为 `start_us..confirmed_at_us` 的持续越限证据，深色为 `confirmed_at_us..end_us` 的已确认区间；红色为研究触发，琥珀色为永远不触发的振动候选。同时变化区间只描述已确认通道的重合，不推断因果。

## 前端入口与验证

`apps/geohazard-demo` 平台导航新增「研究回放」，也可打开 `/?mode=research`。独立视图挂载时不挂载 PlatformDashboard，不启动生产监控轮询。返回按钮回到原平台；旧本地演示入口保留。新增样式局限于研究组件，没有图表依赖，SVG 直接绘图。

页面显著保留「研究结果 · 未标定 · 非生产预警」；R4 显示「雨后静置，非干土基线」；AIN2 有质量提示。土壤只称原始 ADC 码/相对变化，符号不解释为湿/干。页面不计算风险分或概率。会话、曲线、时段与来源全部读取新 API，无运行时假数据。

连接复用 sessionStorage 内的平台 API 地址/Token，通过地址末尾 `/api/v1` 定位同源或已配置后端的 `/api/research`（保留反向代理路径）；连接错误、空登记、原件失效均显式显示，不切换模拟数据。切换会话、改连接或卸载时取消请求并清空旧结果；长计算的请求期限为 90 秒，含响应正文读取。

后端测试用合成三件套经 WP2 注册，不要求桌面数据。新增 `test_research_display.py` 是标准库服务层回归，`test_research_api.py` 是真实 FastAPI TestClient 合约；二者不能相互冒充。完整验收命令：

```bash
platform_backend/.venv/bin/python -m pytest platform_backend/tests
cd apps/geohazard-demo
npm run build
npm run test:research
```

前端依赖已安装且后端使用真实登记时，Muse 应另行浏览器检查：导航与返回、四场切换、12 条曲线/缺测断线、时段颜色与确认时刻、R4/ AIN2 提示、配置来源、错误/空态，以及生产页面回归。此轮本机环境和实跑证据见 [阶段 I 验收说明](../research/stage1-wp4/README.md)，不以静态检查代替构建或页面验收。
