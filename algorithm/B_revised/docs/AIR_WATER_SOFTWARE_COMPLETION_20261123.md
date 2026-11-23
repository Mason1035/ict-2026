# 新标定现有材料的软件收尾

本轮在离线换算后继续完成来源比较、独立结果适配器和土样汇总核验。没有修改冻结Telemetry、硬件、正式风险或阈值。

## 可调用接口

```python
from data_intake.air_water_adapter import evaluate_observation, load_parameters
p = load_parameters()
result = evaluate_observation(channel=2, raw=16000, valid=True,
    firmware_sha256=p['firmware_elf_sha256'])
```

此处raw=16000仅是调用示例，不能作为实测记录。实际调用必须传入原始记录的固件哈希，不可为了启用换算把期望哈希当实际固件填写。返回独立RESEARCH_ONLY结果，包含w_rel_pct、单位、版本、质量标记；vwc_pct始终None，risk_eligible和fusion_eligible始终false。不适用固件、无效观测和缺测返回空值及原因。参数变更需重新审计。

## 汇总表发现与处理

原包`soil_calibration_summary.csv`表头为36列，第2行AIR与第3行WATER仅35列。直接DictReader读取会导致数值错位。本轮按实际列数隔离这两行，没有改写或推测补齐原件。端点原始CSV和独立参数表已由前一工具核对一致，不因汇总表错误否定原始端点。

其余6场土样的18个通道汇总已根据原件重算：4320行，样本数、中位数、极值与相对指标两位小数均匹配。包括此前未接入的W01串口提取表；其中seq明确标记为串口记录序号，不冒充Telemetry序号。跨固件值仅是诊断参考投影，不批准作为运行时标定；全部问题土样继续排除拟合与训练。

```powershell
python -B -m data_intake.verify_air_water_summary --archive 'E:\华为ict大赛\NODE01_标定数据合集_20261122.zip' --output 'E:\华为ict大赛\八场核验重跑_01'
python -B -m unittest discover -s data_intake -t . -p 'test_*.py'
```

存在问题行时CLI退出码为1，是数据核验未全通过的明确结果，不是程序崩溃；报告仍会保存有效场次与问题清单。输出目录必须全新。权威新报告为本轮`标定八场核验_2026-11-23_v2`；早期同名无v2目录是列数门禁修正前的中间结果，不能当验收结论。

## 当前停止点

能独立验证的来源、换算、缺测/版本隔离和汇总处理已完成。A需修正源汇总表的结构或提供原始生成程序，不能猜测补数。正式集成接口、AIN2用途与适用范围仍须三方确认。缺独立测角、土样真值、新干土基线、泵重复与受雨面积、13场历史身份及适用依据的任务继续阻塞，不拟合或发布数值阈值。
