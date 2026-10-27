# 桌面终端（KFlow Terminal）

一块只属于某个 KFlow 账号的小屏。它显示的内容全部来自你的账号，它消耗的每次同步都走既有的会话/令牌鉴权链路。

首版的定位是**只做显示**——不说话、不做动画。触摸、常驻时钟、中文上屏、无线升级、主动提醒这些是后来一版版加上去的（见 §9），但那条底线没变：**屏幕上的每个数字都必须能追到一个接口，且写操作只有签到这一个。**

目标始终没变：一块放在桌上、三个月不用管、抬头就能看到积分和未读的屏。

---

## 1. 范围

| 维度 | 当前（v0.7.5） | 明确不做 |
|---|---|---|
| 数据 | 积分余额、连续活跃、未读通知、勋章数、发帖数、最新碎碎念、最新帖子 | 下单、发帖、投票、私信 |
| 交互 | 触摸（校准后分带：签到/翻页/刷新）、BOOT 按键、新通知自动弹页 | 旋钮、语音、多级菜单、左右滑 |
| 网络 | 局域网 HTTP，或 HTTPS + 自签证书；**OTA 无线升级** | 公网直连、TLS 双向认证、AP 配网 |
| 显示 | 单色版式，240×320 竖屏；中文由服务端渲染成 1-bit 位图 | 彩色主题、图表、动图 |

> 「剥离彩屏」指的是**不用颜色编码信息**，不是换硬件：屏幕仍是 ILI9341，只是版式按单色排版设计，即便将来换墨水屏也不用重排。

---

## 2. 数据流

```
ESP32-S3 ──(1) POST /api/terminal/pair/start──▶ 返回 6 位配对码
   │                                            （屏幕显示，10 分钟有效）
   │
浏览器 /terminal ──(2) POST /api/terminal/pair/confirm──▶ 绑定到当前登录用户
   │                                                    签发令牌，明文暂存
   │
ESP32-S3 ──(3) POST /api/terminal/pair/poll──▶ 一次性取回令牌，写入 NVS
   │                                          服务端立即清空明文
   │
ESP32-S3 ──(4) GET /api/terminal/summary──▶ 摘要 JSON（Bearer 令牌）
                每 refresh_seconds 一次，只读
```

关键设计：**令牌明文只在「确认绑定 → 固件首次轮询」这个窗口内存在于服务端**，下发即清空。设备丢了、刷了机，令牌不会留在服务器上等人捡。

---

## 3. 接口

所有设备接口用 `Authorization: Bearer <token>`，显式豁免 CSRF（终端没有 Cookie）；浏览器接口走会话 + CSRF。

| 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|
| POST | `/api/terminal/pair/start` | 无（按 IP 限流 60 次/小时） | 生成配对码；**未过期的码会原样复用**（不计限流） |
| POST | `/api/terminal/pair/poll` | 配对码 | 返回 `pending` / `active`（含令牌，仅一次）/ `expired` / `revoked` |
| POST | `/api/terminal/pair/confirm` | 用户会话 | 输入配对码完成绑定；重绑会换掉旧令牌并通知原主人 |
| POST | `/api/terminal/unbind` | 设备令牌 | 设备自解绑（长按重置时调用），之后可重新配对 |
| GET | `/api/terminal/devices` | 用户会话 | 我的终端列表（最多 50 台） |
| POST | `/api/terminal/devices/revoke` | 用户会话 | 吊销：清空令牌摘要，终端下次请求即 401 |
| GET | `/api/terminal/summary` | 设备令牌 | 屏幕所需的全部数据 |
| POST | `/api/terminal/checkin` | 设备令牌 | 签到（今天首次有效访问）；**按天幂等**，重复调用返回 `awarded: false` |
| GET | `/api/terminal/textboard?slot=murmur\|topic` | 设备令牌 | 中文正文画成的 1-bit 位图板（**裸二进制**，非 JSON） |
| GET | `/api/terminal/firmware/latest?current=0.6.2` | 设备令牌 | 该不该升级；判断在服务端，设备只认 `update_available` |
| GET | `/api/terminal/firmware/download?version=0.6.2` | 设备令牌 | 原样吐出 bin（不压缩、不分块），附 `X-Firmware-MD5` |
| POST | `/api/terminal/firmware/report` | 设备令牌 | 升级完回执；`result=ok` 才更新 `device.firmware` |

### `GET /api/terminal/summary` 响应

```json
{
  "ok": true,
  "server_time": "2026-10-26T15:40:00+00:00",
  "epoch": 1793038800,
  "user": { "username": "kieran", "display_name": "Kieran" },
  "points": { "balance": 128, "total_earned": 200, "total_spent": 72,
              "reputation_level": 3, "streak": 7 },
  "notifications": {
    "unread": 2,
    "latest_id": 9137,
    "items": [{ "id": 9137, "type": "badge", "label": "BADGE", "is_read": false,
                "title": "获得「初次发声」勋章", "created_at": "..." }]
  },
  "community": { "topics": 12, "replies": 34, "likes_received": 56,
                 "badges": 5, "active_days": 41 },
  "checkin": { "done": false, "reward": 2 },
  "device": { "name": "书桌屏", "firmware": "0.4.1", "sync_count": 87 },
  "refresh_seconds": 300
}
```

`notifications.items` 最多 3 条，固件全存下来，第 4 屏一次列完。

`latest_id` 是**主动提醒的水位线**：设备自己存一份「上次见到的最新 id」，只有看到更大的数字才认为来了新的。取全表最大、不看已读状态——否则用户把通知读掉、id 退回去，设备会以为又来了一条。用 id 而不是时间戳，是因为 id 单调递增，不会因时区或时钟漂移倒退。

`items[].is_read` 让第 4 屏能逐条标出「哪几条是新的」——一屏三条，只给总数没用。

`checkin` 让屏幕自己判断要不要显示 `CHECK IN +2` 还是 `CHECKED IN`——日期判断留在服务端，终端没有 RTC，跨天自己算必然出错。**这一项不写进 NVS 缓存**：缓存是"上次看到的样子"，跨天就会撒谎。

### `POST /api/terminal/checkin` 响应

```json
{ "ok": true, "awarded": true, "points": 2, "balance": 8507,
  "streak": 8, "reward": 2, "done": true }
```

不新造积分事件，直接复用 `apps.points.services.award_daily_activity`——它靠 `user_daily_activity` 的 (user, date) 唯一约束实现按天幂等，所以屏幕连点、手机端同时点，都只会发一次分。所有写操作都在 `transaction.atomic()` 内（发分链路里有 `select_for_update`）。

`label` 是服务端折好的 ASCII 类型标签（`BADGE` / `REPLY` / `LIKE` …），固件不再维护一套中文→英文映射表。

`epoch` 是整数秒（UTC），设备靠它对时。不要指望 `server_time`：后端没配 `TIME_ZONE` 时 Django 输出 UTC，固件按字符串解析会差 8 小时。

### `GET /api/terminal/textboard` 响应

**不是 JSON，是裸二进制。** 位图走 JSON 要 base64，体积凭空涨三分之一。

```
u16 count                      块数
重复 count 次：
  u16 x, y, w, h, stride, color   color 是 RGB565
  stride*h 字节                   1 bit/像素，1 = 前景，行按字节对齐
```

`slot` 只认 `murmur`（最新一条碎碎念）和 `topic`（最新一条帖子），其它值一律 400。内容为空时返回占位文案（`还没有人发碎碎念`），**不返回空 body**——空 body 和"网络断了"在屏幕上是同一个样子：一片白。

**为什么在服务端画字。** 板子上的 TFT_eSPI 只编进了 ASCII 字库。另一条路是塞一套中文点阵进 flash：300KB 起步、只能覆盖子集，而且换行/避头尾/超长截断这些排版规则一旦写进固件，改一个字就要重烧一次。把「画字」搬到服务端以后，排版全在 `apps/terminal/textboard.py` 里，改完即生效。代价是每屏多一次 HTTP——一块 216 宽的 1bpp 位图约 4~5KB，局域网一两百毫秒。

几处实现上的讲究：

| 点 | 做法 | 为什么 |
|---|---|---|
| 极性 | 位=1 画前景色 | `drawBitmap` 只画 1 位、跳过 0 位，白底不重刷，看起来像"字浮上来" |
| 行对齐 | `stride = (w+7)//8`，服务端和固件必须一致 | 不一致会整块斜着画 |
| 颜色 | 每块自带 RGB565 | 标题墨色、正文墨色、作者行灰色，都在服务端定 |
| 溢出 | 超出高度时最后一行加 `…` | 宁可截断加省略，也不让半行字卡在屏幕边缘 |
| 避头尾 | `。，、；：？！` 不许落行首 | 中文排版里标点单独占一行最难看 |
| 字体 | 按 macOS / Linux / Windows 顺序找，可用 `settings.TERMINAL_CJK_FONT` 覆盖 | 换服务器不用改代码 |
| 没字体 | 返回 503 `no CJK font on server` | 屏幕上显示 `can't load`，比一屏豆腐块诚实 |

`stride` 和 `w` 的关系是硬约束：`216/8 = 27` 正好整除，所以现在没有行尾补齐位。改成非 8 倍数的宽度时要记住 `drawBitmap` 自己按 `(w+7)/8` 算跨度，不接受额外参数。

### `GET /api/terminal/firmware/latest` 响应

```json
{
  "ok": true,
  "update_available": true,
  "current": "0.6.1",
  "latest": "0.6.2",
  "version": "0.6.2",
  "size": 1235200,
  "md5": "120333ff4759f372cb7a9111357cd7c7",
  "built_at": "2026-10-27 15:22",
  "url": "/api/terminal/firmware/download?version=0.6.2"
}
```

已是最新时 `update_available=false` 且带 `reason: "already up to date"`；目录里没有任何 bin 时也是 false，但 `reason` 是 `no build published`——**两种情况必须能区分**，前者说明链路正常，后者说明你忘了把 bin 放进去。

`current` 不传就用服务端记着的 `device.firmware`。判断在服务端做，固件只回答"升/不升"：版本语义写两遍迟早两边不一致，而将来要加灰度、按设备分组、强制降级，也只需要改这里。

分发目录只认 `kflow_terminal-<主>.<次>.<补丁>.bin` 这一个形状（`uploads/firmware/`，可用 `settings.TERMINAL_FIRMWARE_DIR` 覆盖）。版本号是从文件名来的，**查版本是在清单里做字典查找，字符串根本不拼进路径**，所以 `version=../../etc/passwd` 只会得到 404。

