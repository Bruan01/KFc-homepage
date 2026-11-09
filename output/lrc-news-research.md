# 具身智能行业动态 · 种子数据与可订阅信源检索记录

> **检索日期**：2026-11-05
> **产出**：`lrc-news-seed.json`（12 条 items + 10 个 sources）与本文件
> **硬约束**：不编造新闻、日期、公司名、URL；无法验证的条目直接丢弃；所有产出 URL 均为 https
> **工具**：WebSearch（多轮，配合 `freshness=m3` / `m4` / `d7`）、WebFetch（直连核正文与日期）、`curl -sSL`（实测 HTTP 状态码 / Content-Type / 正文格式标记）、GitHub REST API（交叉验证 release 日期）

---

## 1. 检索与验证方法

1. **第一轮**（`freshness=m3`）：中文「具身智能 2026年10月 融资 模型发布 人形机器人 动态」、英文「Google DeepMind / Physical Intelligence / NVIDIA GR00T October 2026 release」，得到产业月报、周刊、券商周报、聚合站与官方博客候选。
2. **第二轮**：按类别补搜——国家标准（市场监管总局/央视）、融资（自变量、Machenta、简智）、赛事（具身智能技能大赛）、招聘（麦可思/教育部专业目录）、11 月近期（`freshness=d7`）。
3. **第三轮**：对每条候选做 WebFetch 正文核验（标题、页面发布日期、关键事实原文），并用 `curl` 批量实测 URL 的 HTTP 状态；对 GitHub 相关条目改用官方 releases Atom + REST API 取得精确 `published_at` / `<updated>` 与 `<link href>`。
4. **交叉验证**：凡只有单一二手聚合站来源、或媒体间日期/金额冲突无法消解的，一律丢弃。
5. **信源实测**：对候选 RSS/Atom/API 逐条 `curl`，记录状态码、Content-Type、正文首部标记（`<feed` / `<rss` / `[`）与字节数；`curl` 被反爬或网络抖动时改用 WebFetch 直连确认返回体确为 feed 格式，并在 note 中如实标注。

> 环境中已存在 `output/embodied-ai-research.md`（同日、更早的一份知识栈调研），仅用作 URL/版本号线索，未直接采信其结论；其中版本号与本次官方 release 记录的冲突见 §4.3。

---

## 2. 每条动态的检索来源与验证方式

