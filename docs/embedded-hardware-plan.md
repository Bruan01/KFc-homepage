# KFlow 嵌入式产品线 · 调研与落地方案

> 2026-10-23 · 结论先行版。目标：用最低成本把 KFlow 的账号体系延伸到物理世界，而不是新开一家硬件公司。

## 一、结论

**不要把"嵌入式"当成一条新业务线，把它当成账号体系的物理出口。**

KFlow 现在的资产不是代码，是一条闭环：账号 → 积分 → 兑换码 → 下载/OTA → 社区等级/成就 → AI 助手。任何硬件只要接不进这条闭环，就只是一个卖出去就结束的开发板。

按这个标准筛，值得做的只有一个方向、两个阶段：

| 阶段 | 产品 | 定位 | 单台物料（估算） | 零售（建议） |
|---|---|---|---|---|
| v1 | **K 牌**（墨水屏身份牌） | 会员身份的物理凭证 + 桌面信息牌 | ¥55–75 | ¥129 / 800 积分 |
| v2 | **小 K 桌面端**（语音终端） | 按一下就能问小 K 的桌面分身 | ¥110–140 | ¥299–399 |

先做 v1 不是为了赚钱，是为了用最低代价把「打样 → 小批量贴片 → 烧录 → 发货 → 售后」这条链路跑一遍。v2 才是主角，但它必须站在 v1 已经验证过的供应链上。

---

## 二、现有资产盘点：哪些能直接吃下来

这是判断值不值得做的唯一依据。逐条对过代码：

| 硬件需要的能力 | 现有模块 | 复用方式 | 改造量 |
|---|---|---|---|
| 出厂序列号 / 绑定码 | `accounts` 激活码、`store` 加密兑换码 | 新增设备绑定码，复用一次性核销语义 | 小 |
| 固件 OTA | `catalog` 产品/版本 + `downloads` Range 流式 | 固件就是一条 `Product` 的 `version`，`file_sha256` 字段现成可用于设备端校验 | **极小** |
| 使用扣费 | `points` ledger + 条件更新幂等 | 每次会话记一条 ledger，`ref_type="device_session"` | 小 |
| 设备状态看板 | `dashboard` 指标 + 表快照 | 加"在线设备 / 日活 / 积分消耗"卡片 | 小 |
| 语音问答 | `community_ai`（小 K）| 复用同一套 API 配置、人格 prompt、知识库 | 中 |
| 设备推送 | `notifications` | 未读数 / 新通知摘要推到屏上 | 小 |
| 售卖与发货 | `store` K 士多 | 硬件 SKU = 兑换码 + 现金订单 | 中（需补支付） |
| 品牌形象 | `static/xiaok/`（chibi 立绘、银白灰蓝） | 直接做外壳丝印与开机动画 | 零 |

**最漂亮的一条是 OTA**：`products` 表已经有 `file_sha256`、`file_size`、`file_path`，`downloads` 已经支持 Range 断点续传。设备弱网升级需要的分片、校验、断点，全都不用重写。固件当成一个 `category="firmware"` 的产品就行。

---

## 三、候选路线对比

调研了当前开源生态，四条可行路线：

| 路线 | 代表方案 | 单台成本 | 差异化 | 结论 |
|---|---|---|---|---|
| A. AI 语音终端 | `xiaozhi-esp32`（MIT，24.9k★，110 贡献者，70+ 开发板）| ¥110–140 | 中。技术门槛已被抹平，淘宝白牌 ¥99 起 | **做，但必须靠账号/社区差异化** |
| B. 墨水屏信息牌 | 立创开源「多功能墨水屏」（MIT，复刻 ¥80）、`10.2 寸月历天气`（GPL3，¥198）| ¥55–75 | 高。低打扰、可长期挂在墙上 | **优先，v1 就选它** |
| C. Edge Node 边缘盒子 | Orange Pi Zero 3 + frp/WireGuard/Tailscale | ¥100–160 | 高（直接延伸 Edge Client）| 暂缓，见第七节 |
| D. 通用 AI 音箱 / 树莓派方案 | 树莓派 + 本地模型 | ¥800–2000 | 低 | 不做 |

### 为什么舍 A 取 B 作为第一台

不是 A 不好，是 A 不适合当第一台：