---

## 4. 安全边界

1. **摘要只读**：`summary` 不写积分、不消费权益、不改变任何社区状态（有测试守着：`test_summary_is_read_only`）。
2. **写接口只有两个，都限定在"自己"**：
   - `POST /api/terminal/checkin` —— 只把「今天来过」记上并给分，不改内容、不发帖、不投票。
   - `POST /api/terminal/firmware/report` —— 只改自己那行 `device.firmware`，是设备自报"我现在跑几版"。`result=failed` 时连这个都不改。
3. **固件分发要令牌**：`latest` / `download` 都走设备令牌，`uploads/firmware/` 不经媒体路由暴露（实测直连返回 404）。固件里没秘密，但"谁能往那台设备推固件"必须有答案。
4. **一机一账号**：`TerminalDevice.user` 决定数据源，无法通过参数切换到别人的账号。
5. **令牌**：`secrets.token_urlsafe(32)`，库里只存 sha256 摘要 + 8 位前缀（便于用户在设备列表里辨认）。
6. **配对码**：6 位、去掉易混字符（`0/O`、`1/I/L`、`2/Z`）、10 分钟过期、只对未绑定设备有效。
7. **限流**：`pair/start` 按 IP 60 次/小时；未过期的码直接复用、不计配额，所以反复重启不会把自己锁死。固件失败时按 5→10→20…120 秒退避。
8. **吊销即时生效**：清空 `token_hash` 后，任何持旧令牌的请求都返回 401。
9. **传输**：局域网默认明文 HTTP（固件包有签名兜着，改包也装不进去）；公网走 `https://`，**从 v0.10.0 起校验证书链 + 主机名**（内嵌 GTS R4 / GTS R1 / ISRG X1 三张根），不再 `setInsecure()`。CA 轮换导致连不上时用串口 `l` 切宽松档，见 §7.11。
10. **固件来源**：v0.10.0 起 OTA 强制 ECDSA P-256 验签，清单里没有 `sig` 就一个字节都不写。私钥 `secrets/ota_signing_key.pem` 不入库、不部署；公钥烧在固件里，指纹可在串口 `v` 里核对。

---

## 5. 可调参数

写入 `SystemSetting`（后台「系统设置」，或直接改表），全部有安全默认值：

| Key | 默认 | 范围 | 作用 |
|---|---|---|---|
| `terminal.refresh.seconds` | 300 | 60–3600 | 终端刷新间隔，服务端下发 |
| `terminal.pair.ttl_seconds` | 600 | 60–1800 | 配对码有效期 |
| `terminal.pairing.enabled` | true | 布尔 | 关闭后禁止新设备配对（应急开关） |

---

## 6. 烧录

### 6.1 环境

- Arduino IDE 2.x + `esp32` 板支持包（Espressif）
- 板子选 **ESP32S3 Dev Module**，`USB CDC On Boot = Enabled`
- **Partition Scheme 选 `No FS 4MB (2MB APP x2)`**
- 库：**TFT_eSPI**（Bodmer）、**ArduinoJson 7.x**

分区这一步最容易踩坑，说清楚：真正的布局由 sketch 目录下的 **`partitions.csv`** 决定（core 的 prebuild 钩子里，`{build.source.path}/partitions.csv` 优先级最高，会盖掉菜单选项）。这个文件是双 6.25MB app 槽：

```
nvs      0x9000   0x5000
otadata  0xe000   0x2000
app0     0x10000  0x640000
app1     0x650000 0x640000
spiffs   0xc90000 0x360000
```

菜单里选 `Huge APP` 会得到单槽、OTA 根本没有落点；选 `Default 4MB` 的两个槽各只有 1.25MB，现在固件已经 1.23MB，一加东西就爆。所以统一用自定义表，菜单项只是为了让 core 报出一个合理的体积上限（2MB）——**别被那个 60% 迷惑，实际槽是 6.25MB**。

`nvs` 与 `otadata` 的偏移和旧表完全一致，所以换表后已校准的触摸参数（`tcal`）和配对令牌都还在。

命令行编译烧录（`arduino-cli` 用 Arduino IDE 自带的那份即可，不必另装）：

```bash
CLI="/Applications/Arduino IDE.app/Contents/Resources/app/lib/backend/resources/arduino-cli"
FQBN="esp32:esp32:esp32s3:CDCOnBoot=cdc,PartitionScheme=no_fs,PSRAM=opi,FlashSize=16M"

"$CLI" compile --fqbn "$FQBN" firmware/kflow_terminal
"$CLI" upload -p /dev/cu.usbmodem11301 --fqbn "$FQBN" firmware/kflow_terminal

# 只出 bin（给 OTA 用）：产物在 /tmp/ota_build/kflow_terminal.ino.bin
"$CLI" compile --fqbn "$FQBN" --output-dir /tmp/ota_build firmware/kflow_terminal
```

烧录前若串口被占用（`Resource busy`），先 `lsof -t /dev/cu.usbmodem11301` 拿到 PID 再 `kill`。编译占用基线：**1,235,047 B / 60%（占 2MB 名义上限）/ RAM 14%**。

注意 `partitions.csv` 不能带 UTF-8 BOM：`gen_esp32part.py` 只把首字符为 `#` 的行当注释，BOM 会让第一行变成非法数据行，报 `Field 'type' can't be left empty`。

### 6.2 配置

```bash
cp firmware/kflow_terminal/config.example.h firmware/kflow_terminal/config.h
```

填入 WiFi 与 `KFLOW_BASE`（**必须是电脑的局域网 IP**，写 `127.0.0.1` 只会指向板子自己）。

### 6.3 接线

**显示（9 根，必须）**

| ESP32-S3 | TFT 模块 |
|---|---|
| 3.3V / GND | VCC / GND |
| GPIO 10 | CS |
| GPIO 8 | RESET |
| GPIO 9 | DC |
| GPIO 11 | SDI (MOSI) |
| GPIO 12 | SCK |
| GPIO 13 | SDO (MISO) |
| GPIO 4 | LED |

**触摸（4 根，可选）—— 本机已接通并验证**

| ESP32-S3 | TFT 模块 | 说明 |
|---|---|---|
| GPIO 12 | T_CLK | 与屏幕 SCK 同一根总线，需并接 |
| GPIO 11 | T_DIN | 与屏幕 SDI(MOSI) 并接 |
| GPIO 13 | T_DO | 与屏幕 SDO(MISO) 并接 |
| GPIO 7 | T_CS | **必须独立**，不能与屏幕 CS 共用 |
| （不接） | T_IRQ | 轮询方式不需要中断 |

> 注意：模块上 `SDI/SDO/SCK` 与 `T_DIN/T_DO/T_CLK` 是**两组独立引脚**，只是内部接到同一条 SPI 总线上。所以要用面包板或一分二杜邦线，把 ESP32 的 GPIO 11/12/13 各扇出两路。漏接任意一根，XPT2046 都不会应答。

引脚定义在 `~/Documents/Arduino/libraries/TFT_eSPI/User_Setup.h`（`ILI9341_DRIVER`，240×320，`TOUCH_CS 7`）。

**判断触摸是否接通**：不用看屏幕，直接读串口状态报告里的 `touch` 行。

| 现象 | 含义 |
|---|---|
| `x=8191 y=8191`、`zeroXy` 接近 `samples` | 总线无应答：4 根线至少缺一根（MISO 读到 0x00/0xFF） |
| `zeroXy` 很低、`x/y` 在原位跳动、`z` 个位数 | 已接通，未被按下 |
| `pressed` 随按压增长、`z` 超过 150（实测可达 3489） | 正常工作 |
| `nowdown=1` | 此刻判定为按着；按住发一次、松开再发一次对比最直观 |

### 6.4 首次绑定

1. 上电 → **第一屏就是小 K**（不等网络，`setup()` 里先画首屏再连 WiFi）
2. 点一下屏幕（或按 BOOT）→ 屏幕显示 6 位配对码
3. 浏览器打开 `http://<局域网IP>:9000/terminal`，登录后输入配对码
4. 终端 3 秒内自动取到令牌，按一下 BOOT 进数据页

> 长按 BOOT 3 秒清除令牌重新配对；网页端「吊销」立即让终端失效。

### 6.5 串口诊断

固件带一层串口日志（`DEBUG_SERIAL 1`）。USB CDC 在电脑打开串口之前打印的内容会丢，所以除了上电横幅，还支持**从串口发任意一个字符，立刻回一份状态报告**：

```bash
stty -f /dev/cu.usbmodem11301 115200 raw
cat /dev/cu.usbmodem11301 &      # 先挂着读
printf '\n' > /dev/cu.usbmodem11301   # 再踢一脚
```

输出形如：

```
[wifi] failed ssid=PDCN (will retry quietly)
[wifi] connected ip=192.168.1.72 rssi=-30
--- kflow terminal ---
fw=0.6.2 mode=SPLASH page=0 device=esp32s3-kflow-desk
wifi=3 rssi=-34 ip=192.168.1.72 failed=0
token=yes len=43
snap.valid=1 balance=8507 unread=3
base=http://192.168.1.71:9000
ota running=app0@0x10000 size=6400K next=app1 failUntil=0
clock=ok now=15:23:42 cache=1 offline=0
touch[cal=1 compiled=1 tap=1 seen=0] samples=464 pressed=3 zeroXy=0
touch cal x=289..3580 y=376..3780 rot=1
touch nowdown=0
touch last x=0 y=3614 z=10
touch range x=0..613 y=2766..3731 z=2..135
layout title(f4)=91 title(f2)=52 clock(f2)=35 limit=172
board[murmur] valid=0 failed=0 bytes=16384 len=0 heap=265260
board[topic] valid=0 failed=0 bytes=16384 len=0 heap=265260
----------------------
```

`ota` 那行最值得看：`running=app0` 和 `next=app1` 必须是**两个不同的槽**。如果 `next=NONE`，说明分区表还是单槽的，OTA 根本没有落点——这种失败在 `Update.begin()` 里只会回一句 `no partition`，看不出全貌。`failUntil=1` 表示上一轮升级失败、正在 6 小时冷却里。

**指令**

