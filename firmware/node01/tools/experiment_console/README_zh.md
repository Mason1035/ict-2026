# NODE-01 Windows实验控制台与日期归档

这是第十五轮固件的PC配套工具。**固件没有改变，SD卡仍保存Nxxxxxxx.CSV/.BEG/.END**。本工具将核验通过的副本按 `YYYYMMDD_HHMMSS_NODE01_<实验ID>_<防重号>` 命名到电脑，不把PC副本说成SD本体改名。

2026-10-31真实30秒失败运行后的PC修复：屏幕按实际ESP级别、首个事件名和对应数值字段分类；全零SD_FAILURE/压力统计、正常queue_wait不会因说明文字被标红。IRQ ARM ESP_OK是成功里程碑，IRQ fallback/长尾保留黄色告警；SOIL_READ、本地I2C锁超时、非零历史错误计数与真实失败终态仍突出显示。

`CAPTURE_CSV_VERIFIED`正文中的“等待EXPERIMENT_FINALIZED/EXPERIMENT_FINALIZE_FAILED”仅是提示。只有准确的终态事件才建立终态。`session.json`保留原格式及归档字段，同时新增连接状态、实验结果、终态事件/原文/原因/校验字段；后续STOP或断线不会覆盖已观察到的FAILED。断开连接仍标证据不完整，失败实验不会自动变成合格归档。固件身份分为MATCH/MISMATCH/NOT_OBSERVED/UNKNOWN；未收到启动ELF不是MISMATCH。本修复不需要重新烧录。

## 一条命令启动

先关闭ESP-IDF Monitor、桥接和其他串口占用者。推荐Windows Terminal内的PowerShell 7：

```powershell
& 'C:\Users\LQY\Documents\GitHub\ict-2026\firmware\node01\tools\Start-ExperimentConsole.ps1' -Port COM7
```

若执行策略拦截或当前是旧PowerShell，可直接使用本机已经验证存在的PowerShell 7程序：

```powershell
& 'C:\Users\LQY\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\powershell\pwsh.exe' -NoProfile -ExecutionPolicy Bypass -File 'C:\Users\LQY\Documents\GitHub\ict-2026\firmware\node01\tools\Start-ExperimentConsole.ps1' -Port COM7
```

本轮编码助手未执行真实连接。COM7是默认值；查询端口（只枚举，不连接）：

```powershell
& 'C:\Users\LQY\Documents\GitHub\ict-2026\firmware\node01\tools\Start-ExperimentConsole.ps1' -ListPorts
```

默认115200，可用`-Baud`改；`-OutputDir`改控制台日志根目录，`-Manifest`选匹配固件的Manifest。默认验证现有第十五轮最终后缀候选，不能拿本机Manifest存在当作设备身份已经确认，只有真正收到的app_elf_sha256与之相符才显示MATCH。未捕获启动就显示NOT_OBSERVED；建议在没有活动实验或已经完整结束后，由人手动RESET一次以捕获完整身份和READY，工具不会替人复位。

## 独立环境

当前电脑已配置并测试：`C:\Users\LQY\Documents\Codex\node01-pc-console-venv`。固定ESP-IDF Python未安装界面包。以后若独立环境缺失：

```powershell
& 'C:\Users\LQY\Documents\GitHub\ict-2026\firmware\node01\tools\Setup-ExperimentConsole.ps1'
```

依赖精确版本见requirements.txt。Setup拒绝安装进ESP-IDF环境，也不覆盖未标记的其它venv。工具不需要激活ESP-IDF，不调用idf.py、esptool或Monitor。非交互终端会明确拒绝启动界面，不退化为会冲掉输入的后台print+input；可在Windows Terminal/PowerShell7重开，或仅使用`-Help`、`-ListPorts`、离线归档。

## 先确认电脑时间，再操作实验

启动会显示电脑当前ISO8601、实际偏移和时区来源，要求人工输入`YES`确认正确。输入`UNKNOWN`仍可记录/控制，但日期归档会拒绝；其它输入退出且不连接。默认读取Windows当前本地时区，不按国家/环境猜测。

可明确选择IANA时区或固定UTC偏移，两者互斥，例如（仅示例，必须核对实际位置）：