1. **A 是红海**。小智生态已有大量成品，¥99–299 的白牌满淘宝。你做的第 11 个"更好的小智"没有意义，除非差异化来自 KFlow 账号本身——而这需要先有设备端基础设施。
2. **A 有持续成本**。ASR + TTS 按量计费，每个设备每天都在烧钱。25 个用户时无所谓，一旦送出去 100 台就是负债。
3. **B 能零成本验证全链路**。没有音频、没有并发、没有实时性，e-ink 深度睡眠下一块 1000mAh 电池能跑几个月。BOM ¥60 意味着做 20 台只要 ¥1200——试错成本低到可以忽略。
4. **B 的稀缺感更强**。限量的编号版"K 牌"，比一个量产语音盒子更像会员凭证。

---

## 四、v1：K 牌

### 形态

信用卡大小（86×54mm 或 90×60mm），2.9 寸三色墨水屏（黑/白/红），ESP32-C3 或 ESP32-S3 单模组，1000mAh 锂电池，Type-C 充电，背面磁吸 + 支架孔。

### 屏上显示什么

这是产品定义的核心，必须克制——只放"看一眼就够"的信息：

- **主屏（默认）**：`小 K` 头像 + 用户名 + 等级徽章 + K 积分余额
- **副屏 1**：最近一条碎碎念 / 论坛热帖标题（3 条）
- **副屏 2**：未读通知数 + 成就解锁进度
- **副屏 3**（可选）：最近一张「显影」作品（灰度抖动）

刷新策略：**每 30 分钟唤醒一次拉数据，其余时间深度睡眠**。e-ink 断电保持画面，所以"不刷新"才是常态。按键手动刷新一次。

### BOM（估算，需实际询价）

| 物料 | 规格 | 单价 |
|---|---|---|
| 主控模组 | ESP32-C3-MINI-1（已过 SRRC，走模块化认证）| ¥12–15 |
| 墨水屏 | 2.9" 三色 SPI，含驱动板 | ¥25–32 |
| 电源 | TP4056 + DW01 保护 + 1000mAh 锂电 | ¥10–13 |
| 结构 | 3D 打印 / 硅胶套 + 亚克力面板 | ¥6–10 |
| PCB | 嘉立创 4 层打样摊销（20 台）| ¥5–8 |
| 杂项 | Type-C、按键、阻容、排线、包装卡 | ¥5–8 |
| **合计** | | **¥63–86** |

零售 ¥129，毛利约 35–50%，扣除发货与损耗后基本是"不亏钱做会员凭证"。

### 固件选型

不自己写驱动栈。用 **ESP-IDF + GxEPD2 移植**或直接上 **PlatformIO + GxEPD2**（Arduino 生态，墨水屏驱动现成、社区最大）。三色屏刷新慢（15–25s），必须在 UI 设计上接受这一点，别做进度条。

---

## 五、v2：小 K 桌面端

### 为什么最后还是做语音

因为它是这个项目唯一能"演示给别人看"的硬件。一个墨水屏牌讲不出故事，一个会说话的小 K 可以。

### 技术底座：直接吃 `xiaozhi-esp32`

| 项 | 情况 |
|---|---|
| 许可 | MIT，允许商用 |
| 社区 | 24.9k★，110 贡献者，70+ 开发板适配，第三方固件生态庞大 |
| 芯片 | ESP32-S3 / C3 / P4，另支持思必驰、全志、移远 |
| 能力 | 离线唤醒、流式 ASR/LLM/TTS、MCP 协议控外设、OLED/LCD 表情 |
| 协议 | WebSocket 单通道 或 MQTT+UDP 双通道，音频 OPUS 16k/24k、60ms 帧 |

**协议细节已核实**（这是能不能自己实现服务端的关键）：

```
连接头：Authorization: Bearer <token> / Protocol-Version: 1
        Device-Id: <MAC> / Client-Id: <UUID>

握手：设备 → {"type":"hello","version":1,"transport":"websocket",
              "audio_params":{"format":"opus","sample_rate":16000,
                              "channels":1,"frame_duration":60}}
      服务端 → {"type":"hello","transport":"websocket","audio_params":{...}}

控制：listen(start/stop/detect, mode: auto|manual|realtime)
      tts(start/stop/sentence_start)、stt(text)、llm(emotion)、
      abort、goodbye、mcp(JSON-RPC 2.0)

音频：v1 裸 OPUS 帧；v2 16 字节头(含 timestamp，服务端 AEC)；v3 4 字节头
```

`Authorization: Bearer` 和设备 MAC，刚好对上我们的设备绑定 + `Device-Id` 就是硬件指纹。

### 服务端：不要部署 `xiaozhi-esp32-server`

它是 MIT，功能全，但 README 明确写着「功能不完整、未通过网络安全评估、请勿用于生产环境」。拿它当参考实现可以，当生产后端不行。