| 发送 | 作用 |
|---|---|
| 任意字符 | 回一份状态报告 |
| `c` | 进触摸校准（等价于在首屏长按 BOOT 3 秒） |
| `r` | 清零触摸统计（接线前后对比用） |
| `d` | 读 ILI9341 芯片 ID，判断显示总线通不通（正常 `00 93 41`） |
| `s` | 立刻同步一次，顺便验证服务端 `epoch` 对时通路 |
| `t` | 进数据页（已在数据页则回到第 0 屏） |
| `p` | 翻一页；翻到中文页会顺带拉一次位图 |
| `g` | **读回屏幕像素**，统计非白点数——验证中文位图真画上去了 |
| `a` | **读回未读角标像素**，统计红色点数——验证提醒真的画上去了 |
| `o` | **立刻查一次新固件并升级**。绕过 24 小时间隔与失败退避，等于"现在就要升" |
| `k` | 连续采样统计闭眼帧比例，验证待机动画在跑（见 §7.8） |
| `m` | 读回立绘一列，反推呼吸位移到了第几档 |
| `b` | 强制闭眼 8 秒，配合 `n` 把闭眼帧 dump 出来看接缝 |
| `n` | 整屏 RGB565 回传，PC 端还原成 PNG |
| `w` | **扫一遍 2.4GHz 频段**：列出 SSID / 信道 / RSSI / 加密方式，并用 `*` 标出目标 SSID 是否在列表里 |
| `u` | **改服务地址**：随后发一行 `http://ip:port` 回车。写进 NVS，下次开机优先用它，不用重烧 |
| `i` | **触发配对**。正常靠点一下首屏，但屏幕/触摸坏了、或换服务端后令牌被清，串口是唯一还能用的入口。阻塞到配对成功或码过期 |
| `y` | 打印两页中文位图的结构摘要（块数、每块的 x/y/w/h/stride/color、`need` 与 `left`）+ 头 48 字节 HEX。用来区分"数据不对"和"画不对"（见 §7.10） |
| `v` | **验签自检**：用内嵌公钥验一条固定签名（`accept`）、把摘要翻一比特再验（`reject` 必须为 1），并打印公钥指纹。不联网也能证明验签链路可用（见 §7.11） |
| `l` | **切 TLS 严格/宽松**：严格档钉根 CA 校验链与主机名，宽松档 `setInsecure`。写 NVS。只在站点换 CA 导致连不上时用，切了每次开机都会打警告 |
| `x` | **单次跳过验签**（逃生口）：下一次 `o` 不校验签名直接安装，用一次自动关，不写 NVS。只在「验签在真机上挂了、OTA 永久升不上去、手边又没线」时用（见 §7.12） |

按 `mode=` / `token=` / `wifi=` 三行就能判断卡在哪一层：没画面看 `mode`，配对不看 `token`，请求失败看 `base` 和 `wifi`。`failed=0` 表示上次连网是成功的，`wifi=` 才是此刻的链路状态——这两者会短暂不一致，属正常。

`clock=` 行里，`cache=1` 表示内存里的摘要来自 NVS 而不是本次同步（首屏模式不主动拉数据，所以刚开机常是 1），`offline=1` 才是真的没网。

`touch` 四行：`xy` 是坐标层是否开启、`tap` 是点按层是否开启、`seen` 是否已经收到过真实触摸；`nowdown=1` 表示此刻判定为按着；`range` 的 min/max 就是四点校准要填的值。

`layout` 行是首屏排版的实测结果：`title(f4)` 若大于 `limit`，标题会自动降为 Font 2；`clock(f2)` 是时钟实际宽度。这行用来证明标题和时钟没有互相覆盖——不用靠眼睛猜。

> **`wifi=3` 但接口全挂，先看 `base=`，不要怀疑 WiFi。** 完整判据见 §7.9。

> 常见现象：首次 `[wifi] failed` 紧随一次 `[wifi] connected` —— 这块 AP 首次关联要 15–25 秒，属于正常，静默重连会补上。若一直 `failed`，先发 `w` 扫描（§7.9），别急着改 `WIFI_SSID`。

---

## 7. 屏幕版式

### 7.1 首屏（小 K）

上电第一屏永远是小 K——**包括还没配对、甚至连不上 WiFi 的时候**。点一下屏幕（或按一下 BOOT）才继续：没配对接配对流程，已配对进数据页。这是一个「有意的门槛」：屏幕不是监视器，是你抬头时它才说话。

```
┌────────────────────────────┐
│                          ● │  ● 收到过真实触摸才亮（C_ACCENT）
│        小 K 立绘            │  240 x 262 RGB565
│      （挥手 · 白底）         │  122 KB flash
│                            │
├────────────────────────────┤
│ HI, I'M K          21:46   │  ← 标题 Font 4 / 时钟 Font 2
│ tap: open            ( 3 ) │  ← 右侧红胶囊：未读数（v0.7 起）
│                     v0.7.0 │
└────────────────────────────┘
```

三条保证首屏看得见的硬规则：

1. **先画后连**：`setup()` 里 `showSplash()` 在 `connectWifi()` 之前，首屏通电即现，一帧都不等网络。
2. **掉线不重绘**：`loop()` 的静默重连走 `connectWifi(ms, false)`，不擦屏、不画 `Connecting`。旧版本每 15 秒用整屏 `Connecting` 盖住首屏 12 秒，是「看不到小 K」的真凶。
3. **提示随状态变**：`connecting`（还没结论）→ `tap: pair`（无令牌）→ `tap: open`（已配对）；触摸全关时才退回 `BOOT:`。

**标题与时钟必须互不侵入**：`tickClock()` 每秒用纸色 `fillRect` 擦除自己那一小块，一旦压到标题上，跳一分钟就会把字母啃掉一块。所以标题字号是**按实测字宽选的**（`tft.textWidth("HI, I'M K", 4)` 若超过 `SPLASH_CLOCK_X - 16` 就降为 Font 2），时钟起点由 `SPLASH_CLOCK_X` 常量统一供给 `drawSplash()` 和 `tickClock()`，两处不再各写一个坐标。

- 图片由 `scripts/gen_xiaok_splash.py` 从 `static/xiaok/welcome-portrait-v1.png` 生成，输出 `firmware/kflow_terminal/xiaok_splash.h`
- 换图只需替换源文件并重跑脚本，固件无需改动
- 数据页静置 `IDLE_TO_SPLASH_SECONDS`（默认 60 秒）自动回首屏，顺便当成屏保
- 首屏右下角有固件版本号（如 `v0.7.5`），烧完先看这行确认跑的是新固件
- 右上角绿点是触摸自检标记：**点一下屏幕再回来，绿点出现就说明触摸完全可用**
- 提示行右侧的红胶囊是未读数（v0.7 起）；首屏待机时每分钟自己去问一次，所以人不在也一样会亮
- `no wifi` 只在**真的连过并失败**后出现；刚上电那十几秒显示的是正常提示，不是故障

### 7.2 数据页

五屏共用一套头尾，中间换内容。右上角五个点表示当前在第几屏（实心=当前）；`KFLOW` 右边的红胶囊是未读数，五屏都在。

**第 0 屏 · 概览**

```
┌────────────────────────────┐
│ KFLOW (3)      ● ○ ○ ○ ○   │  ← (3) 未读角标，v0.7 起
├────────────────────────────┤  ← 112 分界线（同时也是签到带的下沿）
│ K POINTS      CHECK IN +2  │
│      128      streak 7d    │
├────────────────────────────┤
│ UNREAD   BADGES   TOPICS   │
│   2        5        12     │
├────────────────────────────┤
│ LATEST                     │
│ BADGE                      │
│ (see kflow web)            │
├────────────────────────────┤  ← 252 分界线
│ 21:46:21        sync 21:46 │  ← 左：走秒时钟  右：数据新鲜度
│ BOOT: back      tap sync   │
└────────────────────────────┘
```

**第 1 屏 · 社区数据**（`TOPICS / REPLIES / LIKES IN / ACTIVE DAYS / BADGES` 五行右对齐）
**第 4 屏 · 最新通知**（最多三条，标签用强调色，标题过宽自动截断；未读的那几条右侧点一颗红点）

主动提醒（角标语义、自动弹页、20 秒窗口）见 §7.7。

**第 2 屏 · 碎碎念 / 第 3 屏 · 最新帖子**：这两屏的正文是**服务端画好的位图**，屏幕上真的显示中文。版式见 §7.5。

页脚右侧那格是**数据新鲜度**，三态各有不同含义：

| 显示 | 含义 |
|---|---|
| `sync 21:46` | 本次真的从服务端取到了数据 |
| `cached 21:46` | 用的是 NVS 里上次存下的，服务端这次没应答 |
| `OFFLINE` | 连 WiFi 都没连上，数据完全是旧的 |

时钟只有在对时成功后才显示真实时间；对不上就老实显示 `--:--`，**不拿开机时长去推算**——显示错误的时间比显示空白更糟。

长按 BOOT 3 秒清除令牌重新配对；静置 60 秒自动回首屏。点按的行为见 §7.4。

### 7.2.1 时钟与离线缓存

设备本身没有 RTC 电池，掉电即失忆。时间来自两个源，都不额外依赖硬件：

1. **服务端 `epoch`**（首选）：`GET /api/terminal/summary` 里带一个整数秒，设备本来就要联网取摘要，顺手校准，零额外成本。
2. **SNTP 兜底**：`ntp.aliyun.com` / `ntp.tencent.com` / `pool.ntp.org`。

时区用 `setenv("TZ", "CST-8")` 固定为北京时间，与有没有网无关。

> 为什么不用 `server_time` 字符串：后端没配 `TIME_ZONE`，Django 默认输出 UTC（`+00:00`），固件按字符串算本地时间会整整差 8 小时。给一个 `epoch` 整数，时区问题就只剩设备侧一处。

离线缓存只存「看一眼就够」的 10 个字段（用户、时间戳、通知类型/标题、积分、未读、徽章、连续天数、主题数、回复数），序列化后约 160 字节，存在 NVS 的 `cache` 键。

**磨损保护**：NVS 擦写寿命约 10 万次，300 秒写一次一年就到顶。所以只在关键字段变化、或距上次落盘超过 1 小时时才真正落盘（`saveSnapshotCache()` 里比对指纹 + 时间戳）。

开机 `loadSnapshotCache()` 会把上次的数据读进内存，断网也能进数据页看到最后一眼的样子——只是页脚会明确标成 `cached` 或 `OFFLINE`，不伪装成新数据。

---

### 7.3 触摸

触摸拆成两层，各管一件事。这是刻意的：**「有没有按」和「按在哪里」难度差一个数量级**——后者要四点校准，前者只要线通。

| 开关 | 管什么 | 要校准 | 当前值 |
|---|---|---|---|
| `TOUCH_TAP_ENABLED` | 有没有按下去 | 不要，只看压力 | **1（已启用）** |
| `TOUCH_ENABLED` | 按在哪里（坐标） | 要，屏幕内划一圈即可 | `1`（编译进来；实际可用与否看 `g_calValid`） |

