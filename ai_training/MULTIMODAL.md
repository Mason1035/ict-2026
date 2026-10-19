# 土壤模型、运动模型与规则融合

2026-10-19 新增 `multimodal` 研究入口。当前没有自采沙盘 CSV，因此实际训练的是两个
**下一次观测预测模型**，用来学习各分支的序列变化；不是 NORMAL/RAIN/SLIP 分类器。
正式 B Contract、原始20列 CSV、Telemetry、后台 Risk Engine 和原 Trainer 的门禁均不变。

```text
LISA TDR含水率 ──> 单通道共享土壤预测器 ──> 本地标定/状态提取 ──┐
                                                              ├─> 规则证据融合
Smartstone六轴 ──> 六通道运动预测器 ─────> 本地标定/状态提取 ──┘
```

土壤模型对每个传感器分别应用；不能把上/中/下不同时间的值拼成同步输入。
未来一枚或两枚 IMU 可分别应用同类运动特征方法；双位置关系需用本地配对实验验证。
两个模型的输出含义和单位不同，不直接平均成滑坡概率。

## 实际模型与数据

模型采用 NumPy 加权岭回归：输入当前值和历史增量，预测下一次**记录到的观测**相对当前值的增量。
土壤使用4次历史观测，运动使用8次。这些是可修改的研究超参数，不是正式采样率、危险阈值或预测提前量。
原始时间间隔保留，但单位/间隔未统一，因此不声称预测未来若干秒。
每个实验组的总训练权重相同，避免长记录支配拟合；标准化仅从训练窗口估计。

| 分支 | 使用的数据 | 单位及评价边界 |
|---|---|---|
| 土壤 | LISA三个位置的TDR，位置各自成序列 | VWC体积比。按实验日期分组，并合并明确连续试验18–22；仅Validation选正则化，显式参数才释放Test。未知跨日期母样关系仍是限制。 |
| 运动 | Smartstone四颗石子的原始MAT六轴数组 | 原生数值/时间码，未猜测校准阶段、g、°/s或UTC。全部属于一个实验，固定正则化，仅拟合；Validation/Test为空。 |

LISA坏时间、重复时间、无效数值的处理和源记录索引在report中记录；不覆盖源文件。
没有借用裂缝时刻作为滑移标签，没有将静止或喷水条件自动标为安全/滑移。
南科大、Hollin Hill本版不混入：前者电压/位置映射仍需逐项核验，后者属于分钟至小时尺度。
将来增加来源时，应有独立reader及单位/来源组测试，不能只改列名。

## 下载、训练、测试

只需当前模块的 NumPy；没有增加 PyTorch、scikit-learn、GPU 或大型模型依赖。
在仓库根目录执行，`python`指已安装ai_training/requirements.txt的Python 3.11+：

```bash
python ai_training/scripts/fetch_public_sources.py --destination work/public_sensor_data

PYTHONPATH=ai_training/src python ai_training/scripts/train_multimodal.py \
  --data-root work/public_sensor_data \
  --config ai_training/configs/public_multimodal_v1.json \
  --output-dir ai_training/outputs/public_sensor_run

# 最终评价同一个配置的新run时才加 --evaluate-test；不要根据Test继续选参数。
python -m pytest -c ai_training/pyproject.toml \
  ai_training/tests/test_multimodal_public_data.py \
  ai_training/tests/test_multimodal_training.py \
  ai_training/tests/test_multimodal_fusion.py -q
```

下载器只取约百KB的公开传感器小表与MAT，保留来源和许可，不运行外部代码。
下载路径和训练输出路径必须为新目录；失败的下载目录可保留检查，重试使用新目录。
本机已实际验证9个来源文件的下载与reader结果一致。该Python环境缺省CA未配置，
下载验证时设置了`SSL_CERT_FILE=/etc/ssl/cert.pem`使用系统CA，HTTPS证书校验保持开启。

实际已拟合的两个模型位于 [pretrained/public_sensor_v1](pretrained/public_sensor_v1/README.md)：
`soil_model.json`、`motion_model.json`、配置、分组清单、训练报告。JSON包含标准化参数和权重，无pickle反序列化。
`RidgeForecaster.load`恢复模型；预测要求显式提供训练时的channel_names、units、time_unit，顺序或单位不匹配即拒绝。
不能把ADS1115 raw或仅有干湿两点校准的相对指数直接送入VWC模型。硬件适配层目前未实现。

报告同时提供保持上一观测不变的persistence基线。模型误差小于自身训练误差或优于训练基线，
都不证明对新实验有效；未优于留出基线时也如实保存，不能宣称迁移已经改善本项目效果。

## 规则融合与待完成的部分

`BranchEvidence`只接收上游已定义的状态：soil=`stable/wetting/drying`，motion=`quiet/anomalous`。
预测器本身不直接产生这些状态；残差、变化速度与状态之间的阈值，等待本地数据标定。

`fuse`显式接收同run、同clock的两分支证据及各自最大采样年龄：

- 土壤wetting＋运动quiet：`WETTING_WITHOUT_DETECTED_MOTION`。
- 土壤wetting＋运动anomalous：`COINCIDENT_WETTING_AND_MOTION`。
- 有效运动异常而土壤缺失：保留`MOTION_ANOMALY`，同时标记`INSUFFICIENT_DATA`。
- 缺失、过期、未来时刻、其他run/clock：保留原因，不作为NORMAL。

这些都是证据摘要，未接入泵控制、自动告警或生产风险等级。
没有本地配对数据时，不能从两个不相关来源训练第三个融合分类器。

后续最小交接为：真实CSV/时间侧表、传感器单位及安装位置、土壤标定、录像对应的事件区间、独立重复run。
新精简CSV若采用`elapsed_ms`，须单独版本化并明确重启/时钟身份；本次没有自行删改旧20列表头。

## 来源与署名

- LISA：Laura Longoni、Alessandro Scaioli、Lorenzo Panzeri、Diego Arosio、Monica Corti、Azadeh Hojat、Monica Papini；
  Politecnico di Milano及合作机构。数据 DOI：[10.7910/DVN/0H4AVF](https://doi.org/10.7910/DVN/0H4AVF)。
- Smartstone：J. Bastian Dost、Oliver Gronz、Markus C. Casper、Andreas Krein；Trier University与LIST。
  数据 DOI：[10.5281/zenodo.4316597](https://doi.org/10.5281/zenodo.4316597)；
  [原论文](https://nhess.copernicus.org/articles/20/3501/2020/)。
- 两个来源均为[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)。本代码选择小子集、排除明确无效记录并拟合新权重；
  原始文件不变，来源数据不随仓库复制。继续使用和再分发时保留署名及改动说明。
