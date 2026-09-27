# decisions

本目录保存重要工程决策，推荐采用 ADR（Architecture Decision Record）。

适合记录：
- 为什么正式固件使用 ESP-IDF。
- 为什么 NODE 本地 Risk 不依赖 Atlas / Cloud。
- 为什么 LoRa 不直接传 JSON。
- 为什么某硬件被保留、替换或延期。

推荐命名：
`ADR-0001-use-esp-idf.md`

ADR 最小结构：
- 背景
- 决策
- 原因
- 影响
- 证据 / 关联

涉及 FROZEN 内容时，ADR 不能代替团队评审和 `00_TEAM_SHARED_CONTRACT` 更新。
