# Changelog

只记录本次开始的实际开发，不补造历史。未来每次 meaningful change 必须更新 README 当前状态，
并在此记录 schema、接口、seed/hash、泄漏规则、checkpoint、artifact、测试及缺陷修复的真实变化。

## [0.1.0] - 2026-09-25

### Added

- 建立独立 `ai_training/` src package、项目元数据、最小 requirements、输出目录与忽略规则。
- C 侧 Contract envelope / SplitManifest 提案与 unresolved example；正式 Contract 缺失、未批准或
  不支持时 fail closed。唯一可执行契约为显式 TEST_ONLY fixture，不代表 B 批准。
- TrainingSample / CanonicalDataset / Provenance，显式特征顺序、mask、时间可用性与来源分离。
- run/group/parent lineage 泄漏检查、Test 密封、Train-only normalizer 和非有限数据保护。
- RealAdapter 阻塞接口；SyntheticAdapter 只读 v0.1.1 artifact 身份检查，不映射正式 Features。
- Model/Loss/Optimizer/Normalizer/Metric Protocol，注入式 Trainer、Validation、best checkpoint 与
  early-stopping 接口。仅 fixtures 内包含 toy model/optimizer/normalizer/metric。
- 内容哈希、显式 numpy Generator、环境/框架/注入组件源码追踪、JSON checkpoint 与严格恢复身份。
- 无覆盖 artifact bundle、manifest 完整性与文件/运行身份检查，ONNX/Parity NOT_RUN schema。
- 测试、软件验证 CLI、README、Contract/config/fixture 边界说明。

### Changed

- 没有修改已有模块。physics_sim 源码、YAML 数值、物理/观测行为、README/CHANGELOG/测试，
  正式 docs 和根目录历史 outputs 全部保持不变。
- 本轮新增实现经自审补强：注入代码也进入运行身份；归一化输出重新检查 shape/dtype/finite；
  artifact 配置哈希回绑运行身份，checkpoint/normalizer/evaluation 跨文件归属核验；
  恢复 epoch/历史与停止原因明确记录。
- 首次测试暴露动态 fixture 模块未注册导致 inspect 源码定位失败；修正模块加载，未放宽测试。

### Tests

实际在现有 `work/.venv`（Python 3.11.9 / NumPy 2.4.3 / pytest 9.0.2）运行，未安装新依赖：

- `pytest -c ai_training/pyproject.toml ai_training/tests -q`：**83 passed, 0 failed**。
- 同时指定 `ai_training/tests physics_sim/tests` 的完整当前源码回归：**137 passed, 0 failed**；
  包含原 physics_sim **54** 项。不把根目录 outputs 的历史源码副本当当前测试集。
- 编译检查 **40** 个新增 Python 文件；导入 **26** 个 package/module 成功。
- 独立 `validate_framework.py --self-test`：TEST_ONLY_VALIDATION_PASSED。
  两次完整运行的逻辑身份、manifest 内容哈希、全部核心 artifact 哈希一致；epoch 2 checkpoint
  恢复至 epoch 4 后的全部核心 artifact 与连续训练一致，checkpoint 文件逐字节相同。
- unresolved Contract CLI 返回 **exit 2 / BLOCKED_OR_FAILED**，符合预期。
- 泄漏负向测试覆盖缺契约、feature/label/split 缺失、伪批准、provenance/latent/future 输入、
  run/parent/group 跨集合、循环/缺失祖先、Test/Validation fit、Test evaluation、非有限输入、
  checkpoint 身份/哈希错误、artifact 篡改、防覆盖与虚构 ONNX/parity 成功。
- 另以冻结 physics_sim 的 normal 场景生成独立临时 artifact，仅验证 SyntheticAdapter 的真实
  artifact lineage 兼容：**601 行通过**；feature_version/dataset_version 保持 null，没有用于训练。
- 前后 SHA-256 对照：`physics_sim/`、`docs/`、根目录 `outputs/` 共 **109 个已有文件**，
  **0 changed / 0 added / 0 removed**。

证据：[软件自检](outputs/TEST_ONLY_validation_jckfmwlh/validation_summary.json)、
[只读接口检查](outputs/INTERFACE_ONLY_xn9jwr3u/interface_summary.json)。
这些本地 outputs 不属于版本控制中的正式训练 artifact。

### Assumptions

- 所有可执行模型、数据和科学语义都是 TEST_ONLY / NOT_PROJECT_CONTRACT / NOT_APPROVED_BY_B。
- 当前只验证预对齐、全有效的极小人工序列；toy loss 没有项目科学意义。
- 接口门禁不是 Python 安全沙箱。外部 adapter 的真实计算/来源仍需审查。
- 内容身份与审计时间分离；本机 deterministic intent 不等于跨硬件 bitwise guarantee。
- Normalizer/模型/优化器的所有状态必须显式可序列化；策略必须无隐藏状态。

### Waiting Items

- WAITING_FOR_A（李青原）：Real CSV/schema、实验与设备来源、Calibration Metadata、validity 和交接。
- WAITING_FOR_B（张鹏飞）：正式 Training/Feature/Label/Window/Mask/Split/Leakage/Normalization/
  Metrics/Synthetic Constraints Contract，以及 Independent Real Test 保管和最终评价协议。