#### 第一层：点按（已启用，不需要校准）

`touchRawPressed()` 只读 XPT2046 的压力值 Z，不看坐标。实测数据：

| 状态 | Z |
|---|---|
| 安静（含毛刺） | 2 ~ 100 |
| 手指按住 | 几百 ~ 3489（实测峰值） |
| 线悬空 | 恒定 ~4000，且 X/Y 全 0 |

判据两道：

1. `X` 与 `Y` 不同时为 0 —— 排除 `T_DIN` 悬空时读到的假值
2. `TOUCH_Z_MIN`(150) < `Z` < `TOUCH_Z_MAX`(3950)

再叠两层防误触，缺一不可：

- **armed 门闩**：上电后必须先观察到一次「松手」才允许计数。悬空线上电就是「一直按着」，因此永远点不动——这正是当初整块关掉触摸想解决的问题，门闩把粒度放细了。
- **连续确认**：`TOUCH_TAP_STREAK`(2) 次采样（约 120ms）都超阈值才算按下，单点毛刺不会触发。

行为：

| 当前页面 | 点一下屏幕 |
|---|---|
| 小 K 首屏 | 有令牌 → 进数据页；无令牌 → 走配对流程 |
| 数据页，**未校准** | 翻到下一屏（不知道点在哪，只做最无害的事） |
| 数据页，**已校准** | 按 y 分三带：上签到 / 中翻页 / 下刷新（见 §7.4） |

BOOT 短按在数据页固定是「回小 K 首屏」——它不随分带变，所以永远有一条确定的路能退出。

**怎么判断触摸到底有效，不需要任何工具**：点一下屏幕，页面切走；再点一下，页面回来，而且首屏右上角多了一颗绿点。绿点只在 `g_touchSeen` 为真时绘制，也就是「真的收到过一次触摸」的持久证据。

#### 第二层：坐标（屏幕内校准，不用改代码、不用重烧）

用到「点某个区域执行某个动作」时才需要。

校准值**存 NVS，不写死在编译期**——校准天然是反复试的过程（划偏了要重来），写死意味着每改一次都要重烧一次。

| 开关 | 作用 | 当前值 |
|---|---|---|
| `TOUCH_ENABLED` | 把坐标层**编译进来** | `1` |
| `g_calValid` | 实际**有没有校准数据**（运行期，读 NVS） | 取决于有没有校过 |

`TOUCH_ENABLED` 只管编译，能不能用看 `g_calValid`。没校准数据时自动退回压力层，不会拿错坐标去判区域。

**两步操作，不用开电脑：**

1. **在小 K 首屏长按 BOOT 3 秒** → 进入 `CALIBRATE`
   （串口发 `c` 等价；首屏未校准时底部会提示 `hold BOOT: calibrate`，校准过就不再显示）
2. **10 秒内沿屏幕四条边划一圈**：一笔连划、尽量贴边、中途不抬手指

屏幕实时显示采样计数、进度条、原始 x/y/z。**计数在涨说明真的在采**；一直是 0 说明压力没到阈值（回 §6.3 查接线）。

10 秒到自动结算：

```
[cal] done hits=1268 x=318..3762 y=286..3800 -> ok
```

成功后写 NVS 并**自动切到坐标测试页**：点哪画哪，红色十字落在手指处就说明准了。按 BOOT 回首屏。

**失败会怎样**：`hits < 30` 或 X/Y 跨度小于 800 判 FAIL，**不写 NVS**（避免把好数据覆盖成坏数据），提示停 2 秒自动回首屏，重新长按再校。

**串口确认**：

```
touch[cal=1 compiled=1 tap=1 seen=1] ...
touch cal x=318..3762 y=286..3800 rot=1
```

`cal=1` 才是坐标层真的可用。

**两个已知限制**：

- 校准后 `touchTapped()` 走坐标层并**不再落到压力层**（否则一次触摸算两次）。想回纯压力层，清掉 NVS 的 `tcal` 键。
- `rotation` 目前固定 `1`。若十字左右或上下整体颠倒，改 `finishCalibrate()` 里的 `g_touchCal[4]` 再校一次。

### 7.4 分带交互（v0.4.1）

有了坐标，屏幕就不是「一块按钮」而是**三条横带**。分界线刻意落在页面里本来就有的两条横线上（`y=112`、`y=252`），所以不用背坐标——眼睛看得见边界。

| 带 | y 范围 | 点一下做什么 | 行内提示 |
|---|---|---|---|
| 上 | `0 ≤ y < 112` | **签到**：POST `/api/terminal/checkin`，成功后弹 `+2 K` | 概览屏右上 `CHECK IN +2` / `CHECKED IN`，页脚 `tap check-in` |
| 中 | `112 ≤ y < 252` | **翻页**：0→1→2→3→4→0 循环 | 页脚 `tap next`；头部五点显示当前屏 |
| 下 | `252 ≤ y < 320` | **刷新**：`syncNow()`，重画当前屏 | 页脚 `tap sync` |

**没校准时整套降级**：坐标拿不到，`tapY` 是 `-1`，于是只做「翻页」这一件事，页脚老老实实写 `tap: next` 而不是画三条骗人的带子。这也是为什么 `touchTapped(int*, int*)` 用 `-1` 表示"不知道点在哪"而不是 `(0,0)`——`(0,0)` 是个合法坐标，猜错就会一次误签到。

签到结果的四种回执（都在同一个白底描边卡片里显示 1.3 秒后自动重绘）：

| 卡片 | 触发条件 |
|---|---|
| `+2 K / checked in today` | 服务端 `awarded: true` |
| `ALREADY / come back tomorrow` | 今天已签（本地已知时**不走网络**，直接提示；服务端返回 `awarded: false` 也走这条） |
| `NO SIGNAL / no connection` | `httpCall` 返回负数 |
| `NO SIGNAL / http 401` | 令牌被吊销，需要重新配对 |

签到成功后内存里的 `balance` / `streak` 直接更新并重绘，不必再打一次 `summary`——服务端已经把最新值随响应返回了。

### 7.5 中文页（v0.5.0）

第 2、3 屏显示最新一条碎碎念和最新一条帖子，**屏幕上真的是中文**，不是占位符。

```
第 2 屏 · 碎碎念                 第 3 屏 · 最新帖子
┌────────────────────────────┐  ┌────────────────────────────┐
│ KFLOW          ○ ○ ● ○ ○   │  │ KFLOW          ○ ○ ○ ● ○   │
├────────────────────────────┤  ├────────────────────────────┤
│ 碎碎念                      │  │ 最新帖子                    │  ← 服务端画的绿色小标
│ @kieran · 12 分钟前         │  │ 人多的人                    │  ← 标题 18px
│                            │  │ @admir · 17 小时前          │
│ 今天把中文弄上屏了。        │  │                            │
│ 服务端画好位图再传下来，    │  │ 1111                       │  ← 正文 14px
│ 板子上一个中文字库都没有。  │  │                            │
├────────────────────────────┤  ├────────────────────────────┤
│ 14:32:07        sync 14:32 │  │ 14:32:07        sync 14:32 │
└────────────────────────────┘  └────────────────────────────┘
```

**所有文字（包括绿色小标、作者行、相对时间）都由服务端渲染成位图**，固件只负责把块贴到指定坐标。这样加一屏中文内容不用动固件，改文案也不用重烧。

取图时机与缓存：

| 场景 | 行为 |
|---|---|
| 首次翻到该屏 | 先铺骨架（`loading...`）→ 拉位图 → 重画 |
| 90 秒内再翻回来 | 直接用 PSRAM 里的缓存，不发请求 |
| 超过 90 秒 | 重新拉（旧内容先显示，取到再换，不闪空白） |
| 摘要刷新成功 | 只把两页标成过期，**不立刻重取**——翻到才拉 |
| 拉取失败 | 屏上打 `can't load` + `tap again to retry` |

`BOARD_TTL_MS` 取 90 秒而不是跟摘要的 300 秒对齐：翻页是人的动作，手上点一下却看到五分钟前的内容会很别扭。

内存走 PSRAM（`ps_malloc`，失败退回 `malloc`）。实测两块各 16KB 缓冲，内部 RAM 完全没动（`heap` 前后都是 265KB）。

**验证办法**：串口 `p` 翻页、`g` 读回像素：

```
[board] murmur http=200 bytes=5087
[ink] page=2 sampled=800 ink=22
[board] topic http=200 bytes=4883
[ink] page=3 sampled=800 ink=30
```

`[board] http=200 bytes=5087` 只证明字节到了；`[ink]` 是读回屏幕像素统计出来的非白点数——**全 0 说明根本没画上去，接近 800 说明位极性反了**（整块被涂成前景色）。这两个数只有几十分之一才是对的。

串口指令全表见 §6.5。

### 7.6 无线升级（v0.6.x）

板子摆在桌上，不该为了改一行字被拔来拔去。做完这一版之后，**USB 线只在第一次上电时插过**。

```
开机 90 秒 ──► GET /firmware/latest?current=0.6.2
                    │
        update_available=false ──► 什么都不做，24 小时后再问
                    │true
                    ▼
        GET /firmware/download?version=0.6.3
                    │  流式，边收边写，不进内存
                    ▼
        Update.begin(size) ──► 拿分区容量比对，装不下当场拒
                    │
                    ▼
        写另一个 app 槽 ──► 每 1% 刷一次进度条
                    │
                    ▼
        Update.setMD5 + end() ──► 摘要不符就不切分区
                    │ok
                    ▼
        POST /firmware/report {version,result:ok} ──► ESP.restart()
```

**三个安全点，缺一个都不敢让它自己刷：**

1. **版本判断在服务端**。固件只读 `update_available`，不自己比大小——版本语义写两遍迟早两边不一致，将来加灰度/强制降级也只需改 Python。
2. **摘要校验**。v0.6.x 用的是 `Update.setMD5()`，挡住的是「下到半个文件就重启」；**v0.10.0 换成 ECDSA 验签**，因为 MD5 和包走同一条链路，能改包的人也能改摘要（详见 §7.11）。摘要不符时 `end()` 不执行，分区不切换。
3. **失败退避 6 小时**。连着失败通常是分区或网络问题，立即重试只是刷日志。

**实测过的三条路径（真机，不是推演）：**

