# 队员 B：等待真实数据前的独立软件工作

本轮日期 2026-10-13。可独立完成的本地工具现已实现，不再需要等 A/C 才能验证软件流程。
**软件检查通过不等于正式标定、现场告警或正式训练就绪。**

## 在你的电脑运行

PyCharm 打开 `E:\华为ict大赛\ict-2026\algorithm\B_revised`，选择解释器：

```text
E:\华为ict大赛\ict-2026\algorithm\B_revised\.venv\Scripts\python.exe
```

本地环境基于 Python 3.12.14，未下载第三方库。电脑当前 `python` 命令指向 3.8，不要据该命令推断
项目解释器版本。曾登记的 `E:\python\python.exe` 实际已不存在。`.venv` 依赖本机 Python 基础安装，
不是可发给队友的独立解释器；若基础安装被移除，应使用 Python 3.11+ 重建环境。

直接运行 `run_independent.py`，或者双击 `RUN_LOCAL.cmd`。PowerShell：

```powershell
& 'E:\华为ict大赛\ict-2026\algorithm\B_revised\.venv\Scripts\python.exe' -B -X utf8 'E:\华为ict大赛\ict-2026\algorithm\B_revised\run_independent.py'
```

脚本每次自动新建 `artifacts/local_runs/<UTC时间_随机编号>`，不覆盖旧记录。终端显示软件验证状态和
产物目录；运行目录不进入 Git。版本错误或测试失败会明确停止，不创建 PASS。

队友解压交接包后，用自己的 Python 3.11+ 在包目录运行 `python -B -X utf8 run_independent.py`。
如需双击 `.cmd`，先用自己的 Python 建环境：`python -m venv --without-pip .venv`。
本包没有额外依赖，不需要安装 requirements。工作目录无需硬编码为张鹏飞的机器路径。

## 你会得到什么

| 文件/目录 | 用途 |
|---|---|
| `tests.txt` | 本次真实执行的软件单测记录 |
| `config.TEST_ONLY.json` | 明确标注的演示参数；不能加载到真实节点 |
| 8 个场景目录 | 正常、异常、缺测、重复、失效恢复、重启、未来时间拒绝、过期 |
| `results.jsonl` | 逐输入行的 Feature/Risk 返回、原始输入哈希、阻塞原因 |
| `candidate_features.csv` | 候选特征审计表；空值留空，不是正式模型 X |
| `feature_table_contract.json` | 审计列说明；身份和 Risk 输出不可自动当模型输入 |
| `evaluation.TEST_ONLY.json` | 归一化、混淆矩阵、PR、事件评价的软件示例，不是模型真实准确率 |
| `handoff_preflight.json` | 空交接模板的检查结果，应为 WAITING_FOR_A |
| `summary.json` / `manifest.json` | 全部场景检查与文件哈希，正式 readiness 明确为 false |

输入、配置原始文件原样保存；每次回放记录算法/工具源码 SHA-256。运行耗时只表示这台电脑的离线参考
开销，不算 ESP32/Atlas 的 20 Hz 实时或续航验收。8 个场景不模拟真实通信、持久化补传回执或完整飞控。

## 新增独立工具

### 1. 文件回放与导出

`telemetry_v2_intake/replay.py` 接收 JSONL，每行恰好 `{payload, context}`；payload 必须先经过上游 v2
Validator。本脚本不是新的生产 Validator，不凭声明字段证明 Schema 已验证。`context.runtime_input`
沿用 B 的原始采样批次提案，见 `telemetry_v2_intake/RUNTIME_HANDOFF.md`。默认 A 入口兼容不变。

```powershell
# 在 B_revised 目录；以下三处路径需替换为已校验输入、完整配置、新输出目录
python -B -X utf8 telemetry_v2_intake/replay.py --input <输入.jsonl> --config <配置.json> --output <新目录>
python -B -X utf8 telemetry_v2_intake/replay.py --verify <产物目录>
```

JSON 重复字段、NaN/Inf、已有输出目录均拒绝；未来/冲突/乱序会留下明确拒绝记录，不污染状态。
`--verify` 仅证明文件完整性，不能证明物理正确性。若回放中出现拒绝，CLI 退出 2；故障场景中预期拒绝
由上层场景断言单独核对，不能把“接口返回了结果”自动当作 PASS。

### 2. Train-only 归一化与防泄漏

`evaluation/normalization.py` 的 `fit_real_train(records, ordered_features=...)` 必须显式给列顺序，
不自动选择 CSV 数值列。输入记录为 `{run_id,parent_run,split,is_synthetic,values,valid}`；values/valid
均为按显式特征名索引的字典。先检查母 run 跨分区、同一 run 的来源冲突，再只用真实 Train 有效值
拟合均值和总体标准差；Validation/Test/Synthetic 不参与拟合。此处“真实”依赖交接元数据，工具不鉴定来源。

