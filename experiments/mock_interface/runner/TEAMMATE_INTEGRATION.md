# 真实队友代码边界接入 V0.1

日期：2026-10-04。**TEST_ONLY / INTEGRATION_ADAPTER**。这是运行代码与记录实际边界的接入，不是正式 Risk、生产 Validator 或 Edge Intake。

## 版本与最小引入方式

开始时工作区干净，李青原与 origin/李青原 均为 `d0c9edb3baa747700ba1e7a0a901a3fcb64bab00`；main 为 `3f45c847b9b46720fc06b1483a5f3b78ee599baf`。读取的本地远程跟踪版本：

| 负责人 | 来源 | 固定 commit |
|---|---|---|
| 张鹏飞 | origin/张鹏飞 | `4d635759f4b9e222609938ef5e6d829463d40024` |
| 何宇轩 | origin/何宇轩 | `019a03a53336790a1439485754afdaaf3c34c9c1` |

本轮未 fetch，不声称已查询 GitHub 最新远端。未切换、合并分支或改写队友源码。`teammate_sources.json` 固定上述 commit、最小模块集合、Git blob ID 和 SHA-256；`teammate_source.py` 通过只读 `git show <commit>:<path>` 获取源码，核对双重哈希后原字节编译到内存中。保留原模块导入名，并在调用后清理隔离命名空间；遇到已有同名模块拒绝覆盖，不退回未知环境包。

依赖 Python 3.10+ 和 Git，本次使用 Python 3.12。无需第三方包。需保留这些 commit 的本地 Git 对象；缺少对象、哈希不符或接口变化均记录 BLOCKED/FAIL，不自动取最新代码或使用替代实现。该机制加载的是团队已审查源码，不接受外部任意模块路径。

## 实际数据流

```text
Mock JSON → Loader → 现有 TEST_ONLY Validator
                       ├─ REJECT → 两个方向 NOT_CALLED
                       └─ ACCEPT → TEST_ONLY 快照一致性检查
                                       ↓ 同一个只读 payload
                           ┌───────────┴───────────┐
                       Zhang Adapter           He Adapter
                           ↓                       ↓
                 张鹏飞真实候选函数       何宇轩真实 RealAdapter.to_dataset
                 缺必要参数返回 None       实际抛出 ContractNotReadyError
                 RISK_EXECUTION_BLOCKED    INTERFACE_MISMATCH
                                          EDGE_INTAKE_NOT_IMPLEMENTED
```

保留现有本地 Handoff 的数据保存断言，但每条结果另外记录 `zhang_adapter_result` / `he_adapter_result`，本地 ACCEPTED 不代表队友接收成功。两个方向消费同一只读 payload；He Adapter 不依赖 Zhang 的返回结果。

## 张鹏飞方向

实际调用 `algorithm/B_revised/candidate_features/reference.py`：

- `relative_wetness_index(raw, dry_raw, wet_raw)`：三路 raw 直接来自 v2；未提供干湿标定时两项参数显式为 None，调用真实函数的缺参返回路径。M02 middle_raw 仍为 None。返回 None 不是推断传感器故障，也不是已算出湿度。
- `dual_imu_tilt_difference_deg(top, toe)`：使用现有 v2 两路 tilt_deg；当前都为 None，真实函数返回 None，不能解读为“不同意”或“角度差为 0”。

每条合法消息实际进入四次原始函数。Adapter 不实现数学公式、不造基线、动态加速度、干湿映射或窗口。未调用正式 Risk scorer；Risk 三字段原样保留，`formal_risk_executed=false`、`risk_score_produced=false`，状态 RISK_EXECUTION_BLOCKED。

已核对的其他接口仍不能直接投入 v2：`risk_math.sensor_score()` 要求已验证贡献值和 bonus；`causal_window.CausalObservationBuffer` 要求明确窗口/年龄参数；演示 `队员B_算法开发交付/risk_algorithm.py::evaluate(history)` 要求七字段 UTC 历史（实际路径不在 candidate_features）；`data_intake/check_experiment_csv.py::inspect_csv()` 接收实验 CSV。这里不为满足它们制造数据。

M07 未标定/无合法 Risk 结果不直接归因于 G09；G09 仍单独保留为缺测/无效输入策略未定。M02 的 Unavailable 只保留在 TEST_ONLY sidecar，不解决 G03。

## 何宇轩方向

实际调用 `ai_training/src/ai_training/adapters/real.py::RealAdapter.to_dataset(artifact=payload, contract=None)`，并捕获其原始 `ContractNotReadyError`。

这是**已知接口不匹配的负向能力探测**：输入就是同一只读 v2 payload，没有把它伪造成训练产物，没有伪造 TrainingContract。该函数当前不读取输入而直接抛出异常，所以只能证明进入真实方法帧，不能证明 payload 被理解或接收。

结果同时表达 `reach_status=REAL_CODE_REACHED`、`adapter_status=INTERFACE_MISMATCH`、`execution_status=EDGE_INTAKE_NOT_IMPLEMENTED`、`telemetry_accepted_by_teammate=false`。保存实际异常类型和文本。此 commit 未发现真正 Telemetry/Edge Intake 入口；`validate_contract()` 是训练契约校验，`validate_b_handoff()` / `BRuleFixtureReader` 是训练产物交接，本轮不把它们当 Telemetry Validator 或 Edge 使用。

## 执行与证据

从仓库根目录运行：

```powershell
python -B experiments/mock_interface/runner/run_mock_integration.py --teammates
python -B -m unittest discover -s experiments/mock_interface/runner -p "test_*.py" -v
```

不带 `--teammates` 时保留原 Local Runner 行为。新模式只执行 M01/M02/M07/M08，并新建 `results/teammate_<UTC>_<unique>/`；不覆盖旧结果。异常/阻塞保留在逐例报告，M08 四条先拒绝，不加载或调用队友业务模块。

每次真实调用记录目标、来源分支/commit/module/function/行号/blob/hash、参数、实际返回或异常。`real_code_called` 来自 Python profile 观察到对应原始函数代码对象的 call 事件；导入模块或 adapter 自己运行不算触达。全套依赖来源 manifest 随执行元数据记录，Runner 源码 hash 包含 adapter、测试和 manifest。

LOCAL_RUNNER_PASS 仅说明本地证据断言匹配：包括张鹏飞的真实缺参返回和何宇轩的真实阻塞异常；它不表示 Risk/Edge 功能已经完成。真实函数调用次数从实际 call 记录计算；M08 两个方向均为 0。

所有 G01～G09 保持 OPEN；不改 fixture、Protocol/Review、正式 v2、C++、阈值或 Missing Policy。**THREE_PERSON_MOCK_INTEGRATION_PASS = NO**，完整三人接入仍 BLOCKED / NOT_INTEGRATED。

## 最小下一步

- 张鹏飞：提供自己审核的 v2 接收/特征适配入口及未标定时的明确结果；正式评分另需合法标定/贡献映射与缺测策略。不要求先制造评分结果。
- 何宇轩：提供真实 v2 校验和 Edge 接收函数；当前训练 RealAdapter 不能代替 Edge。先实现离线接收即可，不必接 Atlas/MQTT/Cloud。
- 李青原：沿用现有 v2 和两个分叉；待队友新入口可用后审核新 commit，再更新 provenance 和 adapter 调用。**NO PROTOCOL CHANGE REQUIRED**。
