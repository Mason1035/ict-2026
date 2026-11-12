# Atlas 板端局域网演示速查

链路：NODE-01 或 A 的 SD 回放 → 板端 Mosquitto → 平台 SQLite → 浏览器。以下假定板端代码已同步至 `/opt/ict-2026`，SSH 用户可写该目录；已按后端 README 准备板端 **Python 3.11+ / aarch64 venv 与依赖**、Mosquitto 2.0.11。Ubuntu 22.04 自带 Python 3.10 不满足要求；不要复制 PC 的 venv。这里不安装依赖、不上传原始采集文件。命令中的 IP、账号、目录按现场替换，仅在可信演示 LAN 使用 HTTP/1883。

## 1. PC 构建页面并复制

已有 node_modules，在 PC 仓库根目录（Bash / WSL）：

```bash
BOARD=ubuntu@192.168.1.20 BOARD_REPO=/opt/ict-2026 bash scripts/build-and-push-dist.sh
```

脚本只执行 `npm run build` 和 `rsync`；板端不需要 Node。板端代码也必须包含本次后端与 deploy 改动，dist 不能替代代码同步。

## 2. 板端启动 Broker 和平台

以下全部在板端 SSH 的同一 Bash 会话执行。`0.0.0.0:1883` 同时服务 LAN 与 `127.0.0.1:1883`，不要重复添加占用同端口的 IPv4 listener；已有 conf.d 配置需先合并。`-c` **仅首次创建密码文件使用**，随后新增/改密码不带 `-c`。

```bash
cd /opt/ict-2026
platform_backend/.venv/bin/python -c 'import sys, geohazard_platform, paho.mqtt.client; assert sys.version_info >= (3,11)'
sudo install -m 644 deploy/board/geohazard.conf /etc/mosquitto/conf.d/geohazard.conf
# 首次创建；若文件已有用户，去掉 -c。两次交互输入密码。
sudo mosquitto_passwd -c /etc/mosquitto/geohazard.passwd node01
sudo mosquitto_passwd /etc/mosquitto/geohazard.passwd platform
sudo chown root:mosquitto /etc/mosquitto/geohazard.passwd
sudo chmod 640 /etc/mosquitto/geohazard.passwd
sudo systemctl enable mosquitto
sudo systemctl restart mosquitto

sudo install -d -m 750 /etc/geohazard
sudo install -d -m 700 -o "$(id -un)" -g "$(id -gn)" /var/lib/geohazard
TOKEN=$(platform_backend/.venv/bin/python -c 'import secrets; print(secrets.token_hex(32))')
sudo install -m 600 deploy/board/platform.env.example /etc/geohazard/platform.env
printf '%s\n' "GEOHAZARD_HOST=0.0.0.0" "GEOHAZARD_PORT=8000" \
  "GEOHAZARD_API_TOKEN=$TOKEN" "GEOHAZARD_DEMO=0" \
  "GEOHAZARD_DATA_DIR=/var/lib/geohazard" "GEOHAZARD_ACL=auto" | sudo tee /etc/geohazard/platform.env >/dev/null
# 使用当前已准备好 venv / Ascend 权限的板端用户运行；路径固定 /opt/ict-2026。
sed -e "s/^User=.*/User=$(id -un)/" -e "s/^Group=.*/Group=$(id -gn)/" \
  deploy/board/geohazard-platform.service | sudo tee /etc/systemd/system/geohazard-platform.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now geohazard-platform
curl --fail -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/api/v1/health
printf '\n浏览器访问密钥（仅保存到当前会话）：%s\n' "$TOKEN"
```

从同 LAN 浏览器打开 `http://192.168.1.20:8000` → **连接设置** → API 地址 `/api/v1`，填写上面的访问密钥。现有前端用 sessionStorage 保存，所有 API/图片经 Bearer 请求；关闭会话后重新输入。静态页面可直接打开，API 必须认证。非 loopback `GEOHAZARD_HOST` 没有 token 会拒绝启动。systemd wrapper 自动加载存在的 `/usr/local/Ascend/ascend-toolkit/set_env.sh`，默认关闭演示，不安装、不构建；NPU 不可用时独立降级，不影响接入。

## 3. 配置 MQTT 连接器