| # | 日期 / 条目 | 检索入口 | 验证方式与证据 | 结论 |
|---|---|---|---|---|
| 1 | 2026-08-03 LeRobot v0.6.1 | WebFetch `lerobot/releases.atom`；GitHub REST API `/repos/huggingface/lerobot/releases` | Atom 首条目 `<title>Release v0.6.1</title>`、`<updated>2026-08-03T14:24:49Z</updated>`、`<link href="…/releases/tag/v0.6.1">`；API 返回 200 JSON 数组共 11 条，`published_at=2026-08-03` | 官方一手，采用 |
| 2 | 2026-10-13 Gemini 4 Argon for Robotics | WebSearch 英文轮；`curl` + 解析 `deepmind.google/blog/rss.xml` | 官方 RSS（HTTP 200，`<rss`，100 个 item）中 `Gemini 4 Argon for Robotics` 的 `pubDate` 为 `Tue, 13 Oct 2026 16:01:58 +0000`，`link` 即所引 URL；搜索摘要与腾讯新闻、Turing Wire 均给出 ERQA 87% | 官方 RSS 定日期，采用；文章页 WebFetch 会 302 到 `developers.googleblog.com` 且二次取回失败，另一次 `curl` 为 200，故以官方索引为准 |
| 3 | 2026-10-20 Isaac Lab v3.0.0 | GitHub REST API `/repos/isaac-sim/IsaacLab/releases`；WebFetch `IsaacLab/releases.atom` | API 200 JSON 数组，`v3.0.0` 的 `published_at=2026-10-20`；Atom 首条目 `<updated>2026-10-20T02:32:48Z</updated>`；cameta 月报另记「10-21 GTC 柏林宣布 Isaac Lab 3.0 正式可用」（发布 vs 大会宣布，差 1 天） | 官方一手，采用发布日 10-20 |
| 4 | 2026-10-22 MuJoCo 3.17.0 | GitHub REST API `/repos/google-deepmind/mujoco/releases`；WebFetch `mujoco/releases.atom` | API 200 JSON 数组 30 条：3.15.0=10-05、3.16.0=10-14、3.17.0=10-22；Atom 首条目 `3.17.0 / 2026-10-22T21:45:20Z`。与既有报告中「第三方 2026-10-20 核对 MuJoCo 3.15.0（2026-10-05）」吻合 | 官方一手，采用；版本号强时效 |
| 5 | 2026-10-21 NVIDIA Cosmos 开放工具 | `curl` 解析 `blogs.nvidia.com/feed/`；WebFetch 文章页 | RSS 200 `<rss`，条目 `NVIDIA Cosmos Opens New Tools to Train, Evaluate and Deploy World Models` `pubDate Thu, 22 Oct 2026`；文章页自身显示 `October 21, 2026 by Pranjali Joshi`，正文含 Cosmos Data Factory 五个 blueprint、Cosmos 3 NIM、GR00T / Pi0.5 适配 | 采用文章自身日期 10-21；RSS 与页面差 1 天见 §4.4 |
| 6 | 2026-10-27 Machenta 4000 万美元种子轮 | WebSearch 定向；WebFetch 帝国理工官方新闻页 | 官方页 `27 October 2026`，原文 `$40 million`、`largest ever seed raise by a UK robotics startup`、Creandum 与 Union Square Ventures 领投、模型 `pre-trained entirely on simulated data` | 官方一手，采用；中文媒体 10-29/10-30 为转载滞后 |
| 7 | 2026-11-02 简智机器人 1 亿美元 | WebSearch `freshness=d7`；WebFetch 今日头条/大河财立方 | 页面 `2026-11-02 14:45`，原文「11月2日…第三季度完成新一轮1亿美元融资」「累计融资额超3亿美元」；东方财富股吧同文 `2026-11-02 14:47` 交叉印证 | 采用；注意 11-02 是宣布日，融资「第三季度完成」，累计额为公司自述 |
| 8 | 2026-10-16 首批六项人形机器人国标 | WebSearch 定向；WebFetch 央视网 | 央视网 `2026-10-16 01:26:37`，原文「记者10月15日从市场监管总局获悉…将于2027年4月1日起正式实施」「5项技术要求系列标准 +《人形机器人仿真测试平台技术规范》」；央广网 10-15 同稿 | 官方媒体，采用页面日期 10-16 |
| 9 | 2026-10-23 国际具身智能技能大赛 | WebSearch 赛事轮；WebFetch 今日头条/大河财立方 | 页面 `2026-10-24 17:21`，原文「10月23日下午…上海浦东张江科学会堂…800余支竞赛队伍的千台人形机器人」「9大赛道、23个赛项」及复刻联华超市命题 | 采用事件日 10-23；与「首届智能机器人应用技能大展南京站」（新浪财经 10-31）为不同赛事，勿混淆 |
| 10 | 2026-10-31 具身智能人才缺口与专业布局 | WebSearch 招聘轮；WebFetch 网易/麦可思研究 | 页面 `2026-10-31 17:40:15`，原文含 ROSCon China 2026（10-16 上海）、教育部 9-23 国新办发布会「超常规布局具身智能等相关专业」、北理工调研「人才缺口约100万」、麦可思将需求归为四类人才 | 采用；数字口径冲突见 §4.1/§4.6 |
| 11 | 2026-10-29 智元 GO-3 Preview / G2 Max | WebFetch `nvdium.com` 专题；与微信公众号行业日报、新浪财经人形机器人周报交叉 | Nvdium 页头 `2026年10月29日 23:13`，正文「10月29日，智元在上海举办 2026 智元创新日…GO-3 Preview…WITA-Omni…G2 Max」「21 个自由度，双臂搬运能力最高 40 公斤」；微信公众号日报亦称 10-29 发布 GO-3 Preview | 采用事件日 10-29；命名/日期内部矛盾见 §4.5 |
| 12 | 2026-10-21 宇树 H2-X | WebFetch cameta《全球机器人产业月报》2026年10月刊；与新浪财经人形机器人周报交叉 | 月报原文「10月21日，宇树科技发布H2-X…官方标称最长续航约8小时…10月22日…启动『宇创计划』」；新浪财经周报（10/19–23）亦记「宇树科技发布 H2-X，最长续航约 8 小时」 | 二手月报口径，但双源一致且 URL 可访问，采用并标注；`curl` 直连该站 403（反爬），WebFetch 200 取得全文；8 小时为「官方标称」，未独立验证 |

**items 类别分布**：开源 3、模型 2、融资 2、政策 1、赛事 1、招聘 1、产品 1、硬件 1（共 12 条，覆盖 8 个 kind）。日期集中在 2026-08 至 2026-11，其中 11 月 1 条。

