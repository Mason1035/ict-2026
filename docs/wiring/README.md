# wiring

本目录保存硬件连接、GPIO、总线、电气约束和接线图。

推荐结构：
- `NODE-01/`
- `GW-01/`
- `SANDBOX-01/`
- `CAM-01/`

每个设备可逐步包含：
- `GPIO_RATIONALE.md`
- `LOGICAL_WIRING.md`
- `PHYSICAL_WIRING.md`
- `power_notes.md`

GPIO / 引脚约束尽量区分：
1. 芯片硬约束
2. 板级约束
3. 项目冻结约束

规则：
- GPIO 与总线首先以 `00_TEAM_SHARED_CONTRACT` 为准。
- 不理解的分配可写“待理解 / 待核对官方资料”，不要编造原因。
- 先画逻辑连接，再画物理接线。
- 电压、电平、供电、电流、上拉、地址等必须依据实物和数据手册验证。
- FROZEN GPIO 如需修改，先团队评审并更新主契约。
