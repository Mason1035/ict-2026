# C Edge Intake V0.1.0：真实 Mock 接收边界验证

日期：2026-10-05。范围：`TEST_ONLY / MOCK_ONLY / NOT_REAL_DATA`。
对象：`edge_intake.receive_validated_telemetry`。不调用 B，不替代 A 三人 runner，不证明真实硬件或生产下游通过。

## 版本与前置条件

- A 来源：李青原分支 commit `25c55ca0ab2e9d0f18e3640833a575102f7e48c6`。
- C 修改前基线：`019a03a53336790a1439485754afdaaf3c34c9c1`；新入口版本 `0.1.0`。
- C 最终被测 `intake.py` SHA-256：`09d9d604e11d6a5b4bdc514dfcc5c8be57311887993c68d196bc9fe489e13f35`。
- Python 3.11.9 / pytest 9.0.2，沿用 work/.venv；新增运行依赖 0。
- 任务书 V0.1（10/4）和 00 Shared Contract 的文件 hash 见 `verification.json`。
- 固定快照保留 A 原文件字节；6 个输入/helper 的来源路径/hash 见 `edge_intake/tests/fixtures/a_mock/manifest.json`。

实际顺序：A Mock Validator → ACCEPT 才 check_snapshot → freeze payload/context → 真实调用 C 新入口。
M08 必须先格式拒绝，不使用采样快照修复。A Mock Validator 明确为 NOT_PRODUCTION_VALIDATOR。

## 命令与结果

在仓库根目录：

```bash
PYTHONDONTWRITEBYTECODE=1 work/.venv/bin/python -m pytest edge_intake/tests -q -p no:cacheprovider
PYTHONDONTWRITEBYTECODE=1 work/.venv/bin/python -m edge_intake.scripts.verify_mock_intake
```

实际还对 A 独立只读 checkout `/private/tmp/zhifang-a-review-mLqOTI` 执行：

```bash
PYTHONDONTWRITEBYTECODE=1 work/.venv/bin/python -m edge_intake.scripts.verify_mock_intake \
  --a-repo /private/tmp/zhifang-a-review-mLqOTI \
  --output docs/test_records/integration/2026-10-05_edge_intake_v0.1.0/mock_cases.json
```

其他机器使用自己的 A checkout，必须位于上述固定 commit 且 6 文件 hash 相同；
复验时选一个**新**输出文件，现有证据不可覆盖。

| 用例 | 上游结果 | 真实 C 调用次数 | 实际 C 结果 |
|---|---|---:|---|
| M01_NORMAL | ACCEPT | 1 | ACCEPTED_BY_EDGE_INTAKE；完整内容/身份/source/hash 保留 |
| M02_MISSING_SENSOR | ACCEPT | 1 | middle_raw=null 保留；Unavailable 采样 sidecar 保留 |
| M07_RISK_NOT_CALIBRATED | ACCEPT | 1 | sensor_score/level/reason_mask 三 null 保留 |
| M08_INVALID_SCHEMA | 4 × REJECT | 0 | NOT_CALLED；采样快照检查也未调用 |

M08 真实拒绝分别对应 schema/SCHEMA_NAME、boot_id/TYPE、seq/REQUIRED、soil.middle_raw/TYPE。
四个用例的“PASS”只表示本表的软件边界断言满足，不表示灾害安全/正常状态。

- 自动化：**37 passed / 0 failed / 0 skipped**，包括快照隔离、身份/JSON错误、hash、来源和证据防覆盖。
- 8 个 Python 文件 syntax compile、公开 API import 通过。
- 同代码同输入重复报告完全一致；固定快照与实际 A checkout 的用例和 C 源码 hash 一致。
- 受保护原有 150 文件（Physics/Training/B 活动文件及既有 docs）0 修改/删除；正式 PDF/XLSX 保持原样。
- 独立 Code Review 无阻断发现；澄清 hash 注释后最终测试重跑通过。
- 任务书要求限定本轮相关测试，未重新运行历史 210 项完整回归。

实际逐消息结果/快照/hash：`mock_cases.json`；环境、编译文件、测试数量、受保护范围：`verification.json`。

## 限制与下一轮交接

所有合法返回均为 `downstream=NOT_IMPLEMENTED`、`DOWNSTREAM_NOT_IMPLEMENTED`、`durable=false`。
没有生产 Validator/认证/Topic 校验、可靠存储/去重、MQTT/Atlas/Cloud，没有 NODE 清理权限。
`three_person_integration=NOT_RUN`，`B_risk_consumer=NOT_CALLED`。

给李青原的入口信息：`edge_intake/intake.py` → `receive_validated_telemetry(payload, *, context=None)`。
他需要固定新 C commit 更新 `he_adapter.py` 与状态断言；不再调用训练 RealAdapter。
与 B 新算法入口一起真实重跑四例后，才能评定三人 Mock；当前不虚构集成 PASS。
如果复现失败，先核对 pinned commit 和 manifest hash，再读取逐消息 validator/checks/violations；不要修改 payload 修复负例。
