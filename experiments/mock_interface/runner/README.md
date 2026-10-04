# Local Mock Integration Runner v0.1

范围：**TEST_ONLY / MOCK_ONLY**。标准库实现，仅执行 M01、M02、M07、M08，不支持其他用例。本目录不是正式 Telemetry Schema，也不是张鹏飞正式算法或何宇轩生产 Validator/Edge Intake。

```text
Mock JSON
  ↓ Mock Loader（保留 source=MOCK 和原始输入）
  ↓ source / Schema / 类型 / 必须身份字段校验
  ├── REJECT → 保存错误路径与原始证据；两个 Handoff 均 NOT_CALLED
  └── ACCEPT
        ↓ TEST_ONLY snapshot ↔ payload 一致性检查
        ↓ 同一个只读 Validated Telemetry 对象
        ├── Risk Handoff → 原始值/null 投影与 TEST_ONLY sidecar
        └── Edge Handoff → 保留完整 payload 内容
```

两个 Handoff 是独立消费者，当前由同一进程依次调度，但不存在 Risk 输出转发给 Edge 的依赖。冻结一次的同一 payload 对象分别传入二者；深层不可变保护避免消费者篡改另一个消费者的数据。Risk 分支发生异常时，独立 Edge 分支仍可执行，整条本地检查记录失败。

## 运行

从仓库根目录，使用 Python 3.8 或以上：

```powershell
python -B experiments/mock_interface/runner/run_mock_integration.py
```

默认只执行 M01_NORMAL、M02_MISSING_SENSOR、M07_RISK_NOT_CALIBRATED、M08_INVALID_SCHEMA。可用重复的 `--case` 参数选择其中部分；不接受 M03/M03B/M04/M05/M06。不要把命令执行成功解释为正式三人联调完成。

相关小范围测试：

```powershell
python -B -m unittest discover -s experiments/mock_interface/runner -p test_runner.py -v
```

## 模块与接入点

| 文件 | 职责与入口 |
|---|---|
| mock_loader.py | `load_case(path)` 读取 JSON，保留精确输入 bytes/hash，拒绝重复键和非 JSON 常量；`check_snapshot()` 仅在格式校验通过后核对旁路映射。 |
| mock_v2_validator.py | `validate(payload)` 返回 ACCEPT/REJECT 和字段错误；**NOT_PRODUCTION_VALIDATOR**。 |
| risk_handoff.py | `receive_validated(payload, *, context)` 保留 identity、time、IMU、Soil、Risk、System；不计算风险。 |
| edge_handoff.py | `receive_validated(payload, *, context)` 独立接收同一 payload，保存未改变的内容；**NOT_PRODUCTION_EDGE_INTAKE**。 |
| run_mock_integration.py | `run_case()` 执行校验及两个消费者；`main()` 仅选择四个支持用例，记录真实观测和执行证据。 |
| test_runner.py | 检查共享只读对象、null 保留、M08 拦截顺序、来源隔离及消费者独立性。 |

Validator 针对当前直接 NODE v2 结构实施最小字段/类型检查：schema、身份、时间、双 IMU、Soil、Experiment、Risk、System。拒绝 bool 冒充整数、未知字段、无穷或 NaN；允许 null 缺测及 imu.valid=false，不决定是否 degraded、能否评分或评分多少。不是生产级完整验证器，也未实现 Topic/设备注册、LoRa 部分投影、去重、冲突、持久存储或完整时间/业务一致性策略。

M08 四条按实际字段错误拒绝，不自动修复；第 4 条 Soil 字符串类型错误在 sidecar 映射检查前报告。合法 M02 null 不构成格式错误。快照只作为 TEST_ONLY 对照，既不进入正式 payload，也不补齐生产接口。

Risk Handoff 的 projection 是本地交接证据，不是已冻结的张鹏飞输入契约；它没有湿度标定、滤波、窗口、贡献映射或 Missing Policy。三个 Risk 字段原样保留；正式算法步骤固定说明 `BLOCKED / NOT_INTEGRATED`。M07 未标定不归因于 G09，M02 的缺测也不由此处决定能否继续评分。

## 实际结果与状态边界

每次运行在 `experiments/mock_interface/results/local_<UTC>_<unique>/` 新建目录，不覆盖旧结果：

- `inputs/*.json`：执行时实际读取的原文件字节，含 M08 故意非法证据。
- `<case>.result.json`：输入文件/hash、执行时间、Runner 版本、Git commit/工作区状态、源码 hash、调用命令、预期/实际计数、逐条错误和 Handoff 输出。
- `summary.json`：该次运行的实际本地结果。

Runner 未提交时，Git commit 不能单独代表实现版本，因此同时记录全部 Runner 源码 SHA-256。保留源文件和输入 hash 才能复核相同实现及输入。

`LOCAL_RUNNER_PASS` 仅表示此次本地断言满足；`VALIDATOR_PASS` 表示实际格式校验结果符合预期（包含 M08 的正确拒绝）；`HANDOFF_PASS` 表示实际本地投影和保留检查满足。M08 的 Handoff 必须是 NOT_CALLED。accepted/rejected/call count 均从执行步骤计算，不抄录 case.expected_behavior。单元测试不生成联调结果文件。

正式 Feature/Risk 与三人代码接入仍为 BLOCKED / NOT_INTEGRATED；生产 Validator、Edge/Atlas/MQTT/Cloud 仍 NOT_IMPLEMENTED。G01～G09 全部 OPEN，Serializer / IdentityAllocator 和真实硬件均未因此实现或验证。

**本轮 Local Mock Runner 的通过不等于完整三人 Mock Integration PASS。**

## 下一步最小接入

张鹏飞：在 `risk_handoff.receive_validated(payload, *, context)` 接入自己审核的 v2-to-feature 适配层，明确 source/validity/时间旁路的测试限定；没有合法标定时仍保持 Risk null。不要把七字段演示 `evaluate(history)` 当 v2 入口，不伪造 UTC、湿度或历史窗口。

何宇轩：以 `mock_v2_validator.validate(payload)` 的返回边界接入自己实现/审核的 v2 校验器，并在 `edge_handoff.receive_validated(payload, *, context)` 接入自己的 Edge 接收层。训练契约 `validate_contract()` / `validate_handoff()` 不适用于这些 Telemetry 消息，不能直接替换。

两人真实代码接入后，再以同一输入 hash 和版本证据执行联调并记录状态；本 Runner 不自动将状态升级为三人联调通过。

## 队友真实代码边界接入 V0.1

Runner 实现版本 0.2.0 新增可选 `--teammates` 模式；不带参数仍是上述 Local 工作流。固定 commit、原始源码加载、实际函数调用及阻塞语义见 [TEAMMATE_INTEGRATION.md](TEAMMATE_INTEGRATION.md)。该模式不把训练契约校验当 Telemetry Validator，不把 RealAdapter 的阻塞异常当 Edge 接收成功。
