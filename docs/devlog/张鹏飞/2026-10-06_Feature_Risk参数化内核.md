# 2026-10-06：B Feature / Risk 参数化内核

依据用户截图，继续推进 Telemetry v2 → Feature 映射 → calibration/baseline/window → Missing Policy → contribution → Risk。
本次开始本分支干净，HEAD 为 568e229；fetch 后 A 最新接口联调为 01093f5，C 为 7ada9fb。
A 最新记录证明旧 B 接收边界真实触达，但仍未校准。可见目录中未收到 A 实测标定和原始波形。

实际工作：新增配置验证和哈希、原始批次映射、候选因果低通和预热、基线相对倾角、动态振动 RMS、
逐探针相对指数、时间窗口和增长斜率、保守缺测阻塞、四路折线贡献及共享权重 Risk。
加载失败保留旧配置/历史；分段切换重置；重复/冲突/乱序不污染窗口；默认入口保持兼容。

实现、演示与交接均在 `algorithm/B_revised/telemetry_v2_intake`。
正式 Draft 不可加载；没有真实 CALIBRATED 参数、正式 bit 位表、现场阈值或训练模型。
CALIBRATED 代码分支单测使用虚拟引用和合成数据，只验证软件门禁，不能算真实验收。

真实运行记录：

- `python -B -m unittest discover -s algorithm/B_revised -t algorithm/B_revised -p test_*.py -v`：50 项通过，其中本轮 21 项。
- `python -B -X utf8 algorithm/B_revised/telemetry_v2_intake/verify_a_mock.py`：A ref 01093f5 的 M01/M02/M07 接受并各调用 B 一次；M08 拒绝四条且零调用。
- TEST_ONLY 回放：静止稳定 score=5/NORMAL；异常 score≈75.478/WARNING；缺测全 null。

下一步需要 A 的原始高频实验、逐路时刻/validity、基线和干湿标定；B 据此选正式参数并评估；
A/B/C 会签内部批次/bit/板端误差和报警策略。C 推进持久化/下游，不由本轮代做。
本轮是 Codex 本地实现，不冒充 CodeArts 或真实硬件测试。
