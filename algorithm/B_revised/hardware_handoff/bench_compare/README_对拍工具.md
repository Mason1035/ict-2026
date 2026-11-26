# B端隔离对拍准备工具（2026-11-26）

本工具仅生成TEST_ONLY合成输入/参考输出和检查外部结果，不执行GPIO、不加载设备配置、不实现AlarmTask、不代表物理标定或设备验收。reason_mask正式位号仍待三方会签，TEST_ONLY风险mask继续为null。

## 运行（Python3.11+，无第三方依赖）

PyCharm打开仓库，运行tool.py，参数按下面命令中generate或compare填写。所有输出目录/文件必须全新，脚本拒绝覆盖。

```powershell
python -B algorithm/B_revised/hardware_handoff/bench_compare/tool.py generate --output "E:\华为ict大赛\03_分析结果\2026-11-26_当前\TEST_ONLY对拍参考"
python -B algorithm/B_revised/hardware_handoff/bench_compare/tool.py compare --reference "E:\华为ict大赛\03_分析结果\2026-11-26_当前\TEST_ONLY对拍参考\expected.json" --actual "<A导出的独立结果JSON绝对路径>" --report "<E盘全新报告路径.json>"
```

生成inputs.json（合成配置及三场原始观测批次）、expected.json（case_id/risk/features投影）、binary64_boundaries.json（0/30/60/80/100及相邻double原语）、manifest.json。边界文件为独立分级原语输入，score_hex保留精确binary64；不是完整引擎观测批次。A应独立计算对应等级，边界等级必须严格一致，不能修改输入以迁就实现。

A实际结果须严格遵循expected.json的结构、status标识、case顺序及字段，不能额外加入GPIO/固件元数据；身份、固件/编译配置、输入哈希和测试日志另存sidecar。实际结果必须从独立实现导出，不复制expected文件。B工具不验证实板来源。实时引擎需逐场独立清空状态后处理同一inputs批次；不把低频Telemetry快照当完整IMU波形。

比较器对features/score采用待会签atol+rtol规则；等级、mask、null及结构严格一致，并检查score/level是否自洽。因此微小分数偏差跨等级边界仍失败。拒绝重复JSON键、NaN/Infinity；退出码0仅表示比较通过，1表示差异，其他异常也视为未通过。失败报告包含字段路径及输入文件哈希；不自动改参数、数据或评分结果。

现阶段只支持risk/features这一明确投影。五态Alarm、reason正式位、NVS掉电、按键事件与真实采样输入的完整对拍仍待会签及A的独立输出，不宣称本工具已覆盖。

## 已完成与下一步

已完成三类合成场景（正常、持续异常、缺测）、15个double边界输入、比较器和6项回归测试。参考自身与自身比较只用于软件冒烟检查，不能称板端通过。原数学向量、运行内核及DRAFT门禁不改。

A交回独立Host/ESP32结果及编译/固件/输入哈希后可立即跑对比；C回执和B本人确认后升级接口；11月28日计划补测到齐并验收后才生成真实参数配置及真实回放黄金向量。此前不启用正式风险。