```powershell
& 'C:\Users\LQY\Documents\GitHub\ict-2026\firmware\node01\tools\Start-ExperimentConsole.ps1' -Port COM7 -Timezone 'America/Toronto'
& 'C:\Users\LQY\Documents\GitHub\ict-2026\firmware\node01\tools\Start-ExperimentConsole.ps1' -Port COM7 -UtcOffset '+08:00'
```

IANA使用独立venv的tzdata处理DST；固定偏移明确不处理DST。系统偏移改变或UTC与单调时钟相对跳变超过2秒会标记UNKNOWN_TIME，保留原观测、不补造时间。这个阈值只是主机异常检测，不是对时精度承诺。

只有收到完整、真实的`EXPERIMENT_BEGIN`，才以**主机读到该行的时间**建立 `HOST_OBSERVED_EXPERIMENT_BEGIN` 日期锚，同时保存UTC偏移、ISO8601、PC monotonic_ns和设备monotonic_us。START发出、BEG文件生成、Windows修改日期、N序号都不是BEGIN。秒级显示不等于设备UTC误差小于一秒；串口排队、分块、驱动和显示延迟仍存在，设备没有被本工具对时。

## 在固定输入行操作

输入区始终显示 `NODE-01 >`，支持退格、方向键和编辑；后台只更新独立日志区。输入命令后按Enter：

```text
EXP HELP
EXP STATUS
EXP START 30
```

先等待设备真实READY。`[PC发送]`只说明本机写入，ACK仍不是BEGIN。等真正BEGIN后，按需要输入：

```text
EXP STOP
```

START_PENDING期间STOP不能取消，请看设备回复，BEGIN后重发。STOP或TIME_LIMIT后等`EXPERIMENT_FINALIZED`，不能只见`CAPTURE_CSV_VERIFIED`就取卡。最终消息缺失、缺校验标记、失败或断开都不能当结束；保留证据。一次上电一场，下一场由人等收尾完成后手动RESET。

本地命令不会写串口：

|命令|作用|
|---|---|
|`:help`|中文帮助|
|`:status`|本机观测状态、时钟问题、日志目录|
|`:verbose on` / `:verbose off`|切换完整/精简屏幕，落盘不变|
|`:ports`|只枚举当前端口|
|`:quit`|退出；未确认终态时先警告|
|`:quit confirm`|明确退出，不暗中STOP|

Ctrl+C/Ctrl+D也会先警告，再次确认退出。关闭工具不等于EXP STOP，不保证CSV收尾。断线不自动重连/STOP/RESET，新开会话从UNKNOWN开始；本工具不提供烧录或擦除功能。

屏幕默认折叠正常IMU_IRQ/I2C_DEVICE/SD_PHASE/TASK_PROGRESS/HWM；真实错误、非零drop/error、失败和关键状态显眼显示，最新警告留在固定底栏。正常SD长尾不被自动解释成丢样。屏幕区有界；错误队列过载会保留显著告警、暂停发送，完整RX仍落盘，不静默丢错。

## 完整记录在哪里

启动后显示实际目录，默认在：

`C:\Users\LQY\Documents\GitHub\ict-2026\docs\test_records\NODE-01\sandbox-experiment-archive\console-runs\console-session-<本机启动观察时间>-<随机号>`

这是**控制台启动目录时间**，不是实验BEGIN时间。

- `serial.bin`：实际收到的原始字节，含ANSI、乱码字节和部分行；从不添加PC ACK/时间。
- `device.txt`：完整流式UTF-8可读解码，乱码用转义保留可读性，不做屏幕过滤；原始依据仍是.bin。
- `events.jsonl`：每块RX偏移/字节、PC发送时间和实际字节、真实回复、时间异常及状态事件。
- `session.json`：有限状态和BEGIN观察映射，正常关闭后含三份证据文件的实际SHA/长度。

接收chunk4096、协议行8192、UI队列256、屏幕200行/64KiB；没有无限日志RAM缓存。写盘或部分写入失败立即显著告警、禁继续发命令并退出失败，不能称“完整保存”。正常至少每秒尝试fsync，关键BEGIN/最终状态强制同步；这不是电脑突然断电时的绝对持久性保证。未接通/断开期间的设备字节不可能凭空恢复。