不允许身份、标签、时间到事件、Risk 输出进入 X。缺测保留 null/mask；常量列 scale=1 并明确标记；
整列无有效 Train 值拒绝拟合。`transform` 使用已记录的统计量/哈希，不在目标数据上重拟合。
正式 ordered_features、单位/shape、mask 是否进入模型和 C 的最终缺测输入处理仍等待实测及 B/C 确认。

### 3. 指标工具

`evaluation/metrics.py` 提供纯函数，不训练模型或生成真值：

- classification_report：显式实验类别；unknown 真值另计，未知预测保留 UNSCORED，计入漏评/FN；同时报告
  覆盖率、全有标签样本准确率和仅已评分准确率，避免删除无法评分样本造成高分假象。
- precision_recall_curve：二元 0/1/null 真值、有限分数；同分阈值整体处理；缺失正类分数仍计入 recall 分母；
  AP 用 PR 阶梯面积，缺失正类不能自动得到满分。正类定义及模型概率语义须正式契约明确。
- event_report：显式事件真值、一次触发警报、run/boot 和观察区间。按事件时间先后匹配最早未用警报，
  一对一，不跨未观察间隔；提前量正值=提前，负值=迟到。剩余触发计为该策略下误报，并除以观察小时。

分母为空返回 null；macro-F1 明确列出参与类，不能暗含全部类别。事件匹配规则/早晚窗/报警合并与
解除策略是调用方显式参数，尚非团队正式验收协议。重复持续高分需 A 的警报事件化处理，不能每帧记警报。
没有独立真实 Test 时这些工具只验证口径，不发布泛化指标。

### 4. A 数据交接预检

`data_intake/A_RUN_HANDOFF_DRAFT.json` 是待确认的索引模板，不改变 CSV/v2。文件引用用同一包内的相对
路径和 SHA-256：原始 CSV、逐路实际采样时间/row 映射、validity/错误、传感器校准、实验操作日志、
人工/影像标签证据。预检读取原件不覆盖，也不从 raw 非空推断有效。

```powershell
python -B -X utf8 data_intake/check_handoff.py <交接目录/handoff.json> --output <新报告.json>
```

该工具检查引用存在、文件非空、路径范围、哈希和现有 20 列 CSV/run 一致性。侧表内部格式尚未由团队
冻结，不能仅因它存在就批准内容。返回 MATERIALS_PRESENT_REVIEW_REQUIRED 也不是 Real Data Ready。
缺材料返回 WAITING_FOR_A；冲突/哈希错误返回 INVALID_HANDOFF。

### 5. 软件交接 ZIP

```powershell
python -B -X utf8 local_tools/build_package.py --output <新的B软件交接.zip>
python -B -X utf8 local_tools/build_package.py --verify <B软件交接.zip>
```

包内只放 B 当前工具、必要候选函数、不可加载配置模板、测试和 MIT 许可证；不放 `.venv`、原始真实
数据、密钥、PDF、A/C 源码、旧演示模型或运行二进制。`PACKAGE_MANIFEST.json` 记录各文件哈希及 Git 来源。
这是 B 软件参考包，不是整套可部署华为云应用或硬件固件。原有规则蒸馏路径在仓库仍保留，不重复入本包。

## 现在结束的独立部分与后续接力

已完成：参数化 Feature/Risk、软件边界测试、8 场景回放/审计、归一化与泄漏检查、指标计算、
交接材料预检、可重复本地运行、独立打包。共享权重/等级边界保留，正式配置/Training Contract 未被补成假值。

继续需要真实输入的部分：

1. A：双 IMU 和三 Soil 原始实验及重复 run，实际时刻/validity、基线/干湿标定、采集和坐标版本、标签证据。
2. B：拿到上述原件后核验质量、按独立 run 划分、仅用 Train 选滤波/窗口/贡献参数，冻结 Feature/Label/Window/
   Split/Normalization/Metrics/Synthetic Constraints，做真实误报/漏报/鲁棒性评价。
3. A/B/C：确认内部批次转换、reason bit、设备数值容差、报警锁存/解除与现场联调。没有这些记录不启用正式配置。
4. C：模型/ONNX 的特征契约、训练版本和 Real-only/Real+Synthetic 同一独立 Test 的评价；Edge、数据库、云部署归 C。

当前可以把软件包交给队友做接口和软件回放验证；这不会替代上述数据交接。本轮是 Codex 本地实现，
没有冒充 CodeArts 使用或开通付费华为云资源。