| 场景 | 串口输出 | 结果 |
|---|---|---|
| 正常升级 | `written 1235200 bytes, md5 ok` → `boot fw=0.6.1` | app0 → app1，NVS 全保留 |
| 已是最新再触发 | `check latest=0.6.2 avail=0` | 不下载，不重启 |
| **坏包**（同尺寸随机字节） | `write failed at 4096` | 设备仍跑老版本，`failUntil=1`；坏包写过一半的槽下次仍能正常覆盖 |

坏包那次值得说明：它的大小和真固件一模一样，所以 `Update.begin()` 的体积检查放行了，是镜像格式校验在第一块 4KB 就拦下来。**这正是为什么不能只靠体积和文件名判断一个固件能不能用。**

三处入口：

| 入口 | 时机 |
|---|---|
| 开机 90 秒后 | 自动查一次（避免和首屏联网、配对抢同一条 TCP） |
| 每 24 小时 | 自动再查 |
| 串口 `o` | 立刻查并升，绕过 24 小时间隔和失败退避 |

**升级期间屏幕会全屏显示 `UPDATING 0.6.3` + 进度条 + `do not unplug`**。不是弹个小框：这一刻设备在改自己的固件，断电就废，必须明确告诉人别碰。进度条上还印着已下载 KB 数——只画百分比的话，你分不清是慢还是停了。

**OTA 之后 NVS 完好**，这一点实测了三次（app0→app1→app0）：`token=yes`、`cal=1`、校准值 `x=289..3580 y=376..3780` 一次都没变。不用重新配对，也不用重新校准。

`PartitionScheme` 相关的坑见 §6.1——换分区表那一次必须插线，也就是**最后一次插线**。

**发布一个新版本的全部操作：**

```bash
# 1. 改版本号
sed -i '' 's/"0.6.2"/"0.6.3"/' firmware/kflow_terminal/config.h

# 2. 编出 bin
CLI="/Applications/Arduino IDE.app/Contents/Resources/app/lib/backend/resources/arduino-cli"
FQBN="esp32:esp32:esp32s3:CDCOnBoot=cdc,PartitionScheme=no_fs,PSRAM=opi,FlashSize=16M"
"$CLI" compile --fqbn "$FQBN" --output-dir /tmp/ota_build firmware/kflow_terminal

# 3. 扔进分发目录（文件名必须是约定形状，否则查不到）
cp /tmp/ota_build/kflow_terminal.ino.bin \
   uploads/firmware/kflow_terminal-0.6.3.bin
```

剩下的事设备自己在一天内完成。想立刻推给板子，串口发 `o`。

### 7.7 主动提醒（v0.7）

前面几版设备都是「我去看它」：未读 3 条它一声不吭，你得翻到第 4 屏才看得见。这一版让它会说话，做的是三件事。

**一、未读角标常驻**

- 首屏：立绘下方、提示行右侧一颗红胶囊，里面是未读数。
- 数据页：`KFLOW` 右边同一个胶囊，五屏都在。

数字封顶显示 `99+`。红色是这块屏上唯一的红（`C_ALERT = 0xF800`），所以它一眼就能被瞥见——放在桌上一米外看，描边是看不见的，实心色块才行。

**二、首屏不再是聋的**

首屏原本只在开机时同步一次，于是「摆在桌上没人碰」恰恰是最聋的状态。现在补了一条低频心跳：

| 状态 | 轮询间隔 |
|---|---|
| 有未读 | 60 秒 |
| 没有未读 | 5 分钟 |

轮询只改角标那一小块（`fillRect` 92×19 再画），**不整屏重绘**——重发 125KB 立绘要 150ms，每分钟闪一次比不显示还糟。

**三、新内容到达时自己亮起来**

判断靠 `latest_id` 与本地水位线 `seen`（存 NVS 的 `nid` 键）：

```
latest > seen && unread > 0  →  弹到通知页，20 秒后退回首屏
```

三条边界条件，都是踩过之后才想清楚的：

| 情况 | 行为 | 为什么 |
|---|---|---|
| 第一次运行（`seen == 0`） | 只建基线，不弹 | 那堆未读是"以前就有"，不是"刚刚到"。刚配对完就抢屏是撒谎 |
| 人正在数据页操作（30 秒内有输入） | 只亮角标，不切页 | 正读着碎碎念被拽走，比不提醒更烦。红点已经亮在头上了 |
| 开机首次同步 | 只建基线，不弹 | 角标已经把这批未读摆在首屏上了，再弹一次是重复打扰 |

窗口内任何输入都会立刻作废提醒窗口（`g_attnUntil = 0`）；窗口结束时如果还停在通知页就回首屏，人已经翻去别处就不打扰。

**「看过」和「读过」是两件事，别混**

| 概念 | 存储 | 作用 |
|---|---|---|
| `seen` 水位线 | 设备 NVS | 判断"这一条我是不是第一次见"，决定要不要主动弹 |
| `unread` 未读数 | 服务端 | 红色角标跟着它走，**读了才会消失** |

所以会出现「已经弹过、角标还在」的状态——这是对的。设备不知道你在网页上读没读，它只知道自己提醒过了。想清掉角标，去网站把通知读掉，下次同步就没了。

**实测（真机，不是推演）**

```
首屏 + 新通知      [notice] new id=13 (seen=12) unread=5
                  [notice] pop to notice page, 20s
                  fw=0.7.5 mode=DATA page=4 attn=1
20 秒后            fw=0.7.5 mode=SPLASH  attn=0
数据页内来新通知    [notice] new arrives while busy -> badge only
                  fw=0.7.5 mode=DATA page=4 attn=0     ← 没被拽走
全部标为已读后      [alert] unread=0 nonwhite=0 px(96,18)=0xFFFF
```

最后一行是靠读回像素证明的，不是靠"看日志以为画上了"。而且这次栽了个跟头：**SPI 屏读回的 RGB565 是字节交换的**——画进去 `0xF800`，读回来是 `0x00F8`。第一次探针只比原值，得到 `header_red=0`，差点误判成"没画"。现在探针两种字节序都认。

调试探针本身也踩了同一个坑两次：`uint16_t row[64]` 却按宽度 92 读、`row[96]` 却按 120 读，两次都踩穿栈让板子重启。**读缓冲区要按最宽的那次读取来定，不是按第一次用的宽度。**

### 7.8 待机动画（v0.8.0）

小 K 原本是一张 240×262 的静态立绘。要让它"活着"，最直觉的做法是烤几帧序列图轮着贴，但**一帧就是 122KB**：三帧多占 366KB flash，而且每帧 `pushImage` 要 25ms，帧率上不去，全屏重贴还会闪。

所以拆成两层，各自只动该动的那一点：

| 层 | 动什么 | 单次代价 | 节奏 |
|---|---|---|---|
| 呼吸 | 整张立绘上移 0~3px | 122KB / ~25ms | 每 360ms 一档，8 档一循环（≈2.9s） |
| 眨眼 | 只重贴两眼各 21×23 的小块 | ~1KB / <1ms | 闭 110ms，间隔 2.6~7.2s，20% 概率连眨 |

**呼吸为什么不新增数据**：位移只是改变读取起点。`pushImage(0,0,W,H-dy, xiaok_splash + W*dy)` 直接指向源数组中间，省掉 122KB 的 memcpy；露出来的底部 dy 行用原图最后一行补齐。只往上移是因为立绘底部是身体截面，往下移会啃掉一截；往上移露出的顶边本来就是白背景。

**呼吸会不会闪**：相邻两帧只差 1px，SPI 逐行扫描的中间态看不出来。真机上换成 3px 峰值往复也没有可见撕裂。

**眨眼帧哪来的**：`scripts/gen_xiaok_face.py` 从同一张源图合成。三件事缺一不可——

1. **掩膜**：找出眼睛像素。只看"跟肤色差多少"不够，虹膜上缘的偏白高光和睫毛上方的淡灰蓝眼影都会漏判，闭眼后留一片灰斑。补一条 `b > r + 4` 的偏冷判定。
2. **修补**：扩散填充，让眼眶变成连续的皮肤。**只吸收"像皮肤"的邻居**——最早不限来源，结果额头的纯白高光被当成皮肤扩散进眼眶，真机上看着像翻白眼；后来还得加 `r > b + 8` 把纯白挡在外面。
3. **肤色参考值**：取框**外**、偏暗的三分位。按行取中位数会被虹膜占满的那几行污染成蓝灰；取中位数又会被额头高光抬到接近纯白。

**闭眼线**：中间低两端高的弧（`LID_DIP = 4.2`），端点收细——等宽画过去会在眼角留下两个方头，放大看像贴了两块黑胶布。

**与其它状态的协调**：

- 呼吸重贴整屏会把闭着的眼睛冲回睁开态，所以重贴后若 `g_blinkState` 为真，要补贴一次闭眼帧。
- 眨眼只停 110ms，人手动敲命令根本抓不住，探针必须**在采样循环里继续喂 `idleAnimTick()`**——第一版没喂，动画被阻塞定格在睁眼，统计永远是 0，假阴性了一次。
- `g_otaRunning` 期间动画让路，SPI 留给 flash 写入。
- 只在 `MODE_SPLASH` 跑。数据页文字密度高，整屏位移会把阅读区晃得难受。

实测（`fw=0.8.0`，USB 烧录后串口回读）：

```
[anim] blink samples=130 closed=14 (10%) open_err=3485 closed_err=0 dy=2
[anim] frame=0 dy=3 err=0 (firmware says 3)
[anim] frame=4 dy=2 err=0 (firmware says 2)
[anim] frame=26 dy=0 err=0 (firmware says 0)
dy 覆盖: [0, 1, 2, 3]
```

`closed_err=0` 和 `err=0` 是重点：读回的像素与闭眼帧、与位移后的底图**逐像素完全一致**，说明换上去的确实是对应的那一帧，不是"看起来像"。

串口新增三条调试指令：`k` 连续采样统计闭眼比例，`m` 读回立绘一列反推呼吸档位，`b` 强制闭眼 8 秒配合 `n`（整屏 RGB565 回传）把画面 dump 成 PNG 看接缝。

### 7.9 网络排障：2.4GHz 与 IP 漂移（v0.8.2）

这一节是拿一次真实误判换来的，两件事必须分开看。

**一、ESP32-S3 没有 5GHz。** 芯片射频只覆盖 802.11 b/g/n 的 2.4GHz 频段。5GHz 不是"连不上"，是**扫都扫不到**——没有那个频段的收发器，改代码、换天线都没用。所以"改用 5G 频段开发"这条路在硬件层面就是堵死的。