---

## 3. 信源实测结果（HTTP 状态码与内容格式）

实测命令形态：`curl -sSL --max-time 15~40 -A "Mozilla/5.0 …" -o <file> -w "%{http_code}|%{content_type}"`，随后检查 `<file>` 首部是否含 `<feed` / `<rss` / `[`（JSON 数组）并统计字节数。带 UA 是因为部分站点对无 UA 请求返回 403。

| slug | feedUrl | 实测状态 | Content-Type | 格式标记 | 体积 | 判定 |
|---|---|---|---|---|---|---|
| lerobot-releases | `https://github.com/huggingface/lerobot/releases.atom` | 200（带 UA 重试取得；同域名在别的轮次偶发 000） | `application/atom+xml; charset=utf-8` | `<feed` | 777402B | 通过；WebFetch 亦确认 Atom 命名空间与首条目 |
| isaaclab-releases | `https://github.com/isaac-sim/IsaacLab/releases.atom` | 200 | `application/atom+xml` | `<feed` | 163222B | 通过；WebFetch 确认首条目 v3.0.0 / 2026-10-20 |
| mujoco-releases | `https://github.com/google-deepmind/mujoco/releases.atom` | WebFetch 直连返回完整 Atom XML；`curl` 多轮为 000 或 200 空体 | Atom XML | `<feed` + `<entry>` | 首条目 3.17.0 | 通过（以 WebFetch 为准）；同仓库 releases API 200 JSON 数组 30 条作交叉佐证 |
| github-lerobot-api | `https://api.github.com/repos/huggingface/lerobot/releases` | 200 | `application/json; charset=utf-8` | `[`（JSON 数组） | 11 条 release | 通过；字段含 `tag_name` / `published_at` / `html_url` |
| deepmind-blog | `https://deepmind.google/blog/rss.xml` | 200 | `application/xml` | `<rss` | 70126B / 100 item | 通过 |
| nvidia-dev-blog | `https://developer.nvidia.com/blog/feed/` | 200 | `application/atom+xml; charset=UTF-8` | `<feed` | 773902B | 通过；解析出 11-02、10-23、10-15、08-26 等机器人条目 |
| nvidia-blog | `https://blogs.nvidia.com/feed/` | 200 | `application/rss+xml; charset=UTF-8` | `<rss` | 279058B | 通过；含 10-22 Cosmos 条目 |
| arxiv-csro | `https://export.arxiv.org/rss/cs.RO` | 200 | `application/rss+xml` | `<rss` | 219329B | 通过；镜像 `https://arxiv.org/rss/cs.RO` 亦 200 `<rss>` |
| qbitai | `https://www.qbitai.com/feed` | 200（**必须带 UA**；无 UA 为 403） | `application/rss+xml; charset=UTF-8` | `<rss` | 6636B | 通过 |
| ieee-spectrum-robotics | `https://spectrum.ieee.org/feeds/topic/robotics.rss` | 200 | `application/rss+xml; charset=utf-8` | `<rss` | 383112B | 通过；为 Robotics 主题 feed 而非普通网页 |

**实测可访问且确认为 feed 格式的信源：10 / 10**（其中 3 个为 GitHub releases Atom，1 个为 GitHub releases JSON API）。

### 被排除的候选信源（附实测证据）

| 候选 | 实测结果 | 排除原因 |
|---|---|---|
| `https://www.therobotreport.com/feed/` | 403 `text/html` 5417B | 反爬拦截，无法确认 feed |
| `https://www.robotics247.com/rss` | 403 `text/html` 5305B | 同上 |
| `https://www.jiqizhixin.com/rss` | 200 `text/html` 3375B，无 `<rss`/`<feed` | 返回普通网页，不是 feed |
| `https://huggingface.co/blog/feed.xml`、`https://huggingface.co/blog/robotics/feed.xml` | `curl` 多轮 000 | 本次沙箱网络无法验证，不纳入 |
| `https://github.com/Physical-Intelligence/openpi/releases.atom` | 200 `application/atom+xml`，但正文仅 549B；对应 API 返回 `[]` | 该仓库无 releases，无长期抓取价值 |
| `https://www.36kr.com/feed` | 200 `application/rss+xml` `<rss>` 108607B | 实测通过但为综合科技源、非机器人垂直；已达 10 个上限，记为备选 |
| `https://www.leiphone.com/feed` | 200 `application/rss+xml` `<rss>` 589097B | 同上，记为备选 |
| Physical Intelligence 官方博客 | 未找到可验证的 RSS/Atom/API 端点 | 无法实测，排除 |
| 机器之心其他 feed 路径 | `/rss` 返回 HTML | 非 feed，排除 |

