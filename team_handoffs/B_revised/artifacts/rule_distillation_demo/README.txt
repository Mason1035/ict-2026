智哨防灾 B_RULE_DISTILLATION_CONTRACT 1.0-test-only TEST_ONLY 合成规则蒸馏输出

本数据全部合成；标签来自队员 B 的 demo-rules-1.0.0 规则输出，不是真实灾害标签。
任何分数仅可解释为规则复现效果，不能解释为灾害预测性能。

复现：python synthetic_dataset.py --groups-per-class 60 --seed 20260925
规则包 SHA-256：6eeb04832b47fd8d1b650808e8257f89f935bd3b128c34bbbe7b46d5220f0d38
有效监督窗口：180；unknown 排除窗口：18

文件：train.csv、validation.csv、test.csv、dataset_all.csv、excluded_unknown.csv、
synthetic_histories.jsonl、summary.json、metrics_template.json。
模型输入列必须显式取：soil_moisture_delta_pp, soil_moisture_slope_pp_per_min, tilt_median_deviation_deg, tilt_min_abs_deviation_deg
group_id/node_id/sequence/timestamp/source/battery/labels/reasons/split 全是非特征元数据。