好消息是双频合一的 SSID 不影响使用：同名广播时，芯片会自己挑 2.4G 那个 BSS。实测 `PDCN` 同时广播了 ch4 和 ch6 两个 BSS，设备连上的就是 2.4G 那一侧，RSSI -52。

**二、IP 漂移会让整条链"看起来全挂"。** 故障是这样串起来的：

1. Mac 的 DHCP 租约从 `192.168.1.71` 换成 `192.168.1.87`；
2. 固件里 `KFLOW_BASE` 还写死 `.71`，每个请求都打到空地址 → `[sync] http=-1`；
3. 把地址改对，**仍然全 400** —— Django 的 `ALLOWED_HOSTS` 里也只有 `.71`，Host 头不匹配被直接拒；
4. 症状和 WiFi 掉线一模一样（首屏照旧显示有网、数据页转圈），所以第一反应很容易栽在"2.4G 连不上了"上。

**三层修复（均已落地）**

| 层 | 措施 |
|---|---|
| 固件 | `KFLOW_BASE` 降级为出厂默认值，运行时优先读 NVS；串口发 `u` 可改并持久化，不用重烧 |
| Django | `ALLOWED_HOSTS` 自动并入本机当前私有网段 IPv4（`ALLOW_LAN=1`，仅适合本地/局域网部署） |
| 诊断 | 串口 `w` 扫频 + 状态行 `base=` |

**排障顺序**（照这个走不会误判）

```
z  →  wifi=3 ？ 否 → 发 w，看目标 SSID 在不在列表里
                是 → 看 base= 是否等于本机当前 IP
                     → curl -H "Host: <ip>:9000" http://<ip>:9000/api/terminal/summary
                       400 = ALLOWED_HOSTS 没放行；401 = 只是没带设备令牌（正常）
```

v0.8.2 实测：

```
[scan] found=13 (2.4GHz only — 5GHz is invisible to this radio)
[scan] *PDCN                 ch= 6 rssi= -34 WPA2/3
[scan] *PDCN                 ch= 4 rssi= -52 WPA2/3
[scan] "PDCN" ch=4 rssi=-52 enc=WPA2/3
[wifi] connected ip=192.168.1.72 rssi=-53
[scan] reconnected=1 ip=192.168.1.72
[sync] http=200 bytes=1072
[board] topic http=200 bytes=4883
[ink] page=3 sampled=800 ink=30
[ota] check latest=0.7.5 size=1237648 avail=0
```

`PDCN` 出现两次是双频合一的两个 BSS，不是重影。`WPA2/3` 是混合模式，WPA3-only 的 AP 这块芯片连不上。

### 7.10 公网部署适配（v0.9.0）

服务从局域网换到 `https://mg.kfc-linlin.top` 之后，设备能连上、能配网、`sync` 返回 200，**但中文页一片空白，日志照样是 `http=200`**。这是本地开发永远不会遇到的坑，值得单独记一笔。

#### 症状拆解

```
[sync]  http=200 bytes=720                 ← 正常
[board] topic http=200 bytes=4896          ← 多出 13 字节
board[topic] valid=0 failed=0 len=4896     ← 收下了，但没画出来
[ink] page=3 ink=0                         ← 屏幕上真的一个墨点都没有
```

服务端没问题：本地渲染同一份数据，`build_board("topic")` 是 4883 字节、四个块、`inkbits` 分别 217/237/263/52，有字。

#### 根因：把 chunked 的块头当成了像素

`4883 + 13 = 4896`，`5087 + 13 = 5100` —— 两页都**正好多 13 字节**，这个固定差值就是答案：

```
"1313\r\n"  (6)  +  4883 字节数据  +  "\r\n" (2)  +  "0\r\n\r\n" (5)  =  4896
```

Django dev server 直接发 `Content-Length`，nginx / Cloudflare 转发时改成 `Transfer-Encoding: chunked`，而 `getStreamPtr()` 给的是**未经解码的原始流**。固件按 `stride*h` 硬切，第一块就越界 `break`，于是什么都不画。

> 这类 bug 的共同特征：**本地全绿、上线才炸**，而且日志完全正常（`http=200`）。只要出现"长度比预期多出固定值"，先怀疑传输层包装。

#### 三处修复

| 位置 | 问题 | 修法 |
|---|---|---|
| `httpGetBinary` | 无 `Content-Length` 时把原始流当数据 | 新增 `readChunkSize()` / `eatCrlf()`，逐块解码 |
| `otaApply` | 直接 `refuse` —— 公网永远升不了级 | `Update.begin(UPDATE_SIZE_UNKNOWN)` + 逐块写 |
| 分带提示 | `tap check-in` 压在中文标题第二行 | 三条提示合并到页脚 `y=274` |

**chunked 解码里有个二次陷阱**：第一版按 chunk 大小一次性 `readBytes(buf, 4050)`，结果只收到 3319 字节就停了。

原因是 `Stream::readBytes` 有自己的 1 秒超时，公网下一个 4KB 块常常要两三秒才到齐，等不到就返回 0，被当成"流结束"。

正确写法是**只按 `stream->available()` 此刻真的到了多少取**，让外层循环反复推进。

#### 提示行与内容区的冲突

内容区从 `y=44` 一直铺到 `242`，**中间没有任何一条安全线**：

- 原 `y=98` → 压住 topic 标题第二行（本地那条帖子标题短，只占一行，所以一直没露馅）
- 改 `y=64` → 又压住概览页的 `CHECKED IN` / `streak 0d`

最终把 `tap check-in / next / sync` 并成一行放到页脚 `y=274`，左端两条 10px 短线继续标分带位置。页脚是唯一两边都不用的地方。

`dumpScreen` 同步改成回传 320 行（原来只回传立绘的 262 行，页脚整个看不到），现在整屏可验证。

#### 实测（fw=0.9.0）

```
[sync]  http=200 bytes=720
[board] murmur http=200 bytes=5087    ← 与本地一字不差
[board] topic  http=200 bytes=4883
[dump] count=4  b0..b3 need/left 全部相等，无 OVERRUN
[ink]  page=3 sampled=800 ink=123
```

配对走的是串口新增的 `i` 指令（`runPairing` 只能由点屏触发，屏幕线松了就再也进不去）。生产库是空的，旧令牌按设计被 `401` 清掉，重新配对后 `balance` 从 1085（远程库）而不是 8507（本地库）取，说明数据确实来自新服务端。

**尚未验证**：公网 OTA 下载。生产机 `uploads/firmware/` 是空的（`latest=null`），需要先放一个**版本号高于设备**的 bin 才能触发。（v0.10.0 起还要放同名的 `.sig`，见 §7.11。）

### 7.11 OTA 签名与证书校验（v0.10.0）

上一版 OTA 的全部保障只有一句 `Update.setMD5()`。问题是那个 MD5 就在 manifest 里，和 bin 走同一条链路：**谁能在路上改包，就能顺手改摘要**——校验永远「通过」，因为证明和结论来自同一个不可信来源。这一版把证明挪到链路之外：私钥在本地，公钥烧在板子里。

```
bin ──SHA-256──► digest ──ECDSA P-256(私钥)──► sig (DER, 71B) ──base64──► 清单 sig 字段
                                                                             │
板子：边下载边算 SHA-256 ─► 收完 ─► base64 解码 ─► mbedtls_pk_verify(内嵌公钥) ─► 通过才 Update.end()
```

**四个决定，都不是随手定的：**

| 决定 | 原因 |
|---|---|
| 签**摘要**不签整包 | ECDSA 本来就是「对摘要签名」，长度固定 71B，不随 bin 变大 |
| **DER** 编码 | mbedtls 的 `mbedtls_pk_verify` 收 DER；`r‖s` 裸拼接（64B）是另一套约定，混用只会得到一个 `ERR_ECP_BAD_INPUT` |
| **边下载边算**摘要 | 下载完再回头读一遍 6.25MB 分区要另写几百行；流式算只多一个 `mbedtls_sha256_update` |
| 验签在 `Update.end()` **之前** | `end()` 才切换启动分区。切完再验就晚了——那时已经是一个能开机的坏固件 |

MD5 没有删掉，但**不再参与放行**：它留在清单和 `X-Firmware-MD5` 头里做传输对账。真正的门只有一道，多一道只会让人以为有两道。

#### 密钥与指纹

```bash
python scripts/sign_firmware.py keygen     # 一次性
# 私钥 secrets/ota_signing_key.pem  (600, gitignore)
# 公钥 secrets/ota_pubkey.pem       (服务端预验用)
# 固件头 ota_pubkey.h / ota_selftest.h（入库，公钥不是秘密）
```

当前公钥指纹（SHA-256 of SPKI DER）：

```
1538df1e715a9787cc37d135e7e75c78f431a8f09eb13e9b4c0a5fb85579465f
```

板子串口发 `v` 会用它自己内嵌的 DER 算同一个值。**这是唯一能证明「烧进板子的公钥 = 签名那把私钥的公钥」的手段**——否则验签失败时你分不清是包错了还是公钥错了。

`v` 会跑两条断言，而不是一条：

```
[sig] selftest digest=1 accept=1 reject=1
[sig] pubkey fp=1538df1e715a9787 cc37d135... (match header)
```

`accept=1` 只说明「该过的过了」，一个 `return 0` 的桩函数也能做到。所以第二条把摘要翻一个比特再验，要求**必须失败**（`reject=1`）。两条同时成立，验签才不是装饰。

#### 证书：从 `setInsecure()` 换成三张根 CA

`mg.kfc-linlin.top` 现在挂在 Cloudflare 后面，实测链（2026-10-27）：

```
leaf (CN=kfc-linlin.top, SAN=*.kfc-linlin.top)
  └─ GTS WE1  ──签发者──► GTS Root R4 ──交叉签名──► GlobalSign Root CA
```

钉一张根证书等于把设备的可用性交给那家 CA 的经营策略。Cloudflare 换过 CA（DigiCert → Let's Encrypt → Google Trust Services），换的那天如果板子只认旧根，症状是**WiFi 好、https 全挂、OTA 永远升不了**——而那时已经没法用 OTA 修它。所以认三张：

| 根 | 到期 | 为什么留着 |
|---|---|---|
| GTS Root R4 | 2036-06-22 | Cloudflare 当前用这张 |
| GTS Root R1 | 2036-06-22 | 同一家的另一条链，Google 轮换时会用 |
| ISRG Root X1 | 2035-06-04 | Let's Encrypt，Cloudflare 随时可能切回来 |