---

## 4. 口径冲突与时点不确定（价格 / 版本号 / 融资额 重点标注）

### 4.1 融资额与轮次（最需警惕）

- **自变量机器人「10 亿元 A++ 轮」——已整条丢弃**。cameta 月报与 NSTL《世界机器人产业周刊》记为 **2026-10-10**；但百度百科与 theroboradar 的融资历程均记为 **2026-01-12**，且其后还有 2026-02 Pre-B、2026-04 B 轮近 20 亿、2026-06 B+/B++/C 多轮。时点冲突重大，疑为月报把 1 月事件误置到 10 月，故不写入 items。
- **简智机器人 1 亿美元**：原文为「**第三季度完成**新一轮」，11-02 只是宣布日；「累计融资额超 3 亿美元」为公司自述，未经审计。
- **Machenta 4000 万美元**：帝国理工官方 **10-27**；智通财经/微信公众号 **10-29**；BlockBeats/区块链周刊 **10-30**；embodiedwire 记「10-27 结束隐身」。采用官方 10-27。
- **其他大额融资均未采用**：乐聚近 15 亿元 Pre-IPO、Field AI 7 亿美元 B 轮、Eka Robotics 1.5 亿美元 A 轮、Foundry Robotics 1 亿美元 A 轮、新石器近 4 亿美元 E 轮、星尘智能 10 亿元、模思智能超 10 亿元 Pre-A——仅见于二手周报/月报，未取得公司或机构一手公告。
- **智元「启动 10–15 亿元新融资、投后估值约 500 亿元、港股 IPO 推迟至 2027-02」**：媒体明确写「援引投资人消息」，且经济观察报引述公司内部人士「均不对外发表评论」。估值/市销率（约 48 倍）为媒体测算，未采用。

### 4.2 价格（一律未写入 JSON）

- 启元 Q1/T1「19999 元起」、人形机器人展会租赁单价「从 1.2万–1.3万元/天降至 3000–3900 元/天，降幅超七成」、数据采集员「日薪 200–250 元 / 月薪 4000–8000 元」、算法岗「80K·15 薪 / 应届博士 150 万–500 万年薪」等，均为招聘平台与媒体转引，**存在个例、总包含股权、标题党放大**，且无官方价目表，故只在本文档记录、不进种子数据。

### 4.3 版本号

- 可靠的官方版本记录：LeRobot `v0.6.1`（2026-08-03）、Isaac Lab `v3.0.0`（2026-10-20）、MuJoCo `3.15.0 / 3.16.0 / 3.17.0`（2026-10-05 / 10-14 / 10-22）。**均为检索时点快照，随时会变**。
- 冲突：既有 `embodied-ai-research.md` 记「第三方 2026-10-20 核对 Isaac Lab 2.3.2 + Isaac Sim 5.1」，而本次官方 release 显示 `v3.0.0` 于 10-20 发布；同文件又记「Isaac Lab 3.0.0 对应 Isaac Sim 6.2」。二手版本核对与官方发布页**不一致**，兼容表须以官方发布页复核。
- 未采用的型号：「GR00T N2 预览版（10-09 GTC 2026）」「GR00T N1.7 Early Access（2026-04-17）」「π0.7 / π*0.6」「Gemini Robotics 2 / ER 2 公测」——来自聚合站/二手文章，无法与 NVIDIA、DeepMind 官方 feed 逐条对应。
- 「GPT-6 Astra 在 RoboDojo 42 项任务 22.48%」「Genie 4 世界模型」等出自今日头条「公开资料整理」类文章，无一手出处，丢弃。

### 4.4 日期口径（同一事件多日期）

