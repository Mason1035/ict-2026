# 20261124新土VWC试用接入

本轮只新增独立离线试用模块，不改冻结Telemetry、正式风险、固件或现场。入口为data_intake/vwc_trial_20261124.py，真实包生成参数保存在同名.parameters.json。

Python3.11+标准库，PyCharm工作目录algorithm/B_revised：

```powershell
python -B -m data_intake.vwc_trial_20261124 --archive 'E:\华为ict大赛\01_原始数据\NODE01_标定数据合集_20261124.zip' --output 'E:\华为ict大赛\03_分析结果\2026-11-25_当前\VWC重跑_01'
python -B -m unittest discover -s data_intake -t . -p 'test_*.py'
```

输出目录必须全新。程序直接读取ZIP，不执行包内脚本或固件。先验证ZIP CRC、文件唯一性、表格列数、来源哈希、每路样本数、中位数、极值及单调时间，再核对9个插值节点。

## 调用与保存

`from data_intake.vwc_trial_20261124 import evaluate_trial`，调用`evaluate_trial(channel,soil_raw)`。

结果分别包含soil_raw、channel、w_rel_pct、w_rel_calibration_version、vwc_est_pct、vwc_calibration_version、in_range、flags。缺测返回None，非法/非有限ADC拒绝。VWC按两段线性插值，超范围按指南截断至0或20.9，并明确标为越界；该截断值不能冒充测量精度。W_rel仅是Air-Water刻度，不替代VWC。

派生JSONL还保留来源文件、run_id、串口原始序号、设备单调采样时间、原码、有效状态和选样角色。串口seq不是Telemetry seq。原始记录不改写，可更换版本后重算。JSONL为独立派生结果，C如接入应用应另存结果表/sidecar，不能把试用vwc_est_pct直接写入旧正式VWC或risk。

## 已核验

5场各720行，共3600行；15个通道哈希、样本数、中位数和极值匹配。9节点选样遵守AIN0/1第一湿点R01、AIN2第一湿点R03；R02及未选通道仍回算但标记DIAGNOSTIC_NOT_FIT_INPUT。节点重现是拟合内核验，不是独立精度。

水泵按原表复核质量/5秒得到的流量，保留OFF/REJECTED/NOT_USED/BACKUP/ACTIVE角色；不对缺档插值，不拟合未经约定的新曲线。0.0651m²是估计喷淋口径，0.1152m²为顶部面积口径；两种等效雨强分别记录，均不代表现场雨强验证，仍缺五档重复长时称重。

## 必须保留的限制

- 干土0%是假设；15.7/20.9为条件估计，体积58.6685cm³也为估计，没有独立验证误差。
- 干点约3cm、湿点约2cm，土壤接触和深度不同；不能宣传覆盖其他土类和装填条件。
- 第二湿点R05使用f17ee9串口固件，前点与Air-Water采用85ebda R4。离线投影标为试用，不自动扩大应用端的固件白名单；跨固件适用性由A/C复核。
- 第二湿点测后少1.4g，可能约2.4个百分点影响；不删点、不反调阈值。
- 120秒干土采集不等同原要求>=300秒装回系统的新干土静态基线。
- IMU原件和安装条件、独立角度验证继续按原门槛；土壤新包不自动证明IMU正式验收。

给A：补独立中间验证点、稳定深度/接触、质量和体积依据、原始SD补件及跨固件说明。给C：按独立结果字段集成、保留原码与版本、区分越界和缺测；不要启用正式风险阈值或宣称实板链路验收通过。