代价是信任面从「一家」变成「三家」。对一个摆在桌上的终端，可用性比极限的信任收敛更值钱——这个取舍是刻意的。

`setCACert()` 之后 core 的行为（读了 `NetworkClientSecure.cpp` / `ssl_client.cpp` 确认，不是猜）：

- `_use_insecure=false` → `mbedtls_ssl_conf_authmode(VERIFY_REQUIRED)`，链不对直接握手失败；
- `mbedtls_ssl_set_hostname(host)` → **主机名/SAN 一起校验**，所以换 IP 冒名也不行。

**逃生开关**：串口发 `l` 切到宽松档（`setInsecure`，写 NVS `tlsloose`），再发一次切回。它是给事故准备的——CA 真换了的那天，严格档连不上、OTA 也走同一条 TLS，设备只剩拔线一条路。宽松档下每次启动都会打：

```
[tls] LOOSE(no verify) - send l to restore
```

不静默、不自动降级：**严格档握手失败就是失败**，偷偷退回宽松等于把校验做成装饰。

#### 发布一个新版本（v0.10.0 起的完整流程）

```bash
# 1. 改版本号
sed -i '' 's/"0.10.0"/"0.10.1"/' firmware/kflow_terminal/config.h

# 2. 编译
CLI="/Applications/Arduino IDE.app/Contents/Resources/app/lib/backend/resources/arduino-cli"
FQBN="esp32:esp32:esp32s3:CDCOnBoot=cdc,PartitionScheme=no_fs,PSRAM=opi,FlashSize=16M"
"$CLI" compile --fqbn "$FQBN" --output-dir /tmp/ota_build firmware/kflow_terminal

# 3. 放进分发目录并签名（.sig 会落在 bin 旁边）
cp /tmp/ota_build/kflow_terminal.ino.bin uploads/firmware/kflow_terminal-0.10.1.bin
python scripts/sign_firmware.py sign uploads/firmware/kflow_terminal-0.10.1.bin

# 4. 上传**两个**文件：bin 和 .sig
```

只传 bin 不传 `.sig` 的后果不是「设备照旧升级」，而是清单直接拒绝：

```json
{"update_available": false,
 "reason": "latest build 0.10.1 is not usable: no .sig next to the bin"}
```

这是刻意选的：把未签名包列进清单，设备会每次都白下一整包 1.2MB 再拒，人还以为是网速慢。

#### 首次必须插线烧一次

现有设备跑的是 0.9.1——既不认签名、也不校验证书。所以：

1. **0.10.1 必须用 USB 烧一次**（`firmware/kflow_terminal/build/` 里有合并镜像）；
2. 烧完发 `v`，确认 `accept=1 reject=1` 且指纹对得上；
3. 从那以后才是真正的无线闭环（下载 → 验签 → 切换）。

> 0.10.0 是这道门的第一个版本；0.10.1 在它基础上加了连接复用和验签逃生口，**直接烧 0.10.1，别烧 0.10.0**——两版都是「必须插线」的，没必要插两次。

**私钥丢了 = 以后所有升级只能插线**。没有后门，这就是签名该有的样子。备份 `secrets/ota_signing_key.pem` 到仓库之外的地方。

#### 已验证 / 待验证

本地（都已跑过）：

| 项目 | 结果 |
|---|---|
| 后端测试 | `apps.terminal` 57 项全绿（含 5 项签名：缺签名 / 改一字节 / 换一把钥匙 / 坏 base64 / 清单字段） |
| 清单输出 | `signed: true`，`sha256=48b55474...`，服务端用 `secrets/ota_pubkey.pem` 预验通过 |
| 独立交叉验证 | 从 `ota_pubkey.h` 里把 91 字节 DER 抠出来，**用 OpenSSL 而非签名脚本**核对：`Verified OK`；把 bin 改一个字节 → `Error Verifying Data` |
| 自检向量 | 头文件里的 digest 与 `hashlib` 一致；签名用 OpenSSL 复核 `Verified OK` |
| 固件编译 | 1,256,627 B（61% flash），RAM 15%；比 0.9.1 多 7.4KB（三张根证书 + mbedtls pk） |

待真机（板子不在手边，这两步只能你插线后跑）：

| 步骤 | 期望输出 |
|---|---|
| 串口 `v` | `[sig] selftest digest=1 accept=1 reject=1` + `fp=1538df1e715a9787` |
| 串口 `o` | `[ota] sha256 mine=... server=... match=1` → `signature rejected` 或 `sig ok, restarting` |

**刻意的反面测试**：把 bin 改一个字节但保留原 `.sig` 再发布，设备必须停在老版本、屏幕显示 `FAILED`。这一步没做过，就不能说「签名挡住了篡改」——只能说「代码写了验签」。

### 7.12 连接复用与验签逃生口（v0.10.1）

### 一次进数据页，原来要握三次手

数据页的三块内容来自三个请求：`/api/terminal/summary`、`/api/terminal/textboard?slot=murmur`、`...?slot=topic`。每个请求原来都 `new` 一个 `WiFiClientSecure`、都 `setReuse(false)`，于是每次都从 TCP 三次握手开始，再到 TLS 握手、证书链校验。公网上单次 0.8–1.5 秒，**第一眼看到的就是两三秒空白**。

nginx 那边其实早就配好了 `keepalive 32`（`deploy/nginx-kflow.conf`），是板子这边自己把连接扔了。

### 为什么「共享一个 client」这个显然的改法不管用

`HTTPClient::begin()` 里有一段守卫：

```cpp
if (_host != the_host && connected()) {
  _canReuse = false;
  disconnect(true);   // 直接把 socket stop 掉
}
```

它比的是**这个 HTTPClient 实例自己的** `_host`。每次请求都 `new HTTPClient`，`_host` 都是空串，于是每次都判定成「换了主机」，连接当场被关。更阴的是它只在 `connected()` 为真时才触发——**第一轮看着一切正常，第二轮才发现握手次数一次没少**。

所以四个对象全部提到全局：`g_http` / `g_plainConn` / `g_tlsConn` / `g_tlsConfigured`。这不是图省事，是这份实现下唯一能生效的写法。

### 三个必须一起改的收尾细节

| 细节 | 不改会怎样 |
|---|---|
| **chunked 终止块后面的那个空行要吃掉** | 原来 `chunk == 0` 直接 `break`，`\r\n` 留在 socket 里。连接一关看不出来；开始复用之后它就成了下一个响应的开头，症状是隔一次 `http=-1` |
| **没读干净就不许复用**（`netEnd(clean)`） | 提前 break、`getSize()>cap`、状态码异常这三种情况下，body 还在路上，残留字节会串到下一个响应 |
| **空闲 45 秒主动关** | nginx `keepalive_timeout` 是 75 秒。本地不主动关，就会出现「对面已经掐了、板子还以为活着」，下一个请求撞死在死连接上 |

另外三处地址/档位变化必须显式 `netCloseConn()`：串口 `u` 改服务地址、串口 `l` 切 TLS 档、以及 OTA 下载前（那一刻要开独占连接，同时挂两个 TLS 会话白占 40KB 堆，而验签恰好最缺堆）。

### 怎么证明它真的生效

不看「感觉快了」，看日志：

```
[net] conns=1 reuse=2 conn=1 heap=183420
```

- `conns`：新建连接数，**等于 TLS 握手次数**。一次完整刷新只该加 1。
- `reuse`：省下的握手次数。进一次数据页再翻一页，应该是 `reuse` 加 2。
- `conn`：此刻是不是还挂着连接（1 = 复用窗口开着）。

两个数一起涨 = 没生效。`logStatus()`（串口任意键）和每次 `syncNow()` 结束都会打这一行。

失败时也能分清方向和原因：

```
[tls] /api/terminal/summary failed: cert=verify reused=1 (stale keep-alive? next request reconnects)
```

`reused=1` 说明是旧连接被判死（下一个请求会自己重连）；`reused=0` 才是真的连不上——证书、DNS、路由。

### 验签逃生口：串口 `x`

签名是单向门。0.10.1 之后，如果 `mbedtls_pk_verify` 在真机上因为堆碎片、PSA 后端、DER 边界之类的问题挂了，设备就**永久升不了级**，只能拔线——而 OTA 这条路正是为了不拔线才写的。

所以留了串口 `x`：

```
[ota] BYPASS armed: next update installs WITHOUT verifying signature.
[ota]   use once then send o. cleared automatically after one attempt.
```

- **一次性**：`otaApply()` 返回后立即清除，不管成没成。
- **不写 NVS**：重启即失效，不会变成设备上常驻的后门。
- 屏幕上会显示 `BYPASS / signature NOT checked`，日志是大写 `!!! SIGNATURE BYPASSED`。

为什么这不算降低安全性：串口通了就等于人已经坐在板子边上、手上有根 USB 线，本来就能直接烧固件。绕过验签不增加任何攻击面——它防的不是攻击者，是「自己的代码把自己锁在门外」。

### 0.10.1 烧完要验的四件事

| # | 动作 | 期望 |
|---|---|---|
| 1 | 串口 `v` | `[sig] selftest digest=1 accept=1 reject=1`，`fp=1538df1e715a9787` |
| 2 | 串口 `t` 进数据页再 `p` 翻页，然后任意键 | `[net] conns=1 reuse=2 conn=1` —— **conns 只加 1** |
| 3 | 串口 `o` | `[ota] sha256 ... match=1` → `sig ok, restarting` |
| 4 | 拿一个 bin 改一字节、签名不动，放上生产机再 `o` | 必须 `signature rejected rc=-0x...`，屏幕 `FAILED`，重启后还是老版本 |

第 4 条是唯一能证明「签名挡住了篡改」的实验。前三条只证明「验签会跑」。

固件体积 1,257,151 B（61% flash）/ RAM 15%，比 0.10.0 只多 456 B——连接复用和逃生口都是几十行的改动。

## 8. 已知限制（首版故意留下的口子）

