# 智哨防灾：队员 B → A 算法接口预交接包

状态：`INTERFACE_DRAFT_DO_NOT_DEPLOY`（2026-10-02）。这是供 A 设计固件接口、离线回放和联调的**预交接**，不是经实测冻结的 Risk 算法。权威顺序：`00_TEAM_SHARED_CONTRACT.pdf` → `01_硬件嵌入式与系统负责人开发文档.pdf` → 本包。若有冲突，以 00 为准并由三方评审。旧七字段 `evaluate(history)`、规则蒸馏 TEST_ONLY CSV 不是本项目正式设备接口。

## A 现在可以做

1. 按 `B_TO_A_INTERFACE_DRAFT.md` 设计采样快照、时间/validity、Feature Engine、Risk Runtime、配置校验与故障输出之间的**模块边界**；公式中的未定参数保持显式未配置状态。
2. 用 `candidate_features/reference.py` 和 `candidate_features/risk_math.py` 对照纯数学实现；运行 `python run_vectors.py` 复现本包 `golden_vectors.TEST_ONLY.json`。这些向量只验证数学和四级分数边界，不代表真实传感器阈值。
3. 用 `A_TO_B_DATA_HANDOFF.md` 准备第一批五类实验 run 的 CSV、时间/有效性侧表、校准与操作证据。可用 `data_intake/check_experiment_csv.py` 只读初检 CSV，过检不代表已校准。
4. 等 B 基于真实 run 发布有版本、有哈希的正式窗口、滤波、贡献曲线、缺测/滞回、`reason_mask` 位表和可加载 `risk_config` 后，再把评分接入正式 Alarm；未校准时可采样和显示特征，但 `sensor_score/level/reason_mask` 为 `null`，另报未标定故障。隔离的 HIL 测试注入必须显著标记。

## 包内文件

- `B_TO_A_INTERFACE_DRAFT.md`：字段、时间、有效性、计算与状态边界。
- `RISK_CONFIG_DRAFT_NOT_LOADABLE.json`：含未决 `null` 的设计讨论模板，**固件必须拒绝加载**。
- `golden_vectors.TEST_ONLY.json`、`run_vectors.py`：可复现数学例子；板端数值容差还须量化评审。
- `A_TO_B_DATA_HANDOFF.md`：原始实验交接和首批 run 所需证据。
- `candidate_features/`：B 的纯数学源码；`data_intake/`：CSV 只读初检。
- 两份 PDF：共享契约与 A 负责人文档；`MANIFEST.json`：包内文件 SHA-256。

本包不包含采购建议、GPIO 新分配、LoRa 字节布局或可用的危险阈值。A 的网络、存储、Alarm 和 HIL 仍按两份权威 PDF 实现；C 的 v2 validator、Topic/命令细节和 Atlas 持久化回执仍需 C 交付。
