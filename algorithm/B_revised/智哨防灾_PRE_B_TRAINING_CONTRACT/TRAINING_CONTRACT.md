# 智哨防灾｜第一版 Training Contract

> **历史 TEST_ONLY 规则蒸馏说明，非正式项目 Training Contract。**以下“冻结”只指本生成器的
> 演示规则复现设置；A 不负责 AI 模型训练。当前 C 交接以
> [`../contracts/B_RULE_DISTILLATION_CONTRACT.json`](../contracts/B_RULE_DISTILLATION_CONTRACT.json)
> 和正式 Draft JSON 为准。旧输出保留审计，不能作为 Real/Physics-informed 正式训练集。

版本：`PRE_B_TRAINING_CONTRACT v1.0`　日期：2026-09-25　状态：冻结的演示训练数据契约

本包是早期规则蒸馏演示的输入/输出和评估约定，提供可在 PyCharm 运行的合成数据生成程序。这里固定的特征、代理标签、窗口、数据切分和指标只适用于 TEST_ONLY 规则模仿；**尚未训练模型，也未接入真实硬件或实测标签**。正式训练框架与模型由 C 负责。

## 0. 来自队员 B 文档的边界

《智哨防灾_队员B算法开发文档.md》规定算法只代表演示规则输出，阈值未经现场标定或灾害事件数据验证。湿度不能单独判定泥石流风险，杆体倾角不能等同山体位移；电池电量属于设备状态，缺测不能填 0；原始采样和风险结果分开保存。

因此本版标签是**规则生成的合成代理标签（weak/proxy labels）**。模型若使用此数据，只能研究如何拟合队员 B 的演示规则。这里的任何模型指标都不是地质灾害预测准确率，不能支持真实告警或现场安全判断。

## 1. 交付与运行

交付目录：`E:\华为ict大赛\智哨防灾_PRE_B_TRAINING_CONTRACT`。与 B 算法包并列存放；生成程序直接加载 `E:\华为ict大赛\队员B_算法开发交付\risk_algorithm.py` 和 `demo_rules.json`，不复制或改写它们。

在 PyCharm 中打开本目录作为项目，选择 Python 3.11+ 解释器，打开 `synthetic_dataset.py`，点击 Run。**不需要第三方 pip 包。** 程序将产生 `artifacts/pre_b_training_contract/`，不会覆盖源码或写入真实数据。

命令行（所有参数都可选）：

```powershell
python synthetic_dataset.py
python synthetic_dataset.py --groups-per-class 60 --seed 20260925
python synthetic_dataset.py --algorithm-dir 'E:\华为ict大赛\队员B_算法开发交付'
```

成功后查看 `artifacts/pre_b_training_contract/README.txt` 与 `summary.json`。随机种子、组数、特征列表、标签映射和切分比例都会写入运行摘要。

## 2. Features（冻结）

一条训练行是一段完整六点观测窗口，由固定参考段和最新判断段组成。下列四个连续数值特征在当前合成数据中均完整。单位在字段名中明确：

| 顺序 | 特征 | 类型/单位 | 固定算法 | 缺测处理 |
| --- | --- | --- | --- | --- |
| 1 | `soil_moisture_delta_pp` | 浮点；百分点 | 当前三点最后湿度减第一点湿度 | 当前/参考湿度缺测则该窗口不生成监督标签 |
| 2 | `soil_moisture_slope_pp_per_min` | 浮点；百分点/分钟 | 对当前三点使用采样 UTC 时间计算最小二乘斜率 | 不插值、不以前向值补齐 |
| 3 | `tilt_median_deviation_deg` | 浮点；度 | 当前三点倾角中位数减固定基线倾角中位数 | 参考或当前倾角缺测则排除 |
| 4 | `tilt_min_abs_deviation_deg` | 浮点；度 | 当前三点相对基线偏离绝对值的最小值 | 同上 |

训练端只允许使用上述 `FEATURES` 顺序与数值，禁止通过“自动选择 CSV 全部列”把标签或元数据喂给模型。特征由原始记录派生；派生值不会加入节点七字段协议。以后新增特征须升版并重新做泄漏评审，不能静默修改本合同。

**解释限制：** 这些仅为 TEST_ONLY 特征，刻意表达队员 B 演示规则使用的信号，因此和代理标签有强关联。模型从中恢复阈值不构成独立发现或科学验证。

## 3. Labels（冻结）

对每个合成窗口，将六条原始采样原样传入 B 包的 `RiskEvaluator.evaluate(history)`。使用 `risk_level` 生成目标：

| B 规则结果 | 训练目标 | 是否进入监督集 |
| --- | ---: | --- |
| `normal` | 0（规则未触发） | 是 |
| `attention` | 1（规则触发） | 是 |
| `warning` | 1（规则触发） | 是 |
| `unknown` | 无标签 / null | 否；写入 `excluded_unknown.csv`，保留原因 |

