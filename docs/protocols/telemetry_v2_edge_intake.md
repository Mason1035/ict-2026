# C Telemetry v2 / Edge Intake 最小入口交接 V0.1.0

2026-10-05。负责人 C：何宇轩。此文档定义 C 的**函数边界**，不新增或替代
`00_TEAM_SHARED_CONTRACT.pdf` 的正式 Telemetry Schema。

入口文件：`edge_intake/intake.py`；公开导入：

```python
from edge_intake import receive_validated_telemetry
result = receive_validated_telemetry(payload, context=context)
```

前置条件：上游 Validator 已 ACCEPT 当前完整 v2 payload。
拒绝时禁止调用 Intake。A runner 的 `MappingProxyType` / tuple 输入和同样冻结的 context 可直接传入。
B Feature/Risk 与 C Edge Intake 并列消费同一份已验证原始 payload。

返回 `status=ACCEPTED_BY_EDGE_INTAKE`，附原值 identity、detached payload/context、source、
canonical `payload_sha256`、`intake_version=0.1.0`、`downstream=NOT_IMPLEMENTED`、
`downstream_status=DOWNSTREAM_NOT_IMPLEMENTED`、`durable=false`。
不应继续用旧 local stub 的 `status=ACCEPTED` 判断本入口。

`source=MOCK` 和 sampling_snapshot 保留在 sidecar，不放入 v2 payload。
null 不补 0、不生成 NORMAL、不重分配 seq；字段名、单位、取值及 schema 原样保留。
JSON 内容 hash 定义与 A 的 `mock_loader.payload_hash()` 相同；详见 `edge_intake/README.md`。

本轮接收仅在内存中，**不是 durable ACK**；没有存储/转发成功证据，不允许据此清理 NODE 数据。
TrainingContract / RealAdapter 仍保持训练职责，不能包装为 Telemetry Validator 或接收入口。

## 李青原侧接入步骤（待 A 执行）

1. 固定包含该新入口的 C commit，更新源码 hash 与 `he_adapter.py` 的加载路径。
2. Validator ACCEPT 后直接调用入口，传入原 payload 和 MOCK context。
3. 校验返回新状态、identity/source、payload/context 保留及与 A 一致的 hash；保留异常证据。
4. M08 四条拒绝后入口 0 调用；与 B 新算法入口并列重跑 M01/M02/M07/M08。
5. 按实际两方向结果决定三人 Mock 状态，不沿用旧 RealAdapter 不匹配的预期断言。

版本化源码及四例本地证据见 `docs/test_records/integration/`。
生产 Validator/认证/去重/持久化/Atlas/MQTT/Cloud 是后续独立阶段，本轮不宣称完成。
