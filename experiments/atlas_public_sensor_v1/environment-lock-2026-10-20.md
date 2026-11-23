# Atlas 200I DK A2 环境锁记录（ict-2026）

- 记录日期：2026-10-20
- 记录方式：Muse 经 Tailscale SSH 在真机实测（非抄录文档默认值）
- 设备：Atlas 200I DK A2 开发者套件，主机名 davinci-mini
- 仓库版本：Mason1035/ict-2026 @ 327aa31（main，PR #7 合并提交）

## 硬件

| 项 | 实测值 |
|---|---|
| SoC / NPU | Ascend 310B4，Health OK |
| npu-smi | 23.0.rc3 |
| 内存 | 约 3.4 GiB |
| 磁盘 | 59G，总用量约 36%（部署后） |
| 功耗/温度 | 空闲约 6.9W / 44–46°C；平台运行后约 7.3W / 66°C（需留意散热） |

## 软件栈（板上预装 + 实测版本）

| 组件 | 版本/状态 |
|---|---|
| OS | Ubuntu 22.04 LTS，Linux 5.10.0+ aarch64 |
| CANN toolkit | 7.0.RC1（runtime/compiler/opp/toolkit 均为 7.0.0.5.242） |
| ATC | 可用：/usr/local/Ascend/ascend-toolkit/latest/bin/atc |
| pyACL | Python 可正常 import acl |
| mxVision | 5.0.RC3 |
| 驱动/固件 | 位于 /usr/local/Ascend/driver、firmware（driver/version.info 不在默认路径，版本号待补测） |
| 系统 Python | 3.9.2（miniconda base） |
| 项目 Python | 3.12.15（conda 环境 geo312，专为本项目新建） |
| Git | 2.34.1 |

## 本次新增部署（2026-10-20）

| 项 | 结果 |
|---|---|
| Mosquitto | apt 安装 2.0.11，systemd enabled + active，监听 1883（当前仅本机回环，节点从局域网接入需另改 listener 配置） |
| 仓库 | git clone（--depth 1）到 /home/HwHiAiUser/ict-2026 |
| 前端 | 在 x86 VM 上构建 dist 后传入板（避免板上构建吃内存），后端直接托管 |
| 后端依赖 | platform_backend/.venv（由 scripts/run-platform.sh 以 GEOHAZARD_PYTHON=geo312 创建），pip 源为清华镜像 |
| 平台运行 | uvicorn 127.0.0.1:8000 后台运行中；GET /api/v1/health 返回 status=ok、version=0.3.0、storage=sqlite_wal；demo MOCK 遥测正常入库；首页 HTTP 200 |
| 平台自报能力 | mqtt=implemented，vision=opencv_baseline（vision_score 未标定），atlas_acl=not_connected，cloud=not_connected（与仓库状态文件一致，未因本次部署改变） |

## 模型流水线验证（2026-10-20 追加，当日完成）

- 对象：public_sensor_v1 的 soil/motion 研究模型（JSON 岭回归），经 experiments/atlas_public_sensor_v1/ 流水线部署
- soc_version 实测确认：Ascend310B4；ATC 参数 framework=5、input_format=ND、precision_mode=force_fp32
- ONNX opset 13，静态 batch=1；图内含特征构造（末值+历史增量）+ 标准化 + 线性层
- ATC 板上耗时：soil 约 11 分钟、motion 约 9 分钟（root 运行、conda Python、单任务）
- OM：soil 64,394 B、motion 67,815 B，位于板 ~/ict-2026/experiments/atlas_public_sensor_v1/
- NPU 对账（vs float64 黄金向量）：soil 最大绝对差 1.03e-05、延迟 0.29ms；motion 最大绝对差 8.08e-03 但尺度相对误差 3.2e-04、相关性 0.99999996（310B fp32 MatMul 数值路径所致，非翻译错误，有 ORT 交叉对比佐证）
- 详细记录：仓库 experiments/atlas_public_sensor_v1/deployment_results_2026-10-20.md
- 平台自报 atlas_acl 仍为 not_connected：推理尚未接入平台运行时，本次仅为板级流水线验证

## 待办/未关闭项

- 正式模型仍缺（A 真实数据 + B 正式契约）；本次验证的是研究模型，deployment_ready 仍为 false
- Mosquitto 对局域网节点开放、设备账号与 Topic 权限未配置
- 平台对外访问未开放（当前仅回环；从 Mac 访问建议 SSH 隧道，或另行设置 API Token 后改绑 0.0.0.0）
- NPU 持续负载下温度需复测（散热条件确认）