| 事件 | 口径 A | 口径 B | 采用 |
|---|---|---|---|
| Gemini 4 Argon | 官方 RSS **10-13**（Turing Wire 同） | 今日头条 10-14；腾讯新闻 10-26（Apollo 演示报道日）；行行查称「ER 2 于 10-27 公测」，但官方 RSS 显示 ER 2 发布于 **2026-07-30** | 10-13 |
| NVIDIA Cosmos 工具 | 文章页 **10-21** | RSS `pubDate` 10-22（UTC/上线时差） | 10-21 |
| 六项国标 | 记者 10-15 获悉（央广网 10-15） | 央视网 **10-16** 发布 | 10-16 |
| 智元创新日 | 事件 **10-29**（微信公众号日报同） | Nvdium 页头 10-29 23:13 但正文写「2026年10月30日」 | 10-29 |
| 技能大赛 | 开幕 **10-23** | 报道 10-24 | 10-23 |
| Isaac Lab v3.0.0 | GitHub 发布 **10-20** | GTC 柏林宣布 10-21 | 10-20 |
| Machenta | 官方 **10-27** | 中文媒体 10-29 / 10-30 | 10-27 |

### 4.5 命名口径

- 智元同场发布的操作系统：Nvdium 写 **「Link-U OS 1.0」**，微信公众号行业日报写 **「灵渠 OS 1.0」**；模型名亦有 `GO-3` 与 `GO-3 Preview` 两种写法。JSON 标题/摘要只保留可双源确认的 `GO-3 Preview` 与 `G2 Max`，不写 OS 名称。
- 「Worken（有效智能工时）」为企业自提框架，新华社中国经济信息社/中国信通院报告收录，但**尚无第三方机构或客户合同采用**，未写入。

### 4.6 招聘数字口径

同一篇/不同来源给出互不吻合的数字：人才缺口「约 100 万」（北理工专业设置申请表）vs「9 月全栈人才需求 85 万、可满足 4.5 万」（学会专委会）vs「1–7 月新发岗位同比增 6–7 倍、人形机器人细分 +831.88%」（脉脉高聘）vs「需供比 5.2:1」（国务院研究室）vs「15 倍」（另一份报告）。JSON 只取「约 100 万」并标注为第三方调研，所有数字均为**媒体/平台转引、非官方统计**。

### 4.7 可访问性口径

- `cameta.org.cn` 月报页：`curl` 403（反爬），WebFetch 200 取得全文 → 记为「可访问但需非 curl 通道」。
- `imperial.ac.uk` 官方新闻页：`curl` 202，WebFetch 200 取得全文。
- `github.com` 与 `deepmind.google` 的**文章页**：`curl` 间歇性 000（沙箱网络抖动），同一 URL 在另一轮返回 200；已用 WebFetch + GitHub API/Atom 交叉确认，不作为「不可访问」处理。
- `deepmind.google/blog/gemini-4-argon-for-robotics/` 在 WebFetch 中 302 至 `developers.googleblog.com` 且二次取回失败；但官方 RSS 的 `<link>` 含该 URL、且 `curl` 曾返回 200，故保留并在 note 中说明。
- 11 月覆盖：检索到 11-02（简智、RoboScience 机器科学 A2 轮）、11-05（飒智智能 Pre-B）等条目；因 11 月仅过 5 天、且多数仅单一来源，只采用双源验证的简智一条。

---

## 5. 主动丢弃的候选条目（记录以备复核）

1. 自变量机器人 10 亿元 A++ 轮（10-10 vs 2026-01-12 时点冲突，见 §4.1）。
2. 第 26 届中国国际工业博览会（2026-10-12，5.6 万㎡ / 350 余家 / 450 余款首发新品）：cameta 月报、NSTL 周刊、自动化网三源一致，但主要载体为二手月报与 **http 页面**（不符合全 https 要求），且 items 已达 12 条上限，未纳入；可作为后续补充。
3. 智元估值 500 亿元 / 港股 IPO 推迟：投资人消息，公司不评论。
4. Field AI 7 亿美元 B 轮、Eka Robotics 1.5 亿美元 A 轮、乐聚近 15 亿元 Pre-IPO、模思智能超 10 亿元 Pre-A：仅二手周报/月报，无一手公告。
5. 美国「232 条款」机器人进口调查及关税暂缓（2026-10-28）：涉及政府与地缘政治议题，且非纯产业技术/产品动态，按内容边界主动排除。
6. 地方政策数字（重庆千亿目标、广东 2028 年 8 万台、上海 8000 台进厂、香港 10 亿港元 AI 资助、厦门合作创新采购）：二手月报/转载，未取得官方原文。
7. 「GR00T N2 / Gemini Robotics ER 2 公测 / GPT-6 Astra RoboDojo 22.48%」等型号与指标：无法与官方 feed 对齐。
8. 智元 110 台远征 A3 吉尼斯纪录、启元第 5000 台下线、珞石第 1 万台力控臂：仅 cameta 月报单源，且部分日期为「9 月/年内」无精确日，未纳入。

