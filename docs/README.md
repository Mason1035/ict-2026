# 智哨防灾工程文档（docs）

本目录保存“智哨防灾”项目的工程执行资料、过程记录与可复现证据。

## 权威顺序
- `00_TEAM_SHARED_CONTRACT` 是项目最高事实源（Single Source of Truth）。
- `docs/` 不得私自覆盖已冻结的架构、角色、接口、GPIO、协议名称等。
- 如需修改 FROZEN 内容，应先团队评审并更新 `00_TEAM_SHARED_CONTRACT`，再同步修改代码、协议、接线和测试记录。

## 目录
- `decisions/`：重要工程决策（ADR）。
- `devlog/`：A/B/C 三名成员的开发日志。
- `experiments/`：实验方案、run 计划、元数据与结果索引。
- `protocols/`：正式接口、消息、协议与 Schema。
- `reference/`：负责人开发文档、采购表、基线 PDF 和参考资料。
- `test_records/`：硬件、固件、算法、链路与系统联调测试记录。
- `wiring/`：GPIO、总线、电气连接与接线图。

## 基本规则
1. 开发日志不是正式协议。
2. 失败实验和失败测试也要保留。
3. “完成”必须有测试证据。
4. Mock、Synthetic、沙盘、真实硬件和真实山区数据必须区分。
5. 重要产物尽量记录版本、Commit、配置版本、硬件版本和文件 Hash。
6. 未验证内容继续标记为 TODO / TBD，不包装成已完成。