| 限制 | 原因 | 解法 |
|---|---|---|
| 第 0/4 屏的中文通知标题仍显示 `(see kflow web)` | 那两屏的文字是固件用 ASCII 字库直接画的，没走位图 | 把通知标题也改成 `slot=notice` 的位图块，或等 §9 的点阵字库 |
| 中文页每次都要联网 | 位图不在设备上 | 可把最近一次的板子存进 flash/NVS，代价是 5KB 分区和"离线显示过期内容"的语义 |
| 分带只按 y 分，不支持左右滑 | 三个动作够用；横滑要加手势状态机，收益不明显 | 真需要时在 `handleZoneTap(x, y)` 里按 x 再分 |
| 需要手动配 WiFi | 省掉一个配网 UI | 二版加 SmartConfig / 串口配网 |
| 立绘占 122 KB flash | 240×262 RGB565 未压缩 | 需要省空间时可改 4bit 调色板或 160×175 缩略图 |
| 300 秒刷新 | 桌面信息不需要更快 | 改 `terminal.refresh.seconds`，但不建议低于 60 秒 |
| 未读红点只能在网页上清掉 | 设备侧没有「标记已读」的写接口，硬加就要处理"哪几条"的选择 | v0.9 加设备令牌版的 mark-read |
| 提醒只有视觉，没有声音 | 板上没接蜂鸣器；背光 PWM 闪烁作为提示更扰人 | 想加就接一颗无源蜂鸣器到空闲 GPIO |
| OTA 没有自动回滚 | Arduino core 默认不启用 `APP_ROLLBACK_ENABLE`；新固件如果启动就崩，会一直崩 | 板子有 USB-Serial-JTAG，插线随时能烧回来。要更稳可以开 rollback 并加"首次启动自检" |
| 待机动画只在首屏 | 数据页文字密度高，整屏位移会晃阅读区 | 想加就只做眨眼那 1KB 的局部帧，别动整屏 |
| 呼吸每秒吃掉约 7% CPU | 每 360ms 重贴 122KB | 觉得费电就把 `BREATH_STEP_MS` 调大，或改成只在"有人靠近"时呼吸 |
| **只支持 2.4GHz WiFi** | ESP32-S3 的射频没有 5GHz 收发器，5GHz 的 AP 扫都扫不到 | 硬件限制，软件绕不过。双频合一的 SSID 会自动落到 2.4G 那一侧即可正常用 |
| 服务地址会随 DHCP 漂移 | 开发机换个 IP，设备就打到空地址，且症状和 WiFi 掉线一样 | 已缓解：地址存 NVS（串口 `u` 改）+ Django 自动并入本机私有 IP。根治要靠 AP 配网时一并写入 |
| **签名私钥丢了就只能插线** | 没有「私钥恢复」这种功能，有的话签名就白签了 | 把 `secrets/ota_signing_key.pem` 备份到仓库之外。换密钥必须插线重烧，因为老固件只认老公钥 |
| 根证书固定，CA 轮换会连不上 | 钉三张根是可用性与信任面的取舍（§7.11） | 串口 `l` 切宽松档先把 OTA 救回来，再发一版带新根的固件 |
| 服务端对签名只做「预验」 | 生产机上不一定有 `secrets/ota_pubkey.pem`，没有就跳过预验 | 最终裁判永远是设备；预验只是为了让发布时就发现问题 |

---

## 9. 下一步路线

1. **v0.2（已完成）**：小 K 首屏 + 点按进入 + 静置回首屏；RGB565 立绘生成脚本
2. **v0.2.1（已完成）**：触摸点按层——压力判据 + armed 门闩 + 连续确认，点屏在小 K 与数据页之间来回切；首屏绿点做「触摸已确认」标记
3. **v0.3（已完成）**：常驻走秒时钟（服务端 `epoch` 首选 + SNTP 兜底）、NVS 离线缓存（带磨损保护）、页脚数据新鲜度三态、首屏排版自校验
4. **v0.4.0（已完成）**：屏幕内触摸校准——首屏长按 BOOT 进入，10 秒划一圈四边自动结算，校准值存 NVS（改一次不用重烧）；校准后自动进坐标测试页，点哪画哪；`TOUCH_ENABLED` 与运行期 `g_calValid` 分离，没校准时自动退回压力层
5. **v0.4.1（已完成）**：分带交互 + 签到——数据页按 y 分三带（上签到 / 中翻页 / 下刷新），分界线对齐页面原有横线；三屏（概览 / 社区 / 通知）头部三点指示；新增 `POST /api/terminal/checkin`（复用 `award_daily_activity`，按天幂等，4 项测试）
6. **v0.5.0（已完成）**：中文上屏——服务端把最新碎碎念 / 最新帖子画成 1-bit 位图（`GET /api/terminal/textboard`），固件 `drawBitmap` 贴块；数据页扩到五屏；串口加 `t`/`p`/`g`（进数据页 / 翻页 / 读回像素验证）
7. **v0.6.0-0.6.2（已完成）**：OTA 无线升级——自定义双 6.25MB 分区表、服务端固件分发（`latest`/`download`/`report` 三接口）、固件流式下载 + `Update.setMD5` 校验 + 进度条 + 失败退避；app0/app1 交替实测三次，NVS 的令牌与校准值全程保留
8. **v0.7.0-0.7.5（已完成）**：设备主动提醒——未读红胶囊常驻首屏与五屏头部；首屏待机轮询（有未读 60 秒 / 无未读 5 分钟）；新通知到达自动弹到通知页并 20 秒后退回；"正在操作不抢屏"的 30 秒 hold-off；`latest_id` 水位线存 NVS，与未读数分离
9. **v0.8.0（已完成）**：待机动画——整图上移 0~3px 做呼吸（不新增数据，靠源数组偏移）、只重贴眼睛 21×23 小块做眨眼；眨眼帧由 `scripts/gen_xiaok_face.py` 从同一张源图合成（掩膜 + 扩散修补 + 弧线眼睑）；串口加 `k`/`m`/`b`/`n` 四条回读验证指令
10. **v0.8.2（已完成）**：网络排障——串口 `w` 扫 2.4GHz（SSID / 信道 / RSSI / 加密）、`u` 改服务地址并写 NVS；`KFLOW_BASE` 从编译期常量降为出厂默认；Django `ALLOWED_HOSTS` 自动并入本机私有网段，修掉 DHCP 换 IP 后"WiFi 一切正常但所有接口 400/超时"的误判（详见 §7.9）
11. **v0.8.8-0.9.0（已完成）**：公网部署适配——`httpGetBinary` 与 `otaApply` 都支持 `Transfer-Encoding: chunked`（nginx/Cloudflare 转发不再有 `Content-Length`，原代码把 chunk 头当像素，中文页白屏、OTA 直接拒升）；分带提示合并到页脚，修掉压在中文标题第二行的问题；`dumpScreen` 改为回传整屏 320 行；串口加 `i`（触发配对）/`y`（dump 板结构）（详见 §7.10）
12. **v0.9.1（已完成）**：公网部署适配——`httpGetBinary` 与 `otaApply` 都支持 `Transfer-Encoding: chunked`（nginx/Cloudflare 转发不再有 `Content-Length`，原代码把 chunk 头当像素，中文页白屏、OTA 直接拒升）；分带提示合并到页脚；`dumpScreen` 回传整屏；串口加 `i`/`y`（详见 §7.10）
13. **v0.10.0（已完成）**：OTA 签名与证书校验——ECDSA P-256 对 SHA-256 摘要签名，边下载边算、`Update.end()` 之前验签（取代和包同源的 MD5）；三张根 CA 钉住证书链 + 主机名；串口加 `v`（验签自检，含必须失败的负向断言）与 `l`（TLS 宽松档逃生）；服务端清单下发 `sig`/`sha256` 并拒绝未签名包（详见 §7.11）
14. **v0.10.1（已完成）**：连接复用 + 验签逃生口——`HTTPClient` / client 全部提到全局（`begin()` 的 host 守卫按实例比 `_host`，局部实例下复用永远不生效），一次刷新 3 次 TLS 握手 → 1 次；chunked 终止块后的 CRLF 补吃、脏连接不复用、空闲 45 秒主动关；串口加 `x`（单次跳过验签，不写 NVS）（详见 §7.12）
15. **v0.10.2**：整屏重绘 → 局部重绘——`renderPage()` 开头一句 `fillScreen` 就是 153KB ≈ 42ms 白屏，而且 `syncNow` 每轮都调它（不只是翻页闪，放着不动也会闪）。改成页头/页脚按"值变了才重画"、内容区各页只清自己那一带
16. **v0.10.x**：多页轮播接更多数据源（排行榜 `/api/rankings/site`、K 士多 `/api/store/products`、学习进度 `/api/learn/tutorials`）＋ 通知已读闭环（`POST /api/notifications/mark-read` 现在是 `@require_user`，要加一条认设备令牌的孪生接口）＋ 数值变化高亮 ＋ 第 0/4 屏中文也走位图
17. **v0.11**：OTA 回滚——开 `APP_ROLLBACK_ENABLE` + 新固件首次启动自检（连网 / 屏幕 / 令牌三件事都成了才 `esp_ota_mark_app_valid`），失败自动回滚到上一槽
18. **v1.0**：手机 AP 配网（WiFi 现在是编译期写死的，换路由器就要重编）＋ 服务端推送

---

## 10. 目录

```
apps/terminal/                后端接入层（模型 / 令牌 / 摘要 / 测试）
apps/terminal/textboard.py    中文正文 → 1-bit 位图（PIL 排版 + 换行/避头尾）
apps/terminal/firmware.py     固件分发：扫描 bin / 语义版本 / 双摘要缓存 / 边车验签 / 升级判断
firmware/kflow_terminal/      ESP32-S3 固件（含 xiaok_splash.h 生成的立绘数组）
firmware/kflow_terminal/xiaok_face.h    眨眼用的眼睛局部帧（open/closed，各 21×23）
firmware/kflow_terminal/partitions.csv  双 6.25MB app 槽（不配置则 OTA 无处可落）
firmware/kflow_terminal/ota_pubkey.h    OTA 验签公钥（P-256 SPKI DER，91B，脚本生成）
firmware/kflow_terminal/ota_selftest.h  验签自检向量（固定串的摘要 + 签名，脚本生成）
firmware/kflow_terminal/tls_roots.h     三张根 CA 拼成的 PEM 串（脚本生成）
uploads/firmware/             OTA 分发的 bin + 同名 .sig 边车（gitignore，按版本号命名）
secrets/                      签名私钥与公钥 PEM（gitignore，**私钥务必异地备份**）
static/terminal.html          浏览器绑定页
static/terminal.js            绑定与吊销交互
scripts/gen_xiaok_splash.py   小 K 立绘 → RGB565 头文件
scripts/gen_xiaok_face.py     立绘 → 眨眼帧（掩膜 + 扩散修补 + 眼睑弧线）
scripts/sign_firmware.py      密钥生成 / bin 签名 / 本地核对 / 自检向量（keygen·sign·verify·selftest）
scripts/gen_tls_roots.py      一组根证书 PEM → tls_roots.h（含到期日与指纹注释）
docs/terminal.md              本文档
```