pyserial打开前将DTR/RTS设为False，不主动脉冲、reset/break或清空RX；[官方API](https://pyserial.readthedocs.io/en/latest/pyserial_api.html)说明OS/驱动仍可能产生开口瞬态，因此真实控制线/USB行为需现场验证，不能把软件设置当成物理零复位证明。

## 安全取卡后，只读预览，再明确复制

等设备完整最终状态，退出控制台，确认无未完成写入后由人安全取卡。保留原始三文件。将下面路径换成本次实际控制台目录和读卡器目录：

```powershell
$nodeTools='C:\Users\LQY\Documents\GitHub\ict-2026\firmware\node01\tools'
$nodeRun=Read-Host '粘贴本次控制台实际日志目录'
$nodeSd=Read-Host '实际SD读卡器根目录或原始三文件目录，例如 E:\'
& (Join-Path $nodeTools 'Archive-Experiment.ps1') -SdDirectory $nodeSd -Session $nodeRun
```

默认dry-run，不创建归档副本。它按实际实验ID配对N原文件，检查RX证据hash/解码/事件锚，真实调用原第十五轮校验器，核验固件、CSV长度/CRC/行数/索引/EOF与BEG/END和UART；没有BEGIN、时钟不可信、缺END、短表头、重启、中断或源内容变化都拒绝通过。UNKNOWN_TIME/INCOMPLETE非零退出，保留原因，不是工具自动补数据。

预览通过、明确要复制时：

```powershell
& (Join-Path $nodeTools 'Archive-Experiment.ps1') -SdDirectory $nodeSd -Session $nodeRun -Copy
```

支持`-OutputDir`选择较短的PC目录（不能放源SD目录内），`-ExperimentId`明确选一场（同会话多场不能猜），`-Manifest`指定匹配固件身份。同秒防撞、目标排他创建；不移动/改写SD原件。失败可能保留`ARCHIVE_FAILED.json`和部分副本，不把“存在CSV”当作通过。

归档文件组使用：

```text
YYYYMMDD_HHMMSS_NODE01_<原ID安全编码>_<随机号>.CSV
YYYYMMDD_HHMMSS_NODE01_<原ID安全编码>_<随机号>.BEG
YYYYMMDD_HHMMSS_NODE01_<原ID安全编码>_<随机号>.END
YYYYMMDD_HHMMSS_NODE01_<原ID安全编码>_<随机号>.session.json
```

以上是命名格式示例，不是真实结果。副本三文件逐项SHA与源相同，JSON内容仍引用原N名；映射完整记录源/目标路径、原N号、真实ID、时区、观察时间、验证结果和SHA。先对原N文件运行旧校验器，再用SHA证明改名副本等价，不声称旧校验器能直接接受日期改名文件。另复制原始串口、事件、原会话和Manifest以追溯。迁移电脑时仍需配套固件身份文件/旧校验器环境，不靠漂亮名字证明数据有效。

仅历史SD目录预览（无接收时间证据，必为UNKNOWN_TIME）：

```powershell
& (Join-Path $nodeTools 'Archive-Experiment.ps1') -SdDirectory $nodeSd
```

不使用Windows修改日期或日志文件名推算BEGIN。暂不提供无依据人工补录；保留原证据后可另做有依据的人工审查。

## SD卡本体命名与验收边界

`SD_TIMESTAMP_NAMING_NOT_IMPLEMENTED_WITH_REASON`。实际LFN_NONE不能直接创建完整长日期名；设备无可信现实时间，也无时间传递/ACK。8.3日期目录方案在技术上可行，但必须改实验模式的创建前路径、经过确认的时钟有效期、冲突/恢复和元数据引用；当前READY前已开N文件，不应靠事后非原子批量rename冒险。本轮不改固件，不生成无意义新BIN；SD仍N编号，PC日期副本是另一项独立交付。

软件测试为TEST_ONLY/SYNTHETIC；真实COM7、USB控制线与现场终端人工观感仍HARDWARE_NOT_RUN。设备端DEVICE_FINALIZED与HOST_FILES_VERIFIED仅是不同范围的证据，不等于标定、抗断电或完整预警系统通过。土壤湿度/IMU坐标/降雨PWM仍未标定，Risk/报警/LoRa未整体整合，继续INTEGRATION_NOT_READY。

回退：关闭新控制台后可继续使用原ESP-IDF Monitor及第十五轮人工文档；固件没有变化。切勿同时占同一串口。没有自动改名、删除或恢复历史数据的脚本。