页面 **配置与接入 → 新增**：格式 `标准 v2 遥测`，来源 **REAL**，用途 **OPERATIONAL（实时设备）**，Broker **127.0.0.1**，端口 **1883**，站点 **SITE01**，Topic **zhifang/v2/SITE01/+/telemetry**，用户 **platform**、对应密码，不启用 TLS，勾选启用。这个地址是后端到本板 Broker，不是 ESP32 的目标地址。点击测试，确认 CONNACK/SUBACK 与接入计数。

回放建议另建连接器：站点 **REPLAY-LAB**，Topic **zhifang/v2/REPLAY-LAB/+/telemetry**，用途 **TEST_ONLY**，其他同上。保留独立 `REPLAY-NODE01` 身份；PR #19 的 REAL_REPLAY 标记也会强制隔离为 TEST_ONLY，不能推进正式 latest 或告警。

## 4. 保底：A 的电脑回放真实 SD 三件套

在有现成后端 venv 的 A 的电脑上，用实际包含同名 `.CSV/.BEG/.END` 的目录；无需把原始文件复制到板端或仓库。不要用 embedded broker：

```bash
cd /path/to/ict-2026
read -rsp '板端 node01 MQTT 密码: ' GEOHAZARD_MQTT_PASSWORD; echo
export GEOHAZARD_MQTT_PASSWORD
platform_backend/.venv/bin/python scripts/replay_sd_to_mqtt.py \
  '/path/to/read-only/SD_SESSION' --csv N0000001.CSV \
  --host 192.168.1.20 --port 1883 --username node01 \
  --site-id REPLAY-LAB --device-id REPLAY-NODE01 --frame-hz 1 --speed 1 --loop
unset GEOHAZARD_MQTT_PASSWORD
```

`--csv` 改为实际文件名。Ctrl+C 停止；也支持 `--password`，优先用环境变量避免进入命令历史/进程参数；回放日志密码已脱敏。先用同一命令加 `--dry-run --max-frames 2` 可离线核对 v2，不连接 Broker。默认不发布 AIN2，始终保留 risk=null 与 REAL/TEST_ONLY。端点之外会裁剪并标记，不能当成真实含水率。

## 5. 真正实时：A 在自己的固件工作区配置（本文只记录，不修改固件）

以下口径核对自 `origin/李青原:firmware/node01/components/node_comm/{Kconfig,network.cpp,identity.cpp}`。A 使用其已配置 ESP-IDF 5.5.x 环境与分支，进入 `firmware/node01` 后 `idf.py menuconfig` → **NODE-01 communication → Enable provisioned Wi-Fi/MQTT**，确认 `CONFIG_NODE01_NETWORK_ENABLE=y`，再 `idf.py build`。不要把凭据写入 sdkconfig 或提交仓库。

NVS 命名空间 **node01_net** 的六个键均为 **string** 且都必须存在：`ssid`（非空，≤32 字节）、`psk`（开放 Wi-Fi 可空，否则 8–63 字节）、`uri`（如 `mqtt://192.168.1.20:1883`，≤191 字节，不允许 `@` 内嵌凭据）、`user`（非空，≤64 字节）、`pass`（非空，≤128 字节）、`site`（非空，≤64 字节，无控制字符和 `/+#`，与连接器一致）。不要使用企业 Wi-Fi 登录页；现场提供可接入的 Wi-Fi。`mqtts://` 需要固件启用证书 bundle，不得关闭校验。

身份命名空间 **node01_id** 必须预置 **u64** 键 **last_boot**。启动加载旧值、提交 `old+1` 并回读成功才允许发布；旧值范围 `0..9007199254740990`，seq 从 1 开始。全新、从未发布过的设备可由 A 复核后首次预置 0；**已使用设备必须保留其原计数，不能重新置零或刷回旧 NVS 备份**。缺失/损坏会 `IDENTITY_BLOCKED`，代码不自动初始化或擦除。

下面仅用于 **首次配网、从未发布过的设备**。在 A 的电脑临时目录生成 NVS，实际使用设备须通过保留既有 `last_boot` 的配网流程更新，不能执行该整分区覆盖示例。命令使用构建产物解析 NVS 地址和大小，不猜 Flash 偏移：