- 正式 Contract 接入需要版本解释器/adapter 与兼容性测试，不能通过改状态字符串启用。

### Known Limitations

- 没有正式数据转换、生产窗口/特征/标签构造、正式模型训练或项目性能评价。
- epoch 边界 JSON checkpoint；没有中间 batch / 分布式恢复或 tensor backend。
- 合成 inspector 只验证身份/哈希，不负责完整传感器语义、warmup/validity 到 Feature 的转换。
- 无 ONNX export/parity、ATC、OM、ACL、Atlas，也无 MQTT/Cloud/Web/Risk Fusion。
- 整体保持 PRE_B_TRAINING_CONTRACT；本版本完成的是骨架，不是正式训练就绪。

## [0.1.1] - 2026-09-25

### Added

- C 侧 `contracts/b_handoff.py`：读取 B 1.0-test-only / 0.1-draft 并调用 B 公开 validator；
  记录 Contract/validator hash、readiness、WAITING_FOR_A/B 与 TODO_CALIBRATION 未决项。
- `adapters/b_rule_fixture.py`：显式 TEST_ONLY tabular reader，验证嵌入/上游 Contract、manifest、
  10 文件hash、B verifier语义、规则/生成器来源hash；仅按 model_features 取X，label与provenance独立。
- `FormalTrainingNotAllowedError`；非TEST_ONLY用途先于读文件拒绝；Test不通过训练partition API暴露。
- `validate_b_handoff.py` CLI：重复读取/内容身份、正式用途拒绝检查及exclusive JSON报告。
- 31项B→C集成测试；根级README/PROJECT_STATUS_AND_READINESS.md/project_status.json由本轮总审计新增。

### Changed

- Framework独立版本0.1.0→0.1.1；正式状态继续PRE_B_TRAINING_CONTRACT。
- Loader识别B正式draft后输出具体A/B/calibration阻塞，不再仅报未知字段；B规则契约不能塞进toy解释器。
- 统一特征禁用表覆盖B新增scenario/source/teacher/group/sample/node/规则来源/generator seed等审计字段。
- README与Contract说明同步当前B旁路；没有将B四特征/代理label/demo split定义为正式项目规则。
- 未修改physics_sim任何文件、B_original/B_revised、正式docs或根级历史outputs；164文件hash对照无变化。

### Tests

实际使用Python3.11.9 / NumPy2.4.3 / pytest9.0.2；没有安装新依赖。

- 修改前全量：179 passed、0 failed、0 skipped；另20 subtests passed。
- 修改后全量：210 passed、0 failed、0 skipped；另20 subtests passed。
- 分项独立运行：physics54；B原Risk24+12subtests；B适配18+8subtests；ai_training114。
  ai_training114包含新增integration31，不能重复相加成245。
- 编译65个活动Python文件、导入28个ai_training模块成功。
- toy自检完整重跑、epoch2→4恢复、核心artifact hash与checkpoint字节一致；正式训练入口拒绝。
- B integration CLI重复输入/身份一致；正式draft CLI预期exit2；新JSON输出拒绝覆盖已有文件。
- 三physics场景重跑一致、1803行C lineage检查、三份plot CLI成功；Inf=0，仅保留约定首行rate null。
- 负向测试包括伪ready/版本、hash与rehashed语义篡改、来源/用途冒充、provenance入X、非有限数、Test封存。

证据：[本轮总记录](outputs/PROJECT_AUDIT_7rasdry4/verification.json)、
[B接入](outputs/PROJECT_AUDIT_7rasdry4/b_integration.json)、
[toy重跑/恢复](outputs/PROJECT_AUDIT_7rasdry4/toy_cli.stdout.json)。旧记录保持原样。

### Assumptions

- B public CLI运行于隔离进程，避免顶层contracts包冲突；依赖可信本地B_revised源码，不是执行不可信代码的沙箱。
- B数据已是预聚合tabular rows，C不伪造time axis/mask，不转成独立toy scalar-regression contract。
- B group_id不是Real run_id；nullable来源保持null。reader float64/int64不代表正式dtype冻结。
- B输入fingerprint用于完整性，不是正式dataset_version/模型身份/审批/科学有效性证明。
- B reader smoke不训练模型；独立toy loop只有软件测试意义。

### Waiting Items

- WAITING_FOR_A：Real CSV、Calibration Metadata、逐通道validity、run/时间/坐标与真实响应证据。
- WAITING_FOR_B：正式Features/Labels/Window/Split/Leakage/Normalization/Metrics/Synthetic Constraints、独立Real Test。
- TODO_CALIBRATION：physics/sensor/泵雨与真实扰动参数；只允许未来Train来源拟合。

### Known Limitations

- 正式Contract解释器/Real与Physics Feature Adapter仍未实现；整体是Skeleton，不是production训练框架。
- B reader需要完整源码交付与fixture；只支持当前版本，不猜未来schema。
- Test API门禁不是文件访问隔离；不证明上游任意派生公式无隐藏未来信息。
- 未训练正式模型、未运行Real-only/Real+Synthetic/Independent Real Test，未导出ONNX或执行ATC/OM/ACL/Atlas。
