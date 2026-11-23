# 软件验收补充 2026年11月23日

回应C的反馈：软件测试通过不等于NODE01实板、链路或云部署验收。本轮不删分支、不改固件、不变更现场，也不把人工固件声明改称设备认证。

## 修复与联合回归

- Windows中文路径图片读取失败属于真实软件缺陷：改用Path读取字节再交OpenCV解码，新增含中文和空格目录的当前图/参考图回归。
- 部分SQLite测试只退出事务却未关闭连接，导致Windows清理失败：明确关闭连接并保留事务提交语义。
- POSIX bash启动器测试在Windows上明确跳过，在Linux CI中保留执行，不把Windows bash兼容层当作Linux。
- 增加会话声明冲突锁定：同一站点/设备/boot中，固件声明改变后，本会话相对土壤指标保持空值；重启服务不解除，只有新的boot重新建立独立状态。填写哈希不能追认旧会话。
- 重复消息不会重标记已有结果，旧输入不因补填固件声明自动变成已核验。正式Telemetry、原始risk、VWC和告警资格保持原语义。
- 参数相符增加独立parameter_match；hardware_verified始终false，verification_status明确UNVERIFIED_OPERATOR_DECLARATION。输出保留会话身份和一致性状态。applicable只表示研究换算可用条件，不是实板验收。

## 本地证据

修复后Windows完整后端：276 passed、21 skipped、0 failed。前端类型检查和生产构建通过。原JUnit文件位于03_分析结果/2026-11-23_当前/三路标定应用集成/backend-acceptance-final.xml，详细日志位于07_整理记录/软件验收。

上述21项跳过包含Linux启动脚本和外部真实数据输入；本轮另行用现有数据.zip准备四场原始三件套，独立运行真实回放测试。原始包保持不变，来源哈希另存。未提供的历史故障样本不伪造。

## 远端持续集成

.github/workflows/software-acceptance.yml在main、张鹏飞分支push以及PR触发，可人工重跑：Ubuntu/Windows完整后端、算法软件测试、Linux前端构建。上传JUnit、提交哈希、Python版本及pip freeze，便于复核同一次提交。CI使用软件夹具，外部私有数据缺失时如实跳过，不声称覆盖实板。

只有GitHub Actions实际运行成功才可称远端通过；新增工作流文件或推送成功本身不是通过记录。运行状态和链接应以GitHub实际结果为准。

## 下一步仍需A与C

核对实板MAC/设备身份、实际固件ELF、单设备Topic、本次boot_id及原始采样日志，形成带时间和操作者的实板联调记录；然后由C安排部署。连接器填写哈希不能替代这些证据。土样VWC、独立测角、新干土基线、雨强与正式阈值仍受原验收门槛约束。
