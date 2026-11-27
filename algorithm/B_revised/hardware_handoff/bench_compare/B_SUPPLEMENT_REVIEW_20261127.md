# A补充核验包接收结论（2026-11-27）

范围：TEST_ONLY离线对拍及软件日志证据；不批准加载未标定配置。

已接收本地 A_TO_B_TEST_ONLY_BENCH_AND_LOGS_20261126.zip，外层SHA-256为 a10b6a0c00d56cee38b9f3aed413c887cea0652173279e64eeee5a96c4bee3f2，与A声明一致。ZIP CRC通过；SHA256SUMS.txt全部9项通过且完整覆盖其余成员；嵌套原包CRC通过、5个原件与外层逐字节一致。

sidecar对应97769a050c2ae9ab6afb1e4cbb857aa5d3a15a4d，B参考bd962b2339c7d1a2b4947de372f2ee7a6cbab933；三份B参考和三份A产出的哈希全部核对一致。B使用原actual.json重新比较，3场景passed=true、errors=[]；15个边界输入score_hex及等级逐项一致。

新补充日志由A说明对应0f4ea38ed53aac7c23ebbfdbf7bdf938206fcace。已从远端核对该提交仅改SDSPI驱动及两份文档，且从97769a05到该提交的node_logic及bench_compare_runner.cpp无差异。提交关联是A提供的日志来源声明加Git范围核对，不是日志签名认证。

Host日志有32条PASS标记、31条不重复标记；HOST_NETWORK_POLICY_TEST_PASS重复一次。因此按“32条PASS输出”记录，不作为32个独立测试或覆盖率。退出码0由A回执/sidecar声明，日志没有独立结构化进程退出码，本次未重跑全套Host测试。

ESP-IDF v5.5.3日志有两次Project build complete及BOTH_ISOLATED_BUILDS_OK。日志记录的WDT修复后产物：

| 配置 | BIN字节 | BIN SHA-256 | ELF SHA-256 |
|---|---:|---|---|
| live | 867968 | 7f410f44f68ac26011d46cdd317594320537232ea86ce5cf199d733006b0947d | ad03a533db89b30980d737056bd3e438bc25c286ed3200ad6b72ba3bd79bc751 |
| sandbox | 436016 | 469585c4791638e9ca1fc6cf57e378cbcff6da0502987075a275de1bed7ca747 | ca4666ca6b9b1248946b5ef265ee94186285692c6ac8efbdf9b3524cc30cab55 |

sidecar中的旧867856/435904字节及旧哈希保留原义，不覆盖。包内没有BIN/ELF，因此上述新产物哈希仅完成日志查阅，未独立重算；B未重跑ESP-IDF构建，也未刷机或扩展固件白名单。

截至本次：原包及sidecar已收件核验，Host完整日志和两套编译日志已查阅归档，前页“未收到”仅是2026-11-26当时状态。真实标定、配置冻结、三方会签、ESP32黄金向量、NVS掉电、GPIO/按键实测及链路送达验收继续待办，不把编译成功解释为WDT现场修复通过。

E盘详细记录：E:\华为ict大赛\03_分析结果\2026-11-27_当前\A补充证据核验\evidence_review.json；原包保留原路径，不移动不改写。仓库仅收录结论，不公开原始日志或构建产物。
