# Changelog

只记录实际发生的修改；未来 meaningful change 同步更新 README 当前状态及本记录。

## [0.1.0] - 2026-10-05

### Added

- 独立 `receive_validated_telemetry(payload, *, context=None)` 接收边界，与训练 RealAdapter 分离。
- 支持 A 的 MappingProxyType/tuple 输入，返回独立 payload/context 快照、原值三元身份与 MOCK sidecar。
- 与 A `payload_hash()` 相同的 canonical JSON SHA-256；不添加系统时间或重新分配 seq。
- schema/identity/有限 JSON/循环/UTF-8 边界保护，不修复非法数据、不补零或生成 Risk。
- 明确接收状态、`DOWNSTREAM_NOT_IMPLEMENTED`、`durable=false`。
- 固定 A commit 的四用例和两个 TEST_ONLY helper 字节快照、来源/文件 hash；验证 CLI 与不可覆盖证据输出。
- 接口交接文档、项目当前进度增量与真实测试记录。

### Changed

- 根级 README/项目状态从历史“无 Intake”更新为“最小内存接收入口已验证”；保留 9 月历史审计。
- 未改动 physics_sim、ai_training、B 交付或正式项目 PDF/XLSX。

### Tests

- 37 passed / 0 failed / 0 skipped；8 个 Python 文件 syntax compile 与公开 API import 通过。
- 固定 A checkout `25c55ca0ab2e9d0f18e3640833a575102f7e48c6` 实际复验：M01/M02/M07 各接收 1 次，M08 四拒绝、Edge 0 调用。
- M02 middle_raw=null、M07 Risk 三 null、原始身份/payload/context/source/hash 全部保留。
- 同代码同输入重复报告完全一致；固定快照与 A checkout 用例结果一致；原有受保护 150 文件无改变/删除。
- 独立 Code Review 无阻断发现；澄清 payload 时间字段参加 hash 的注释，再完成最终测试。
- 证据：`docs/test_records/integration/2026-10-05_edge_intake_v0.1.0/`。

### Assumptions / Waiting Items

- 调用前必须上游 Validator ACCEPT；内存快照不是 durable ACK，不允许清理 NODE 数据。
- A Mock Validator 仅 TEST_ONLY，未晋升为生产 Validator；未将任何 Mock 数据描述为真实量测。
- WAITING_FOR_A：李青原更新 he_adapter.py、pinned C source 与新状态断言。
- WAITING_FOR_A/B：两个正式入口并列接通后才重跑三人 Mock；本轮 B 未调用、三人联调 NOT_RUN。

### Known Limitations

- 无生产 Validator/认证/Topic 校验、durable storage/dedup、MQTT、Atlas、Cloud、Web。
- 无原始 wire byte 保存、掉电恢复或 exactly-once 保证；仅保留解码后的 JSON 内容。
- 正式训练、真实硬件/灾害模型评价没有因本轮软件通过而完成。
