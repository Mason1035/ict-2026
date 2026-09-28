# B Formal Training Contract Draft

Contract ID: B_FORMAL_TRAINING_CONTRACT  
Contract Version: 0.1-draft  
Status: DRAFT

此文档与同名 JSON 共同表示 **NOT_READY_FOR_FORMAL_TRAINING**。JSON 是程序读取的 Draft；
`training_ready=false`。填入零散字段或改 status 字符串不能使它变成已批准正式契约；需 B 版本化
评审、A 真实交接、C 的新版本适配器及回归测试。

00 共享契约的实验平台是 2×ICM-42688-P（top/toe）和 3×Soil（top/middle/toe）。
`tilt`、`tilt_rate`、`vibration_rms`、`moisture`、`moisture_growth`、双 IMU 一致性与
空间 Soil 差异只是 **candidate_feature_families / PENDING_FORMALIZATION**，绝不是
`ordered_features`。正式特征、单位、dtype、mask、坐标、对齐/年龄、窗口长度/步长/预热/缺口/
padding、标签、run/parent_run split manifest、归一化、指标、Synthetic Constraints 均未冻结。

当前确定的边界是因果窗口、Test 不参与拟合/调参、来源字段不进 X、同 run/parent_run 分组。
具体计算与异常处理仍由 B 冻结；真实传感器值、标定版本及 validity 需要 A 交接。
所有现实传感器/物理阈值和转换参数为 **TODO_CALIBRATION**，不得把 demo_rules 数值迁入正式契约。

Validator 的 `unresolved_fields` 可由 C 的接入流程自动读取；返回 WAITING_FOR_A 与 WAITING_FOR_B。
正式 Real-only 与 Real+Synthetic 比较需同一独立 Real Test，本 Draft 没有提供该 manifest。
