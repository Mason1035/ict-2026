# B 对 A 主机级回传的独立复核（2026-11-26）

范围仅 TEST_ONLY。用户转述 A 提交 97769a050c2ae9ab6afb1e4cbb857aa5d3a15a4d 的结果；E盘未找到所称附件ZIP及sidecar，未声称已收到或验证原包。

B从该提交提取最小源码快照到仓库外E盘，用本机g++8.1.0、C++17、-ffp-contract=off重新编译跑手及risk_framework_test，均成功；后者运行退出0。B比较器复跑3场景passed=true、errors=[]；独立逐项核对15个边界score_hex及等级，15/15一致。此为B本机源码复现，编译器与A所报16.1.0不同，不代表ESP32结果。

文件哈希核对：

- expected.json：与A声明一致；B实得 a2e44fefd900b80520b4e8d4b16ea12d52d63c2a7249be79851fbd93b72dc2c5
- actual.json：与A声明一致；B实得 3bb1e75c1895d5c6b7fc474e62e8f0fb374fa0c06a510c74da2ef38b6d1c6d5e
- actual_boundaries.json：与A声明一致；B实得 e35ce0f418a5d10100ee390cfb8cf87342a9101c7b7caed196765641078e5778

详细证据在 E:\华为ict大赛\03_分析结果\2026-11-26_当前\A独立跑手_B复核，包括源码哈希、编译/运行日志、实际输出、比较报告。未上传编译产物和第三方分支源码副本。

仍待核验：A原包/sidecar、全套32项Host日志、两套ESP-IDF编译日志；未完成实板/NVS掉电/本地GPIO动作验收。物理标定、阈值冻结、三方会签及实板黄金向量对拍仍独立待办。不得将本页或比较通过视为准许加载未标定配置。
