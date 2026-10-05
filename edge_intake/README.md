# Telemetry v2 / Edge Intake V0.1.0

负责人 C（何宇轩）的独立最小接收入口，供 A/B/C Mock 联调使用。
接收**已经通过上游格式校验**的 `zhifang.telemetry.v2` JSON 对象，返回原始内容的独立内存快照、
三元身份、来源 sidecar、内容 hash 和明确的下游状态。当前状态：`MINIMAL_INTAKE`；不构成生产 Edge 服务。

依据：项目 `docs/00_TEAM_SHARED_CONTRACT.pdf`（最高契约）、负责人 A/B/C 文档，
以及李青原《何宇轩方向：Telemetry v2 / Edge Intake 最小正式入口任务书》V0.1（2026-10-04）。
任务书中的示例状态用于本入口，未修改正式 v2 字段、单位、风险等级或阈值。

## 数据流与职责

```text
原始 Telemetry → 上游 Validator → 同一份已验证原始 payload
                                  ├→ B Feature / Risk
                                  └→ C receive_validated_telemetry
                                       → 返回内存快照与接收状态
                                       → 下游 NOT_IMPLEMENTED
```

原始 Telemetry 不经过 Risk 输出中转。`ai_training` 的 TrainingContract Validator 和
`RealAdapter.to_dataset()` 继续负责训练数据契约，不作为 Telemetry Intake。
`physics_sim` 输出也不是正式 v2 Telemetry 或 A Real Experiment CSV；本入口不导入两个模块。

## 接口

从仓库根目录使用 Python（3.10+），只依赖 stdlib：

```python
from edge_intake import receive_validated_telemetry

# 必须先由上游 validator ACCEPT；失败的消息不得调用本入口。
result = receive_validated_telemetry(validated_payload, context=validated_context)
```

输入 `payload` 支持 `dict` 或 `Mapping`；递归支持 JSON 值及 A runner 的
`MappingProxyType` / tuple 只读视图。返回值将只读数组视图恢复为 JSON list，保留原始 JSON 语义、
所有字段、数值、null 和 `device_id / boot_id / seq`，不重新分配身份、不修复缺测、不计算 Risk。

`context` 是可选 JSON sidecar（`Mapping` 或 `None`）。Mock 调用保留
`source=MOCK`、`case_id`、`scope=TEST_ONLY`、`sampling_snapshot`；这些字段不会加入 payload。
未提供 source 时返回 `null`，不会猜测 `REAL`。同一个 null 不能证明某一路是 Unavailable 还是 Error，
逐路 validity/time 信息仅保留上游 sidecar，不由 Intake 推断。

| 返回字段 | 含义 |
|---|---|
| `status` | `ACCEPTED_BY_EDGE_INTAKE`，仅表示已生成内存接收快照 |
| `identity` | 原值 `device_id`、`boot_id`、`seq` |
| `payload` | 独立 JSON 快照；与上游及其他消费者没有可变引用共享 |
| `context` / `source` | 来源与采样证据 sidecar；未知为 null |
| `payload_sha256` | 下述 canonical JSON 的 SHA-256 |
| `intake_version` | `0.1.0` |
| `downstream` | `NOT_IMPLEMENTED` |
| `downstream_status` | `DOWNSTREAM_NOT_IMPLEMENTED` |
| `durable` | `false`；没有持久化，也没有允许 NODE 清理的回执 |

hash 与 A 的 `mock_loader.payload_hash()` 一致：
`json.dumps(payload_snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)`
的 UTF-8 字节取 SHA-256。字段顺序和系统时间不改变此内容身份；context 不参加 payload hash。
**这是 JSON 内容 hash，不是原始网络字节 hash**。本接口输入已解码对象，不能恢复原始 wire bytes。

调用者持有返回快照；本模块没有后台缓存、数据库、网络传输或持久化。
收到返回值不等于 Atlas 保存成功，不能据此清理 NODE 原文、SD 文件或 cloud spool。

## 校验边界与错误

上游必须校验正式 Schema、必填、类型/范围、null 语义、Topic/site/device 一致性等。
本入口只额外保护 schema 常量、非空 device_id、非负整数 boot_id/seq，以及有限可编码 JSON。
布尔值不能冒充整数；非法类型、NaN/Inf、循环引用、不可编码 UTF-8 等抛出 `EdgeIntakeError`，不静默修复。
函数名和这些保护不证明已完成全部上游校验；没有生产 Validator 的调用者不能绕过前置条件。

## 文件职责

- `intake.py` / `__init__.py`：独立公开 API、快照、内容 hash 和边界错误。
- `scripts/verify_mock_intake.py`：TEST_ONLY 四用例验证与证据输出，可核对 A 的独立 checkout。
- `tests/`：接口保护和实际调用计数测试；固定 A Mock 用例、loader、validator 的只读副本和来源 hash。
- `CHANGELOG.md`：只记录实际修改、实测与限制。

## 测试与交接

```bash
PYTHONDONTWRITEBYTECODE=1 work/.venv/bin/python -m pytest edge_intake/tests -q
PYTHONDONTWRITEBYTECODE=1 work/.venv/bin/python -m edge_intake.scripts.verify_mock_intake
```

Mock fixture 固定于 A commit `25c55ca0ab2e9d0f18e3640833a575102f7e48c6`。
它们是 `TEST_ONLY / MOCK_ONLY / NOT_REAL_DATA`；A Mock Validator 不是生产 Validator。
M01/M02/M07 上游接受后必须真实调用本入口，M02 middle_raw=null、M07 三个 Risk null 保持原值；
M08 四条消息必须上游拒绝，入口真实调用计数 0。不得把“合法 JSON”当成“合法 v2”。

A 旧 `he_adapter.py` 仍指向训练入口，runner 仍有旧状态断言。
李青原需更新 pinned C source 和 adapter，改为调用此 API，检查新状态及保留内容，
再与 B 正式算法入口一起重跑四例。当前不声明 `THREE_PERSON_MOCK_INTEGRATION_PASS`。

## 已知限制与待办

- 只完成解码后对象的内存接收边界；生产完整/LoRa 部分 Validator、认证、Topic 校验未实现。
- Dedup/冲突合并、durable store/receipt、MQTT、Atlas、Cloud、Web 均 `NOT_IMPLEMENTED`。
- 不处理重传、乱序、掉电恢复、spool 或持久化确认；重复输入每次返回快照，没有 exactly-once 承诺。
- A/B 联调仍需各自维护 adapter/入口；A 的真实硬件、真实数据和标定验收不由 Mock 替代。
- G01–G09 等团队开放项不因本轮接收成功而关闭；本模块不定义 Feature/Label/阈值/校准参数。
- 后续有意义修改必须同步当前 README 与真实 CHANGELOG，不自动扩展本轮下游。