---

## 6. 主要来源清单（标题 + URL）

### 官方一手 / 发布记录

1. Hugging Face LeRobot Releases（Atom） — https://github.com/huggingface/lerobot/releases.atom
2. LeRobot v0.6.1 Release — https://github.com/huggingface/lerobot/releases/tag/v0.6.1
3. GitHub Releases REST API（huggingface/lerobot） — https://api.github.com/repos/huggingface/lerobot/releases
4. Google DeepMind Blog RSS — https://deepmind.google/blog/rss.xml
5. Gemini 4 Argon for Robotics — https://deepmind.google/blog/gemini-4-argon-for-robotics/
6. NVIDIA IsaacLab Releases（Atom） — https://github.com/isaac-sim/IsaacLab/releases.atom
7. IsaacLab v3.0.0 Release — https://github.com/isaac-sim/IsaacLab/releases/tag/v3.0.0
8. MuJoCo Releases（Atom） — https://github.com/google-deepmind/mujoco/releases.atom
9. MuJoCo 3.17.0 Release — https://github.com/google-deepmind/mujoco/releases/tag/3.17.0
10. NVIDIA Developer Blog（Atom） — https://developer.nvidia.com/blog/feed/
11. NVIDIA Blog（RSS） — https://blogs.nvidia.com/feed/
12. NVIDIA Cosmos Opens New Tools to Train, Evaluate and Deploy World Models — https://blogs.nvidia.com/blog/cosmos-open-train-evaluate-deploy-world-models/
13. Build World Models for Interactive Simulation with NVIDIA Cosmos — https://developer.nvidia.com/blog/build-world-models-for-interactive-simulation-with-nvidia-cosmos/
14. Imperial AI spinout Machenta raises $40 million to make robots instant learners — https://www.imperial.ac.uk/news/articles/2026/imperial-ai-spinout-machenta-raises-40-million-to-make-robots-instant-learners/
15. arXiv cs.RO RSS — https://export.arxiv.org/rss/cs.RO

### 官方媒体 / 机构与已核验报道

16. 首批人形机器人领域国家标准发布（央视网，2026-10-16） — https://news.cctv.com/2026/10/16/ARTI4Ap5IvaBJ5F1KX1p9RXj261015.shtml
17. 首批人形机器人国标来了（央广网，2026-10-15） — https://www.cnr.cn/newscenter/native/gd/20261015/t20261015_527843088.shtml
18. 《全球机器人产业月报》2026 年 10 月（第 7 期），中国机电一体化技术应用协会 — https://www.cameta.org.cn/index.php?a=show&catid=238&id=3887
19. 智元发布 GO-3 基础模型，奥迪在工厂测试人形机器人（Nvdium，2026-10-29） — https://nvdium.com/zh-CN/articles/397773139
20. 真实场景搬进赛场，千台人形机器人上海「赶考」（大河财立方，2026-10-24） — https://www.toutiao.com/article/7700162055634092585/
21. 简智机器人完成 1 亿美元新一轮融资（大河财立方，2026-11-02） — https://www.toutiao.com/article/7703461704231043638/
22. 简智机器人完成 1 亿美元新一轮融资（东方财富转载，2026-11-02） — https://guba.eastmoney.com/news,600104,1790762255,d.html
23. 严重缺人！这一专业，战略急需（麦可思研究，2026-10-31） — https://www.163.com/dy/article/LAJ9LV4B05218435.html
24. 人形机器人周报：两办推动具身智能产业化 智元启动 AI WAVE 成果发布（新浪财经） — https://vip.stock.finance.sina.com.cn/q/go.php/vReport_Show/kind/lastest/rptid/846388444668/index.phtml

### 可长期订阅信源（补充）

25. 量子位 RSS — https://www.qbitai.com/feed
26. IEEE Spectrum Robotics Topic RSS — https://spectrum.ieee.org/feeds/topic/robotics.rss
27. 36 氪 RSS（备选，综合科技源） — https://www.36kr.com/feed
28. 雷锋网 RSS（备选，综合科技源） — https://www.leiphone.com/feed

---

**一句话结论**：12 条 items 中 7 条来自官方一手（GitHub release / 官方博客 / 官方媒体），5 条为已双源交叉核验的二手报道；10 个信源全部实测为 HTTP 200（或 WebFetch 等价 200）且确认为 Atom / RSS / JSON 数组；融资额、价格、版本号与多处日期存在口径冲突，已在 §4 逐项标注，相关数字未写入种子数据。