**正确做法：自己写一个薄网关，独立进程，不碰 Django。**

理由：Django 现在是纯 WSGI，引入 Channels/ASGI 会动到整套部署模型和 `start.sh`。语音是长连接、高并发、易崩的负载，塞进 Django 进程是自找麻烦。

```
[ESP32-S3] --WSS(OPUS)--> [voice-gateway: FastAPI/uvicorn]
                                    |
                                    +--HTTP--> Django 内部接口
                                               /api/internal/device/auth
                                               /api/internal/points/debit
                                               /api/internal/xiaok/chat
```

网关只做四件事：接 OPUS、调 ASR、调小 K（走 `community_ai` 同一套配置）、调 TTS 回推。业务状态全部落在 Django，网关无状态，可随时重启。

ASR/TTS 两条路：

- **云端**：阿里/火山，上线快，按量计费。每次对话 5–10 秒音频，成本可控。
- **本地**：`SenseVoiceSmall` 已有 llama.cpp/GGUF 运行时（2026-06 发布，无需 Python/torch，Linux arm64 可跑），中文 CER 8.01%，比 whisper.cpp small 的 22% 好一个量级；TTS 用 CosyVoice2 / IndexTTS。你有 3090，这条路成本≈0，且"语音不出内网"是可以写进产品页的卖点。

**建议**：v2 先用云端跑通体验，同时把本地链路作为"私有部署版"卖点，两条都留。

### BOM（估算）

| 物料 | 规格 | 单价 |
|---|---|---|
| 主控 | ESP32-S3-WROOM-1-N16R8（8MB PSRAM 必需）| ¥22–28 |
| 音频 | ES8311 codec + NS4150 功放 + 8Ω/2W 喇叭 | ¥12–16 |
| 屏 | 1.28" 圆屏 GC9A01（240×240 SPI）| ¥14–18 |
| 电源 | TP4056 + 800mAh 锂电 | ¥10–13 |
| PCB | 4 层，小批量摊销 | ¥8–10 |
| 结构 | 3D 打印 / 硅胶 + 丝印 | ¥12–18 |
| 杂项 | Type-C、按键、阻容、麦克风开孔、包装 | ¥8–12 |
| **合计** | | **¥86–115**（加损耗与测试按 ¥130 算）|

零售 ¥299–399。

### 唤醒词必须换掉

「小智」已被多家公司注册商标。商用必须自定义唤醒词。ESP-SR 的 WakeNet 支持自定义，但中文自定义唤醒词要走乐鑫的服务（周期与费用需询价）。

**v1 的务实解法：按键说话（push-to-talk）**。跳过唤醒词，省掉整个合规与技术问题，体验差异对桌面场景几乎无感。唤醒词留到 v3。

---

## 六、怎么"套进去"：新增 `apps/devices`

### 数据模型（草案）

```python
Device           # id, device_uid(MAC 唯一), hw_model, hw_version,
                 # fw_version, user_id(nullable), token_hash, bound_at,
                 # last_seen_at, status, points_used_total
DeviceBindCode   # code_hash, issued_by, expires_at, used_by, used_at
                 # 一次性；管理员后台生成 / K 士多兑换产出
DeviceSession    # session_id, device_id, user_id, started_at, ended_at,
                 # asr_chars, tts_chars, points_cost
DeviceLog        # device_id, level, message, created_at（限 200 条滚动）
```

沿用 legacy 命名习惯，表名建议 `devices`、`device_bind_codes`、`device_sessions`、`device_logs`。

### 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/devices/bind` | `{code, device_uid, hw_model}` → `{token, user, points}` |
| GET | `/api/devices/me` | 状态卡数据：等级、积分、未读、最新碎碎念 3 条 |
| GET | `/api/devices/ota/latest` | 按 `hw_model` + 当前 `fw_version` 返回 `{url, sha256, size, version}` |
| GET | `/api/devices/ota/download/<id>` | 复用 `downloads` 的 Range 流式 |
| POST | `/api/devices/heartbeat` | 在线状态、电量、信号、fw_version |
| POST | `/api/devices/session/debit` | 会话结束扣积分（幂等，按 `session_id`）|

鉴权：`Authorization: Bearer <device_token>`，token 只存 hash（`token_hash`），和现有 session 体系完全隔离，不复用 `user_session`。

### 绑定流程

