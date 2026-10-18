# 真实队友 Telemetry 接收入口接入 V0.2

2026-10-05。**TEST_ONLY / MOCK_ONLY / INTEGRATION_ADAPTER**。Runner 0.3.0；不是生产 Validator、正式 Risk 执行或 Atlas/MQTT/Cloud 验收。

## 固定版本

上一轮接入开始时工作区干净，分支为李青原。未 checkout、merge、rebase 或修改队友源码。

| 来源 | commit |
|---|---|
| 李青原 HEAD、origin/李青原 | `25c55ca0ab2e9d0f18e3640833a575102f7e48c6` |
| origin/张鹏飞 | `568e229aa1d2534ea42a9f5812cdc7d9fa786cbf` |
| origin/何宇轩 | `7ada9fb084cc40975a2ef8bba6387635c54ce240` |
| origin/main | `ed4449670a81629b917e8cd177f6a836b0be1b5b` |

这是已审查的远程跟踪引用。GitHub Desktop Fetch origin 已完成，两个远程提交均与 manifest 中的 pinned commit 完全一致；当前状态为 `REMOTE_SOURCE_VERIFIED`。manifest 同时保留了早先自动 fetch 失败的历史记录，但那不是当前状态。

`teammate_sources.json` 固定 commit、Git blob ID、SHA-256 和依赖执行顺序。`teammate_source.py` 读取 Git objects，验证原字节后编译到内存；没有复制工程或重写算法。先登记最小模块集合，再按依赖顺序执行，以支持包导出入口。拒绝覆盖任一已有同名命名空间，结束后清理加载模块。需要 Python 3.10+、Git 和对应本地 Git objects，无第三方包。

## 实际调用入口

| Adapter | 队友源文件 | 函数 |
|---|---|---|
| zhang_adapter.py | `algorithm/B_revised/telemetry_v2_intake/entry.py` | `evaluate_telemetry_v2(payload, *, context=None)` |
| he_adapter.py | `edge_intake/intake.py` | `receive_validated_telemetry(payload, *, context=None)` |

张鹏飞入口投影现有 v2 并内部调用自己的候选函数。Adapter 不再逐个 probe 候选函数。何宇轩入口独立接收 v2，不再调用训练入口 `RealAdapter.to_dataset`。

```text
Mock JSON → TEST_ONLY Validator
              ├─ REJECT → Zhang / He NOT_CALLED
              └─ ACCEPT → TEST_ONLY snapshot 一致性检查
                             ↓ 同一个只读原始 payload
                 ┌───────────┴───────────┐
          B evaluate_telemetry_v2     C receive_validated_telemetry
          观测/候选特征/阻塞原因        payload/context/hash/identity
          Risk 阻塞                   内存接收；下游未实现
```

来源和逐路采样证据仍在 context，不增加 v2 字段。C 不消费 B 返回值。两路保留 null、时间和身份，不修复原文。

## 接收判定与限制

- `REAL_CODE_REACHED` 只来自 profile 观察到固定原始函数代码对象的调用帧。导入、Adapter 执行或本地 Handoff 接收都不算。
- `TELEMETRY_ACCEPTED` 是 Adapter 审计结论：B 实际返回，并核对身份、全部观测、Risk 原值和未使用 sidecar 计算。B 原始返回状态完整保存，不假称这个枚举来自 B。
- `EDGE_INTAKE_ACCEPTED` 映射 C 实际返回的 `ACCEPTED_BY_EDGE_INTAKE`，同时核对完整 payload、context、source、identity 和 hash。`durable=false`，没有允许 NODE 清理的存储回执。
- M01/M02/M07 候选 Feature 返回 `feature_status=BLOCKED`，不能标成 `FEATURES_PARTIAL`。B 返回 `RISK_EXECUTION_BLOCKED`：缺标定、滤波/基线/窗口/对齐、贡献映射，以及正式缺测策略/reason_mask。Adapter 不生成 Risk。
- C 返回 `DOWNSTREAM_NOT_IMPLEMENTED`，不是 Atlas/MQTT/Cloud 或生产 Edge 服务完成。
- M02 middle_raw=null 原样保留，TEST_ONLY Unavailable 不成为 G03 正式解法。M07 原始观测 Valid 也不产生 Risk；未标定不直接归因于 G09。
- 实际计数只统计观测到的公共入口：合法消息每方向各一次，M08 每方向零次。B 内部候选函数清单作为其返回保存，不混同于 Adapter 观测的入口调用数。

