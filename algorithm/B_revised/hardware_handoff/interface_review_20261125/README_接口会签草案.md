# B → A/C：RiskTask / AlarmTask 接口会签草案 V0.1

日期：2026-11-25。状态：PENDING_A_B_C_REVIEW。本包可供实现解析和隔离测试骨架；不是已会签契约、不是设备可加载配置，不启用正式阈值。任何 Telemetry/命令字段、Topic、reason_mask 位号必须三方确认后才能对外生效。本包不修改冻结 Telemetry。

## 1. 本次范围与既有代码

沿用 telemetry_v2_intake/config.py 的 B.feature_risk.config.v1，以及 RUNTIME_CONFIG_DRAFT.json 的实际字段；不再造一份平行的完整评分配置。原配置 mode=DRAFT、空参数必须拒绝；TEST_ONLY 只用于隔离注入，不接真实现场告警。已有数学与 TEST_ONLY demo 不因此升级为正式实现。

INTERFACE_PROPOSAL.json 是本说明的机器可读提案，不能直接送给现有 validate_config 当作 risk_config。新增 Alarm 部分是单独的策略提案，现有 FeatureRiskRuntime 不实现它；现有配置验证器也不替 Alarm 验证器验收。A 可先解析、拒绝 DRAFT 和保留接口，不能据此声称 Alarm 已实现。

## 2. reason_mask 提案

采用 uint32_t，并另设有效性，JSON 无结果为 null。位号从 0 开始：

| bit | 十六进制 | 名称 | 置位条件 |
|---|---|---|---|
| 0 | 0x00000001 | TILT_CONTRIBUTION | 有效倾角贡献 > 0 |
| 1 | 0x00000002 | VIBRATION_CONTRIBUTION | 有效振动贡献 > 0 |
| 2 | 0x00000004 | MOISTURE_CONTRIBUTION | 有效湿度贡献 > 0 |
| 3 | 0x00000008 | GROWTH_CONTRIBUTION | 有效增长贡献 > 0 |
| 4 | 0x00000010 | DUAL_IMU_CONSENSUS | 双 IMU 共识条件满足，实际奖励为 5 |
| 5–31 | — | RESERVED | 发送端清零；接收端记录未知位并拒绝声称已完整解释，不擅自当故障位 |

理由位解释贡献来源，不等同 WARNING 或 SLIP；NORMAL 也可能有非零 mask。贡献全为零且评分有效时 mask=0；评分无效时 mask=null。贡献先保持浮点原值，不按页面舍入决定置位。故障、缺测、在线、送达状态与风险理由分别记录，不塞进这五个位。旧 TEST_ONLY 模式继续不分配正式 mask。

会签后须同时冻结 reason_mask_version 与配置中的 reason_bits，不能只更新 A。未会签仍保持现有 null 行为。

## 3. 缺测与分段策略

第一版提议继续 REQUIRE_BOTH_IMU_AND_ALL_THREE_SOIL_V1：双 IMU 与三路 Soil 必须全部满足有效性、窗口覆盖、时龄、采样对齐、标定/身份要求。任一路无效、过期、缺配置、窗口未预热或时间异常，sensor_score/level/reason_mask 均为 null。可显示仍有效的单路特征；不以 0 填空、不保持旧值冒充新采样、不重归一权重、不用单 IMU 假造共识。

故障恢复后须重新满足相应窗口和预热要求。boot、装夹坐标、ODR、标定或特征配置切换时分段，不跨段拼接；重复/旧包不能刷新 freshness、累计驻留时间或重复触发。使用板端单调采样时间；回放/补传历史不触发“当前现场新报警”。首次没有有效配置时继续原始采样，报告未标定；不是 NORMAL。

本版 Soil 风险输入仍是经批准的相对刻度。W_rel 与 vwc_est_pct、原码和版本分别保存；新土试用输出不替换旧正式字段。若改用 VWC 曲线，需新 feature/config 版本和重新验收。

## 4. Alarm 状态与动作提案（须 A/C 审核）

逻辑状态：UNARMED、ARMED、ACTIVE_LATCHED、ACKED_LATCHED、RECOVERY_PENDING；传感器/通信故障另设标记。GPIO 输出可区分静音与风险锁存，不能用蜂鸣器关断表示“安全”。

| 当前情况/事件 | 提议动作 |
|---|---|
| 启动，无批准配置且无历史锁存 | UNARMED，风险 null，显示未标定；不制造地灾告警 |
| 有效配置及预热完成 | ARMED；等待当前有效结果 |
| 当前有效等级达 WARNING/EMERGENCY，持续满足 entry_dwell_ms | 锁存 ACTIVE_LATCHED，保存触发上下文后驱动本地声光；参数未定时不启用 |
| 活跃期间更高等级 | 升级锁存等级，保留最高级与初始触发记录 |
| 掉线、缺测、窗口重置、配置被拒绝或云/NPU故障 | 不清除既有锁存；清除计时失效，恢复需重新计时 |
| 本地授权确认 ACK | ACKED_LATCHED；允许按会签输出策略静音，保留 LED/记录和锁存，不等于解除 |
| 当前有效 score 严格低于 clear_score_exclusive 且持续 clear_dwell_ms | RECOVERY_PENDING；仍保留锁存，等待明确本地 CLEAR |
| 已 ACK、持续满足恢复条件、收到本地授权 CLEAR | 清除锁存，回到 ARMED；任一条件缺失拒绝 |
| 远程 ACK/CLEAR、历史回放触发、配置更新 | 第一版不允许通过这些动作直接解除锁存 |