目标列名为 `label`，类型为整数 0/1。`risk_level` 与 `reasons` 留在审计文件 `synthetic_histories.jsonl` 中供追溯，**不作为模型输入**。unknown 绝不转换成负类，也不自动补值后重打标签。电量不会参与代理标签；只在符合七字段要求的记录中独立随机生成。

评估口径冻结为二分类“规则未触发 / 规则触发”，而非四分类灾害风险预测。A 若另做四级标签模型，必须先提交新版契约供三方确认。

## 4. Window（冻结）

- 一个样本 = 同一节点固定基线 + 当前判断窗口，共 6 个不同采样点。
- 基线：`sequence=1,2,3`；当前窗口：`sequence=4,5,6`。窗口互不重叠。
- 记录恰含固定七字段：`node_id, timestamp, soil_moisture_pct, tilt_deg, battery_pct, sequence, source`；`timestamp` 为 UTC，每条间隔 10 秒，`source="simulated"`。
- 依据 B 文档规则，两个三点段各自时长 20 秒、序号连续、间隔不超过 20 秒。一次只将六条序列调用给 B 的规则函数。
- 本数据生成器每个独立合成序列只产出一个样本。禁止从同一六点序列切出多个重叠行分别放进 train/validation/test。
- 真实应用重算迟到数据窗口的行为仍由 B 文档定义；本合同样本不模拟线上通知、无人机、网络重试或风险消息投递。

## 5. Split（冻结）

切分单位是**独立完整生成组（group）**，每组一个节点和一个窗口；同一组永远只能进入一个集合。固定随机种子 `20260925`，在目标类别层面分层后按组切分：

| 集合 | 组比例 | 用途 |
| --- | ---: | --- |
| train | 70% | 拟合模型与训练期参数 |
| validation | 15% | 选择模型超参数、分类阈值或校准方式 |
| test | 15% | 最终一次性报告冻结模型结果 |

默认分别生成 60 组 normal、60 组 attention、60 组 warning。因此二分类监督集的预期比例为 label 0 : label 1 = 1 : 2（60:120），**不是类别平衡数据**；切分按二分类标签分层，每类类别内按最大余数法分配为 42/9/9。至少各有 20 个有效组的负类和正类，以保证最小可行覆盖。不得对窗口记录进行随机行切分。禁止根据 test 结果调阈值、改特征、改模拟器再重复报告该 test 分数；发生这类选择后，须新建独立未触碰测试集并升版记录。

该切分只防止同一节点/窗口跨集合和直接时间窗口重叠。训练、验证、测试都来自同一版本规则生成器，所以它**不能测试跨设备泛化、真实场地泛化或真实灾害事件泛化**。

## 6. Leakage Rules（冻结）

`dataset_all.csv` 中有用于分组、标签审计和集合追踪的非特征列。模型只能显式取 `FEATURES`。这些列及其他衍生信息不得作为输入：

| 禁止入模项 | 原因 |
| --- | --- |
| `label`, `teacher_risk_level`, `risk_level`, B 返回的 `reasons` | 目标或直接目标解释 |
| `group_id`, `sample_id`, `node_id`, `sequence` | 设备/生成批次身份或采样顺序，可记忆标签组 |
| `timestamp`, 文件行号、生成顺序、split | 时间、导出和切分代理变量 |
| `source`, 场景名、生成器分支、随机种子 | 标签生成线索；本批全是模拟样本 |
| `battery_pct`、电量衍生特征 | B 契约明确电量不参与地灾等级 |
| `risk_level` 的 one-hot、阈值是否触发、阈值差值、未知原因 | 标签直接复制或重述 |
| 未来点或窗口外的摘要、全序列最大值、全序列统计 | 预测时不可用信息，且包含未来观测 |
| 同一节点相邻/重叠窗口跨集合 | 训练与评估信息交叉 |

禁止用测试集拟合标准化/填补/特征选择/校准。任何数据变换只能在 train 上拟合，再应用到 validation/test。测试评估必须固定训练好的变换和阈值。

合成标签本来由 B 演示规则生成，规则所用湿度/倾角信号也在 FEATURES 内。对规则解释特征的使用不是意外泄漏，但它意味着任务是**规则蒸馏/复现**；报告必须明确目标来源，不能称作独立预测能力。

## 7. Metrics（冻结）

正类定义：`label=1`（B 规则为 attention 或 warning）；负类：`label=0`。主要展示：

| 指标 | 定义 | 用途 |
| --- | --- | --- |
| confusion matrix | TN、FP、FN、TP，按固定 0.5 决策阈值 | 透明呈现错误类型 |
| precision | TP/(TP+FP) | 规则触发预测中的代理标签命中比例 |
| recall/sensitivity | TP/(TP+FN) | 代理正类覆盖比例 |
| specificity | TN/(TN+FP) | 代理负类识别比例 |
| F1 | precision 与 recall 的调和平均 | 单阈值正类折中 |
| balanced accuracy | (recall + specificity)/2 | 类别平衡后的阈值分类指标 |
| PR-AUC | Average Precision；使用预测概率 | 类别比例改变时审阅正类排序 |
| ROC-AUC | 对正负概率排序的 ROC 面积 | 作为次要排序指标，配合 PR-AUC 阅读 |
| coverage / unknown_rate | 可评估窗数 / 总窗数；unknown 数 / 总窗数 | 披露 B 规则对观测质量的拒判情况 |