## 执行与证据

从仓库根目录执行：

```powershell
python -B -m unittest discover -s experiments/mock_interface/runner -p "test_*.py" -v
python -B experiments/mock_interface/runner/run_mock_integration.py --teammates
```

只覆盖 M01/M02/M07/M08；无 `--teammates` 时保留 Local 工作流。每次新建 `results/teammate_<UTC>_<unique>/`，保存输入字节/hash、Runner 源码/hash、成员 commit、调用参数/返回/异常、来源文件/函数和逐项检查。

M08 因 schema、boot_id 类型、缺 seq、middle_raw 类型错误在 snapshot 检查前拒绝，两个队友模块不加载、不调用。非法 payload 原样保存。

相关测试覆盖正例原值/null、同一只读对象、M08 零调用、源码 hash 拒绝、缺对象不冒充触达、命名空间保护，以及真实返回被错误改写时拒绝记为接收成功。单元测试不写 results。

`LOCAL_RUNNER_PASS` 只表示实际检查符合预期；`telemetry_boundary_expectations=MET` 表示这四例的接收边界检查满足，包括 M08 正确拒绝。不等于 Risk、生产 Validator 或下游通过。**不声明无范围限定的 THREE_PERSON_MOCK_INTEGRATION_PASS**；`three_person_integration=NOT_DECLARED`。

之前 Local Runner 和 V0.1 capability probe 结果保留原样，不回写历史证据。

## 开放项与下一步

G01～G09 仍全部 OPEN。最小内存 Intake 不关闭 G08 的生产校验、去重、冲突及完整下游缺口。不改 fixtures、Protocol/Review、C++ 或正式 Schema。

下一步先由团队核定固定版本接收证据；B 推进正式标定/贡献映射/缺测策略，C 推进生产校验和持久化接收。真实硬件仍 TBD_HARDWARE_TEST。

**NO PROTOCOL CHANGE REQUIRED**。

## 2026-10-05 Adapter 小范围清理与回归

本轮开始时保留上一轮 8 个 Runner 相关文件的修改及已有结果目录，没有无关未提交改动。实际源码已经没有旧 capability/training probe；两个文件各只有一个 docstring，He Adapter 也已经具备 `return handoff`。本轮不虚构删除或补 return 的改动，仅将 Adapter docstring 的队员代称改为 Zhang Pengfei / He Yuxuan，并增加返回值及调用边界回归检查。

本轮清理时的快速失败 fetch 曾约 2 秒返回 128 / `SEC_E_NO_CREDENTIALS`；该记录保留在 manifest 的 `historical_blocked_auth` 中。随后通过 GitHub Desktop Fetch origin 完成来源验证：张鹏飞 `568e229aa1d2534ea42a9f5812cdc7d9fa786cbf`、何宇轩 `7ada9fb084cc40975a2ef8bba6387635c54ce240` 均与 pinned commit 一致，因此当前为 `REMOTE_SOURCE_VERIFIED`。没有修改 credential helper、持久化 Git 配置或请求 token。`LOCAL_PINNED_SOURCE_TESTED` 与 `REMOTE_SOURCE_VERIFIED` 仍分别表示本地执行和来源确认。

新增回归直接核对 He Adapter 成功时返回非空 dict、包含真实 Edge receipt，加载/调用异常时仍返回包含阻塞原因的 handoff。合法消息还通过调用帧观察，确认旧 Feature probe 未绕过 Zhang 正式入口、没有 training `to_dataset` 调用；Zhang 自身入口内部的 Feature 调用是合法依赖，不能误删 manifest 中的依赖源码。

三个合法用例每方向只记录一次正式入口；M08 两方向零调用。原有 receipt checks 全部保留。结果另建目录，不覆盖旧证据，不改变完整三人 PASS 定义；G01～G09 OPEN，NO PROTOCOL CHANGE REQUIRED。