```bash
# 当前目录 firmware/node01，已 idf.py build；示例 Bash，Windows 可在 IDF 对应环境执行同等命令。
PORT=/dev/ttyACM0                  # 换成实际串口
PROVISION_DIR=$(mktemp -d)
chmod 700 "$PROVISION_DIR"
cat > "$PROVISION_DIR/node01.csv" <<'CSV'
key,type,encoding,value
node01_net,namespace,,
ssid,data,string,REPLACE_WIFI_SSID
psk,data,string,REPLACE_WIFI_PASSWORD
uri,data,string,mqtt://192.168.1.20:1883
user,data,string,node01
pass,data,string,REPLACE_MQTT_PASSWORD
site,data,string,SITE01
node01_id,namespace,,
last_boot,data,u64,0
CSV
# 在临时 CSV 中替换凭据；含逗号/引号时按 CSV 引用规则填写。
python "$IDF_PATH/components/partition_table/gen_esp32part.py" \
  build/partition_table/partition-table.bin "$PROVISION_DIR/partitions.csv"
read -r NVS_OFFSET NVS_SIZE < <(python - "$PROVISION_DIR/partitions.csv" <<'PY'
import csv, sys
rows = [r for r in csv.reader(open(sys.argv[1])) if r and not r[0].lstrip().startswith('#')]
r = next(r for r in rows if r[0].strip() == 'nvs')
size = r[4].strip()
size = int(size[:-1])*1024 if size.upper().endswith('K') else int(size, 0)
print(r[3].strip(), hex(size))
PY
)
python "$IDF_PATH/components/nvs_flash/nvs_partition_generator/nvs_partition_gen.py" \
  generate "$PROVISION_DIR/node01.csv" "$PROVISION_DIR/node01.bin" "$NVS_SIZE"
idf.py -p "$PORT" flash
python -m esptool --chip esp32s3 --port "$PORT" write_flash "$NVS_OFFSET" "$PROVISION_DIR/node01.bin"
rm -rf "$PROVISION_DIR"           # 凭据不留在仓库或终端日志
idf.py -p "$PORT" monitor         # 复位后看 WIFI / MQTT_CONNECTED；Ctrl+] 退出
```

串口 `MQTT_CONNECTED` / enqueue 只是设备链路状态，不等于 Atlas 持久化确认；需网页入库计数和 seq 持续增加验证。固件每秒发布一次、QoS0、非 retained；可能丢包，SD 保留作为回放后备。`edge_online=false` 目前是固件原值，不代表平台没收到。

## 6. 页面与快速排障

选择 REAL 的 SITE01/NODE-01 或 REPLAY-LAB/REPLAY-NODE01：查看原始 ADC/双 IMU 曲线、入库历史 JSON、临时风险特征/原因和序数趋势。正式风险卡仍按设备上报显示，risk=null 时继续未知；临时结果独立保存，`status=PROVISIONAL`、`calibration_version=null`、`fusion_eligible=false`、`uncalibrated, not a formal alarm`，不写 alarms。前 10 个有效 IMU 样本预热，2 秒短窗至少 2 点；断流/乱序标记质量问题；重启后从数据库恢复同 boot 的状态。

阈值：方向角、振动/陀螺参考数值来自已提交 `provisional-v1-r4.json`；1 Hz 无法执行其高频覆盖、STA/LTA、持续时间规则。演示等级、湿度指数阈值和 WARNING 倍数集中在 `provisional_config.py`，逐条记录来源。B 的两个 2026-11-12 候选/离线复核文档均说明不可加载为正式标定；只按本演示请求借用 AIN0/1 AIR/WATER 参考，AIN2 排除，IMU 不套候选校正。分级为演示观察，不是灾害概率或正式告警，NORMAL 不证明安全。

```bash
# 板端排障；若开启 ufw，只放行实际演示网段（按现场修改）。
sudo ufw allow from 192.168.1.0/24 to any port 1883 proto tcp
sudo ufw allow from 192.168.1.0/24 to any port 8000 proto tcp
sudo ss -lntp | rg ':1883|:8000'
sudo journalctl -u mosquitto -u geohazard-platform -n 80 --no-pager
sudo systemctl restart geohazard-platform
```

ESP32/A 电脑目标必须填 **板子的 LAN IP**，不能是 `127.0.0.1`；后端同板订阅才填 loopback。401：浏览器密钥；403：同源 API 地址/Origin；连接拒绝：listener/防火墙；认证失败：Mosquitto 两个用户密码及文件权限；页面空白：dist 路径/代码版本；无遥测：topic 中 site 与 payload 一致、连接器启用且 source=REAL；`IDENTITY_BLOCKED`：检查既有 NVS counter，禁止盲目清零。日志 `Provisional risk failed` 只影响临时计算，先确认遥测入库；检查规则 JSON 是否随代码同步。