若某集合仅有单一类别，ROC-AUC 写 `null` 并解释“测试集合缺少正类或负类”；分母为零的 precision/recall/specificity 记 `null` 并披露分母，不伪造为满分或零分。**这里仅规定 TEST_ONLY 指标口径；C 后续执行训练与评价，正式指标仍待 B 冻结。本包不报告虚构的模型性能。**

本生成器会在 `metrics_template.json` 保存指标定义、分母约定及 `model_metrics=null`。如果只运行规则再对比自身产生的标签，指标是恒等校验、理论上接近完美，毫无独立评估价值，因此不这么报告。

## 8. Synthetic Constraints（冻结）

1. 数据只由本目录程序合成，七字段全部有效；source 始终为 `simulated`。不混入真实节点、真实事件或外部数据。
2. 场景目标只用于合成器内部生成模式；标签仍由实际调用 B 的函数算出，若模式预期等级与 B 实际输出不一致，立即报错停止，不能强行盖写标签。
3. 固定基线湿度 20～55% 内抽取，倾角基线约在 ±0.8° 范围，三点波动小于 0.3°；电量 30～99% 独立于风险场景抽样。具体逐点数值见源代码，范围属于可复现演示素材。
4. normal 样本为稳定湿度与基线附近倾角，少量样本带未达持续条件的孤立倾角尖峰；attention 样本分为湿度关注趋势与持续倾角关注；warning 样本分为较大持续倾角与“倾角关注＋较强湿度趋势”。
5. 噪声为小幅确定性伪随机扰动，采样周期、范围、种子版本固定写入摘要。按不同 seed 重建的数据分布仍是同一合成世界，不能当成独立真实测试域。
6. 附加缺测样例在基线或当前窗口把湿度/倾角置 null；B 返回 unknown，这些窗进入排除审计文件，不参加有标签类别切分。模拟电量缺测同样不允许当 0。
7. 不生成“真实灾害”“泥石流”事件标签，不使用坡面灾害因果表述。warning 是规则演示标签，不是地灾真值。
8. 生成器采用 Python 标准库，不下载数据，不联网，不触及真实账号、云服务或付费资源。

## 9. 生成文件与队员 C 的 TEST_ONLY 接手接口

`artifacts/pre_b_training_contract/` 每次运行会重建：

| 文件 | 用途 |
| --- | --- |
| `train.csv` / `validation.csv` / `test.csv` | 可供 A 后续拟合的分区数据 |
| `dataset_all.csv` | 带分组、split、标签审计列和冻结特征的汇总表；入模时仍只取 FEATURES |
| `excluded_unknown.csv` | B 判为 unknown 的窗口、原因、missing_fields；不可训练 |
| `synthetic_histories.jsonl` | 原始七字段、代理标签和风险原因的逐组审计记录 |
| `summary.json` | 契约版、特征、样本数、按组切分、标签和 unknown 计数、随机种子 |
| `metrics_template.json` | 冻结指标定义，未训练的模型指标留空 |
| `README.txt` | 本次运行的可读说明和复现命令 |

仅限规则蒸馏 TEST_ONLY 的旧示例入口；C 正式接入应优先读取新版 JSON/manifest：

```python
from synthetic_dataset import FEATURES  # 直接复用/复制冻结字段常量，避免手写漂移

X_train = train_df.loc[:, list(FEATURES)]
y_train = train_df["label"]
X_valid = validation_df.loc[:, list(FEATURES)]
y_valid = validation_df["label"]
X_test = test_df.loc[:, list(FEATURES)]
y_test = test_df["label"]  # 只在选型锁定后报告一次
```

A 应单独向 B 确认特征、窗口和代理标签定义，再决定是否以规则蒸馏作为模型演示。如果目的是演示序列建模、边缘计算或模型泛化，需先提出相应的新契约，不能把本规则代理目标改称真实地灾标签。

## 10. 版本与变更

本 v1.0 仅固定 TEST_ONLY 规则蒸馏行为，不向 A/C 发布正式训练契约。演示特征、标签映射、窗口、组级 split、指标或合成约束变化，应记录版本和回归结果；如算法端更新，须同步核对 B 的 `demo_rules.json`。正式项目契约另由 B 版本化发布。

## 11. 验收边界

本旧包只能给 C 做接口联调或规则模仿测试。没有拟合或发布分类器，没有接入真实节点、应用页面、RDS/Redis、码道 CodeArts 云服务或真实告警；也不授权由合成成绩声称灾害预测有效。
