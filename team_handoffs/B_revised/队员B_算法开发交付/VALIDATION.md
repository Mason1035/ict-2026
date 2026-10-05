# 实际验证记录

- 验证时间（UTC）：2026-09-23T14:12:01.742616+00:00
- Python：3.13.12
- 系统：Windows 11
- 验证工具：Codex 调用本地 Python；不是码道 CodeArts 操作记录。
- 命令：`python -X utf8 -B -m unittest discover -s tests -v`
- 结果：24 项测试全部通过，退出码 0。
- 完整测试输出：TEST_RESULTS.txt。
- 数据协议校验：三个场景共 18 条样本均恰含约定七字段；三个结果均恰含输出三字段。
- 实际样例结果：normal → normal；abnormal → warning；missing → unknown。
- sample_data.json 和 sample_outputs.json 由本次模块实际运行生成。

## 验证范围

验证演示规则、输入规范、去重、冲突、乱序、窗口连续性、固定基线、缺测、电量与风险分离、阈值边界和补传行为。

未验证真实传感器、现场灾害识别能力、前后端联调、RDS/Redis、云部署、真实无人机或通知送达。
测试通过仅表示代码满足当前演示规则，不能作为预测准确率或现场安全证明。
