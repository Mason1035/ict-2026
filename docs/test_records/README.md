# test_records

本目录保存可复现测试记录。

每份测试至少记录：
- 测试对象
- 版本
- 前置条件
- 操作步骤
- 期望结果
- 实际结果
- PASS / FAIL / NOT TESTED
- 日志、数据、截图或 Hash
- 失败复现步骤

推荐子目录：
- `NODE-01/`
- `GW-01/`
- `CAM-01/`
- `SANDBOX-01/`
- `integration/`

建议覆盖：
硬件 Smoke Test、I2C/SPI/UART、传感器有效性、SD、MQTT、LoRa、掉电恢复、断网、重启、重复/乱序/丢包、Watchdog、A-B-C 接口联调、Atlas/Cloud 集成。

未经测试的项目不能标记 PASS。