clear_score_exclusive 必须低于对应进入等级下界，形成滞回；本轮 entry_dwell_ms、clear_dwell_ms、最大结果年龄及解除值均未定，不用猜测秒数。无效/超时/乱序结果中断连续计时；允许的调度间隙须显式配置。计时基于不重复的当前有效观测，不按循环次数累计。

锁存记录须带 site/device、boot、触发序号/单调时刻、最高级、原始触发理由、风险/Alarm 配置哈希及确认/解除审计。触发理由与最新理由分存；最新风险失效不擦除触发证据。原子保存/校验并按设备恢复；重启后恢复锁存和指示，但恢复/解除计时重新开始。损坏或不明持久化状态进入故障待人工核查，不悄悄当无报警；首次空记录须与损坏记录可区分。存储失败报告故障，不能据此取消即时本地指示。断电期间声光无法保证持续工作。

GPIO6 蜂鸣器/GPIO14 LED 仅记录 A 的规划；有效电平、外部驱动、启动电平、静音/闪烁模式、持续能力、自检与锁存恢复由 A 提供 hardware_profile，不代填。测试成功只说明现场输出；MQTT PUBACK/Atlas 落库不等于远端警报送达，送达须 C 定义独立回执。

## 5. 配置、加载与完整性

Risk 结构直接参照本包附带 RUNTIME_CONFIG_DRAFT.json：schema/mode/config_version/feature_version/calibration_version/frame_id/device_identity/sensor_ids/validated_for_runtime/review_refs/reason_mask_version/reason_bits/weights/odr_hz/missing_policy/imu/soil/windows/curves/consensus/config_hash。窗口按真实毫秒；IMU m/s²、度，增长为相对百分点/分钟。不得把 VWC 百分点混进相对指标曲线。

Alarm 配置字段见 INTERFACE_PROPOSAL.json.alarm_policy_proposal，单独引用 risk_config_hash、reason_mask_version 和 hardware_profile。它在本轮永远为 DRAFT。A/B/C 会签引用是审计凭据，不能用任意非空字符串当签名。声明的固件哈希是适用性声明，SHA-256 仅提供完整性，不认证设备或操作者。

发布时 B 提供不可变 JSON、规范化哈希输入字节、SHA-256 和配套向量；沿用现有 Python config_hash 实现，不能由 ESP32 自行重新格式化浮点后直接比较。跨语言规范化方式会签前：使用 B 随包提供的规范字节作为哈希对象，并验证解析内容与这些字节相同，拒绝重复键、NaN/Infinity、缺项、未知 schema/字段和类型/范围错误。若改用原始文件哈希或其他规范化算法，必须新版本，不静默改变旧 config_hash 含义。

加载先验证模式、完整性、设备/传感器/固件/标定适用性、三方审核记录、全参数及 Risk/Alarm 关联关系；两份配置作为一组原子激活。任一失败保留最后批准组合并记录拒绝原因；若旧配置已不适用于当前身份/安装/版本，保留审计但停止评分。配置更新不清除报警锁存，窗口重新预热；缺参数不部分启用。当前加载器尚无完整设备端认证和 Alarm 配置事务实现，需 A 实现并实测。

## 6. 浮点与黄金向量比较约定提案

Python 参考使用 binary64；ESP32 若采用 float32，按实际类型和运算顺序记录。参考初值：abs(actual-ref) <= atol + 1e-5*abs(ref)。atol：倾角/方向角 0.001°；振动 0.0001m/s²；相对湿度 0.001 个百分点；增长 0.001 个百分点/分钟；贡献和评分 0.001。以上是待实板验证的软件容差，不是传感器精度。时间整数、身份、null、等级、位掩码、锁存/ACK/CLEAR 状态必须精确一致。

等级按未舍入 score 的 [0,30)、[30,60)、[60,80)、[80,100]；不加 epsilon，不用浮点容差放行等级错误。贡献 >0 的位也不使用 epsilon。边界取 30/60/80 和各自相邻 float32 值，同时测试 0/100、贡献恰为0及微小正数。若评分误差在容差内但等级/理由位不同，仍失败，须统一精度/运算顺序或升级数值规范。

随包 verify_proposal.py 只核验草案自洽、既有 DRAFT 拒绝加载和比较规则；不是新的实板黄金向量或 Alarm 状态机实现。旧数学向量的 Python 1e-12 比较保持不变。

## 7. 本轮范围与会签表

B 提议按 50/70/100% 各3次独立约30秒称重、实测受雨面积做本轮三档复核；C 尚未会签，不能替代旧五档60秒方案，范围外保持未验收。30秒用真实计时，保留每次质量/时长/流量、重复性和环境条件，不把收集水量直接当沙盘实际均匀雨强。

A确认：数据身份/采样能力、GPIO驱动与自检、持久化与重启、uint32/null、浮点类型及比较可实现性。
B确认：理由语义、保守缺测策略、相对指标单位、候选数学和数值规范；参数待真实数据冻结。
C确认：Telemetry映射、理由版本兼容、独立故障/送达回执、配置交付审核和本轮水泵范围。

三方分别给出姓名/日期/准确文档版本或提交/同意条款/异议；当前均为待签。若改规则，发布新版本，不编辑已签名版本。接口会签不自动批准数值配置。11月28日数据验收后依次：冻结配置及哈希→Python回放向量→ESP32逐向量对照→故障与重启/断网HIL→C端接收和显示复测。不能承诺半天必然验收通过。
