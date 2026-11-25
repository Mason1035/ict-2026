# 2026-10-05：补充 Telemetry v2 / Edge Intake

李青原 10/4 任务书和最新 A Mock 记录确认：现有联调触达的是 C 的训练 `RealAdapter.to_dataset()`，
其 ContractNotReadyError 是接口职责不匹配，不能靠隐藏异常或改 TrainingContract Validator 解决。

本次新增独立 `edge_intake` V0.1.0，明确前置上游验证、原始 v2/三元身份/null 保留、
MOCK provenance sidecar、A-compatible canonical hash 与未实现下游状态。
接收仅在内存中，没有 durable ACK；没有更改 v2、物理模型、训练骨架或 B 的交付。

沿用 stdlib + 现有 pytest，无新依赖。37 测试及固定 A 真实 checkout 四例通过；
M01/M02/M07 各 1 次真实调用、M08 四次拒绝后调用 0；独立 review 无阻断问题。
结果、复现命令与 source hashes 见 [测试记录](../../test_records/integration/2026-10-05_edge_intake_v0.1.0/README.md)。

A 当前旧 adapter/runner 没有在本轮修改，B 没有调用，三人 Mock 仍 NOT_RUN。
下一步由 A 固定新 C commit 更新接线，再和 B 新入口并列重跑；生产下游和真实模型不在本轮。
