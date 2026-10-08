# 2026-10-05 Telemetry v2 算法入口

依据 E 盘 `张鹏飞_Telemetry_v2_Feature_Risk_最小正式入口任务书_V0.1.docx`，在 `algorithm/B_revised/telemetry_v2_intake/` 新增 B 自己维护的入口。它接收上游已验证的 v2 payload，映射身份、时间、IMU、Soil 与 system；调用原有候选函数，明确返回 Feature 阻塞和 `RISK_EXECUTION_BLOCKED`，保留 payload 的三个 risk 字段。没有复制 A 的 Adapter/Validator 或改动团队 Telemetry。

只读获取 `origin/李青原`（`25c55ca0ab2e9d0f18e3640833a575102f7e48c6`）中的 M01/M02/M07/M08 fixture 与 TEST_ONLY Validator：前三个各被 Validator 接受并调用 B 入口一次，M08 四条均被拒绝且 B 入口零调用。`sampling_snapshot` 只传作旁证，不参加 Feature 计算。此证明是本地 Mock 兼容，不是正式 Risk 算法或三人集成 PASS。

本次代码由 Codex 完成，不记录为码道 CodeArts 的操作。正式风险评分仍待 A 的校准/有效性/窗口数据及 B 的贡献映射和 Missing Policy；C 的 Edge Intake 与正式 Validator 后续由相关主责联调。

验证：新入口 4 项单测通过；B 目录相关 29 项与既有适配 18 项测试通过；4 个新 Python 文件均以 `ast.parse` 无缓存语法检查通过。跨分支脚本的 M01/M02/M07 入口调用数各 1，M08 四条拒绝后的入口调用数 0。编译缓存目录因 E 盘当前权限未能写入，故未把 `compileall` 的失败当作语法失败；实际导入和执行已通过。
