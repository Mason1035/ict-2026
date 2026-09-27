# protocols

本目录保存正式接口、消息、协议和 Schema。

建议逐步形成：
- `telemetry_v2.md`
- `mqtt_topics.md`
- `lora_frame_v2.md`
- `commands_and_receipts.md`
- `vision_result.md`

协议文档应说明：
- 字段名与类型
- 单位
- null 规则
- 版本
- 错误处理
- 身份与幂等
- 正负测试样例

开发日志里的想法不自动成为正式协议。
未冻结的位号、字节布局、CRC、量化等必须明确标记 TBD。