```
设备首次开机 → AP 热点配网页 → 用户填 WiFi + 8 位绑定码
  → POST /api/devices/bind
  → 服务端校验 code_hash 一次性 + 过期时间
  → 绑定到当前登录用户（或按 code 归属），返回长期 token
  → 设备存 NVS，之后所有请求带 Bearer
```

绑定码来源两个：后台管理员批量生成（送人用），K 士多兑换（自购用）。刚好复用 `store` 的幂等兑换语义。

### 扣费

每次语音会话结束后记一条 `points` ledger，`ref_type="device_session"`，按 `session_id` 做唯一约束保证幂等。积分不足时设备播报提示并显示"去 K 士多兑换"的二维码。

---

## 七、必须说清楚的风险

### 1. SRRC：不是可选项

任何带 WiFi/蓝牙发射、面向国内销售的产品，**必须**取得无线电发射设备型号核准，标注 CMIIT ID，否则不得上市流通。这是硬前置。

- 用已认证模组（如 ESP32-C3-MINI-1 本身有 SRRC）**可以减少测试项，但整机仍要单独申请、拿自己的 CMIIT ID**，不能借用模组的核准号。
- 官方申请本身不收费，成本主要是授权实验室的测试费（需向检测机构询价）。
- 改天线结构、改发射功率、增减蓝牙/WiFi 功能，都算新机型，要重新认证。
- 生产商对外销售还需办理**销售备案**，与型号核准是两件独立的事。

**这条会决定产品能不能卖。立项前先找检测机构问价，别等量产。**

### 2. 供应链才是真门槛，不是技术

焊第一块板子很容易，做第 50 块、每块都一致、每块都能过测试、坏了能换——这才是硬件。贴片、烧录、测试架、包装、发货、退换，每一环都会吃掉你的周末。

先用 3D 打印 + 手工焊做 10 台，把售后问题在 10 台里踩完，再考虑开模。

### 3. 25 个用户不是市场

社区现在 25 个账号。这个规模做硬件，注定是"自用 + 送人 + 少量售卖"，不是生意。所以第一台设备的目标不应该是利润，而应该是：**验证链路 + 产出内容 + 证明这个站不只是一个网页。**

如果要做成生意，目标客户是站外的 vibecoding 人群，那产品定义就必须从"KFlow 会员牌"变成"独立好用的墨水屏桌面牌，KFlow 集成是加分项"。这是两种完全不同的产品，现在不用决定，但心里要有数。

### 4. 我不同意的一种做法

不要为了"显得像硬件公司"去做一款通用 AI 音箱。那个赛道已经被小智生态 + 白牌厂商填满，你的优势在账号体系和社区，不在声学结构。

---

## 八、下一步

### 本周（成本 < ¥200）

1. 买：ESP32-C3 开发板 ×2、2.9" 三色墨水屏模块 ×2、杜邦线。约 ¥100。
2. 写：`apps/devices` 最小骨架 —— `Device` 表 + `bind` + `me` 三个接口，先不做 OTA 和扣费。
3. 跑：开发板点亮屏幕，显示你的用户名、等级、积分。**这一步出来，方案就成立了。**

### 两周内

4. 画 PCB（立创 EDA，两层够用），打样 5 片，验证电源与墨水屏时序。
5. 做 3D 外壳，打印 3 台样机。
6. 把 OTA 接进 `catalog`/`downloads`，验证弱网断点续传 + sha256 校验。

### 一个月内

7. 问 SRRC 检测机构报价，决定"自己卖"还是"只送不卖"。
8. 做 10 台，送 3 台给活跃用户，收一轮反馈。
9. 再决定 v2 语音终端要不要上。

---

## 附：参考项目清单

| 项目 | 许可 | 用途 |
|---|---|---|
| [xiaozhi-esp32](https://github.com/78/xiaozhi-esp32) | MIT | v2 固件底座、语音协议参考 |
| [xiaozhi-esp32-server](https://github.com/xinnan-tech/xiaozhi-esp32-server) | MIT | 仅作协议实现参考，**不上生产** |
| [FunASR / SenseVoice](https://github.com/modelscope/FunASR) | MIT | 本地 ASR，有 llama.cpp/GGUF 运行时 |
| 立创开源「多功能墨水屏」 | MIT | v1 硬件参考，复刻成本 ¥80 |
| 立创开源「10.2 寸月历天气」 | GPL-3.0 | 墨水屏 UI/低功耗参考，注意 GPL 传染性 |
| GxEPD2 | GPL-3.0 | 墨水屏驱动（商用注意许可） |
| Orange Pi Zero 3 + frp/WireGuard | 各自 | 路线 C 备选 |
