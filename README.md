# 智哨防灾：开发仓库

当前已有合成模拟、训练基础设施骨架及最小 Telemetry 接收入口，尚不具备正式模型训练或端到端部署条件。
项目名称：**智哨防灾——基于昇腾与边缘计算的地质灾害多模态早期预警系统**。

最高依据：[00_TEAM_SHARED_CONTRACT.pdf](docs/00_TEAM_SHARED_CONTRACT.pdf)。
个人文档、交付契约、README 或代码发生冲突时，以 00 为准；正式资料只读。

| 路径 | Owner | 当前用途和状态 |
|---|---|---|
| `docs/` | A/B/C | 00 共享契约、01/02/03 个人文档、04 资产表，文档基线 1.0 |
| [physics_sim/](physics_sim/README.md) | C 何宇轩 | 0.1.1 合成观测生成器；第一阶段软件已验证，PRE_B / TODO_CALIBRATION |
| [team_handoffs/B_revised/](team_handoffs/B_revised/README.md) | B 张鹏飞 | B-adaptation-0.1；DEMO_ONLY Risk、TEST_ONLY fixture、DRAFT 正式训练契约 |
| `team_handoffs/B_original/` | B | 原始交付归档，保留，不作为新正式契约入口 |
| [ai_training/](ai_training/README.md) | C 何宇轩 | 0.1.1 SKELETON；B fixture 只读接入与 toy Trainer 自检；正式训练拒绝 |
| [edge_intake/](edge_intake/README.md) | C 何宇轩 | 0.1.0；已验证 v2 对象的内存接收边界，Mock 四例通过；生产下游未实现 |
| `outputs/`、模块内 `outputs/` | 验证记录 | 历史/新软件验证产物；合成数据与测试 checkpoint 不等于真实数据/正式模型 |
| `work/` | 本地环境 | 开发虚拟环境，不作为项目交付或真实实验数据 |

详细事实、证据、职责、阻塞项与依赖路线见：

- [PROJECT_STATUS_AND_READINESS.md](PROJECT_STATUS_AND_READINESS.md)
- [project_status.json](project_status.json)

各模块独立版本化；没有用单一版本号代表整个项目。model_version、正式 dataset_version、
calibration_version 当前均为 null。A 的真实数据与 B 的正式科学契约仍未完成交接。

正式主线：A Real Data + B Formal Contract + 经约束/校准的 C Synthetic → C Adapter → Dataset →
Training/Evaluation → Model Artifact → ONNX/Parity → ATC/OM/ACL → Atlas。
目前只能运行其中的软件骨架与模拟段。

独立旁路：B Demo Rules → Rule-distillation Fixture → C TEST_ONLY Reader。
其四特征、代理标签、demo split 不能约束 physics_sim 或成为正式训练默认值。

2026-10-05 新增接入支线：Validated raw Telemetry 同时分给 B Feature/Risk 与 C Edge Intake。
C 的新入口保留 payload、三元身份、MOCK sidecar 与 null；仅表示内存接收，不是可靠持久化确认。
A 当前 he_adapter.py 仍指向 RealAdapter，需由李青原切换至新入口后重跑三人 Mock。
接口说明见 [telemetry_v2_edge_intake.md](docs/protocols/telemetry_v2_edge_intake.md)。

## 验证

以下从根目录运行，使用现有 Python 环境。完整回归不包含历史 outputs 中的源码副本。

```bash
PYTHONPATH='team_handoffs/B_revised/队员B_算法开发交付:team_handoffs/B_revised:ai_training/src' \
PYTHONDONTWRITEBYTECODE=1 MPLCONFIGDIR=/private/tmp/zhifang_mpl \
work/.venv/bin/python -m pytest -c ai_training/pyproject.toml \
  'team_handoffs/B_revised/队员B_算法开发交付/tests' \
  team_handoffs/B_revised/tests ai_training/tests physics_sim/tests -q

PYTHONPATH=ai_training/src PYTHONDONTWRITEBYTECODE=1 work/.venv/bin/python \
  ai_training/scripts/validate_b_handoff.py \
  --handoff-root team_handoffs/B_revised \
  --artifact team_handoffs/B_revised/artifacts/rule_distillation_demo

PYTHONPATH=ai_training/src PYTHONDONTWRITEBYTECODE=1 work/.venv/bin/python \
  ai_training/scripts/validate_framework.py --self-test
```

2026-09-25 实际回归：210 passed / 0 failed / 0 skipped，另有 20 subtests passed。
软件测试通过不是灾害预警性能验证。正式模型、独立真实 Test、ONNX 导出和 Atlas 部署未执行。
未来 meaningful change 更新对应模块 README/CHANGELOG，并同步总状态；不改写历史测试记录。

2026-10-05 本轮相关验证（stdlib，无新增依赖）：

```bash
PYTHONDONTWRITEBYTECODE=1 work/.venv/bin/python -m pytest edge_intake/tests -q
PYTHONDONTWRITEBYTECODE=1 work/.venv/bin/python -m edge_intake.scripts.verify_mock_intake
```

实际 37 passed / 0 failed；M01/M02/M07 各接收 1 次，M08 四拒绝后入口 0 调用。
[测试记录](docs/test_records/integration/2026-10-05_edge_intake_v0.1.0/README.md)含固定 A 源码、输入与 C 代码 hash。
三人 Mock `NOT_RUN`，生产 Validator、持久化、Atlas/MQTT/Cloud `NOT_IMPLEMENTED`。
