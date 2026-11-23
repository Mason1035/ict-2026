# 智哨防灾：队员 B 算法交付

**仅用于演示，未验证真实灾害预测能力。** `normal` 表示未触发当前规则，不等于现场安全。

当前团队职责与 C 交接说明见上一级适配目录 [README](../README.md) 和
[HANDOFF_TO_C](../docs/HANDOFF_TO_C.md)。本包只负责演示 Risk Algorithm，
不定义正式训练 Feature/Label/Window/Split。代码与文档由 Codex 生成，不能作为码道 CodeArts 已实际使用的证据。

## 快速运行

无第三方依赖。已验证 Python 3.13.12；其他版本尚未测试。

```powershell
Set-Location -LiteralPath 'E:\华为ict大赛\队员B_算法开发交付'
python -X utf8 -B examples.py
python -X utf8 -B -m unittest discover -s tests -v
```

示例依次返回 normal、warning、unknown。JSON 输入/输出快照在 sample_data.json 与 sample_outputs.json；测试实录在 VALIDATION.md。

## 调用

```python
from risk_algorithm import evaluate, RiskEvaluator

result = evaluate(history)
# 结果恰含 risk_level、reasons、missing_fields

evaluator = RiskEvaluator()  # 或传入配置 JSON 路径
result = evaluator.evaluate(history)
version = evaluator.algorithm_version  # 另存于应用元数据
```

模块与 demo_rules.json 必须一起部署。输入只能是同节点七字段采样列表，不要传 ORM 对象、风险结果或数据库元数据。函数不修改输入、不访问网络、不写数据库。

## 不可省略的调用条件

- 每次必须带固定基线和最新判断段，默认基线为序号 1～3，当前窗口为最新 3 点且不得与基线重叠。
- 两段各要求连续序号、间隔不超过 20 秒、持续至少 20 秒；最低六个不同样本。
- 两段湿度、倾角缺测则 unknown；电量缺测仅产生设备说明和 missing_fields。
- 同键相同内容去重；同键不同内容、混合节点、混合来源、时钟逆序均 unknown。
- 实例启动时读配置，修改配置后重新创建实例；配置无效会抛出异常，不能按 normal 处理。
- 算法无系统时钟依赖，不判断数据是否陈旧或通知是否送达。
- 三个输出字段不容纳版本等元数据，由应用独立存储。

## 规则说明

湿度趋势同时检查逐点不下降、净增幅和回归斜率；倾角检查相对固定中位数基线的同方向持续偏离。湿度单独触发最高 attention；倾角持续较大偏离，或倾角关注与较强湿度趋势同时成立时 warning。所有阈值在 demo_rules.json，均属演示参数。

## 文件与许可

requirements.txt 明确无第三方运行依赖。LICENSE 提供 MIT 文本；团队开源前核对整体项目许可证、依赖与素材权属。不要提交密钥或账号凭据。后续码道实际操作证据应单独如实保存。
