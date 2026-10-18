# 安全 & 性能审计（2026-10-18）

范围：`kflow/` + `apps/*`（19 个 app）+ `static/`，数据库 `data/homepage.db`（SQLite）。
方法：全量 AST 装饰器矩阵、危险 sink 扫描（SQL / 文件 / 命令 / 重定向）、逐条调用点追溯、`CaptureQueriesContext` 实测查询数、预热后计时。

**总体结论**：没有发现外部可直接利用的 SQL 注入、路径遍历或 CSRF 绕过。真正的风险集中在**管理员凭据与权限模型**；性能上没有塌方式的问题，但有几处「白干活」和「N+1」拉高了每个请求的固定成本。

图例：`已修` = 本次已改并验证；`待决策` = 改动会影响现有登录 / 存量数据，需要你拍板；`记录` = 风险可接受，登记备查。

---

## 一、安全清单

### 高危

| # | 位置 | 问题 | 可利用性 | 状态 |
|---|---|---|---|---|
| H1 | `kflow/settings.py:24-25` | 超级管理员默认口令 `admin` / `admin123`，全仓无环境变量覆盖（`.env` 里也没有） | **真实可利用**：`POST /api/admin/login` 一把梭拿到 `is_super=true`，全站管理面（含显影 API Key、兑换码管理） | 待决策 |
| H2 | `apps/accounts/views.py:360` `tokens_create` | 只要求发起者是 lv2，却允许指定 `admin_level: 3` | **真实可利用**，完整链路：lv1 上传 1 个项目 → 自动升 lv2（`LV1_AUTO_PROMOTE_PROJECT_COUNT=1`）→ 发 lv3 邀请码 → 用自己邮箱注册 lv3 | **已修** |
| H3 | `kflow/settings.py:23` | `SECRET_KEY` 硬编码且无覆盖；它同时是商城兑换码的 Fernet 主密钥（`apps/store/crypto.py:10`） | 拿 DB 副本即可离线解密全部兑换码；且与 H4 的 `db_path` 泄露叠加 | 待决策 |
| H4 | `apps/accounts/views.py:342` `tokens_get` | lv1 即可读全部邀请码明文（`full_token`），包含既有的 lv3 令牌 | **真实可利用**：读到一枚未使用的 lv3 令牌即可直接注册 lv3 | **已修**（按等级过滤） |

> H1 / H3 需要你确认后再动：改口令会改变现有登录方式；换 `SECRET_KEY` 会让**存量兑换码无法解密**（必须同时重新加密），并踢掉所有已登录会话。

### 中危

| # | 位置 | 问题 | 状态 |
|---|---|---|---|
| M1 | `apps/accounts/views.py:169,297` | 口令登录接口无失败限速/锁定（邮箱验证码路径有限速，口令路径没有） | 待决策 |
| M2 | `apps/core/http.py:21` | 无条件信任 `X-Forwarded-For`，每次换一个值即可绕过「每 IP 20 次/小时」的验证码限额 → 邮件轰炸 | **已修**（默认只信 `REMOTE_ADDR`，`TRUST_X_FORWARDED_FOR=1` 才启用） |
| M3 | `static/user-login.html:152` | 登录后跳转 `next` 只挡了 `//`，没挡 `/\evil.com`（浏览器把 `\` 规范化为 `/`）→ 登录成功后被送去钓鱼站 | **已修**（正则白名单，排除反斜杠与控制字符） |
| M4 | `apps/accounts/views.py:380`、`apps/points/views.py:104`、`apps/dashboard/views.py:48` | lv1 可读全量用户邮箱、积分资产；大屏返回 `db_path`、`process_id` | 待决策（大屏是给站主运维用的，删了会显示 `--`） |
| M5 | `kflow/settings.py:118` | `SESSION_COOKIE_SECURE=False`、无 `SECURE_SSL_REDIRECT`；`redeploy.sh` 默认监听 `0.0.0.0` | 待决策（需要先有 HTTPS） |
| M6 | `apps/accounts/services.py:165,182` | 明文口令兼容分支：把 `password` 字段的**哈希串当口令提交**也能登录 | 待决策（需先确认库里没有明文口令） |

### 低危

| # | 位置 | 问题 | 状态 |
|---|---|---|---|
| L1 | `apps/forum/views.py:1776` | 分享页 OG meta 只转义 `& < >`，漏 `"`（不能构成 XSS，但可注入属性） | 记录 |
| L2 | `apps/imaging/views.py:315` | super admin 可指定任意 `base_url`（已限制 http/https，仅剩 SSRF 探测面） | 记录（super 本就能做更危险的事） |
| L3 | `apps/core/pages.py:308` | `/material/<path>` 整个目录匿名可读（遍历已阻断，缺的是授权） | 记录（当前只放了一个演示 mp4） |
| L4 | `scripts/migrate_data.py`、`scripts/db_sync.py` | f-string 拼表名 / `executescript`，表名来自元数据、不参与线上请求 | 记录 |

### 确认安全（不要照着「看起来可疑」去改）

| 位置 | 结论 |
|---|---|
| `apps/dashboard/views.py` `snapshot()` 里的 f-string SQL | **不是注入**：表名来自模块级硬编码 `TABLES` 白名单，路由无参数，已做 `table_names()` 交集 |
| `apps/core/pages.py:_safe_static_path` | 路径遍历已阻断：`resolve()` + `relative_to()`，`../`、`//`、软链、绝对路径全部被拦 |
| `apps/imaging/views.py:template_cover` | 三重防护：目录约束 + 后缀白名单 + `is_file()` |
| `apps/imaging/skill_packages.py:70` | SSRF 已阻断：强制 https + 主机名必须 `github.com` |
| 全站 CSRF | 零 `csrf_exempt`，`CsrfViewMiddleware` 已启用，前端 `csrf.js` 自动注入 header |
| 会话固定 | `login()` 自动 `cycle_key()`，admin 分支额外 `flush()` |
| 令牌随机性 | 全部 `secrets.*`，无一处 `random` |
| 口令哈希 | 自定义 PBKDF2（1.2M 迭代）+ `hmac.compare_digest`，编码兼容与自动升级都正确 |
| `DEBUG` | 默认 `False`，全仓无 `DEBUG=True` |

---

## 二、性能清单

### 已修（本次实测）

| # | 位置 | 问题 | 修复前 | 修复后 |
|---|---|---|---|---|
| P0-1 | `apps/core/pages.py:_rendered_html` | 缓存 key 在**所有改写做完之后**才查 —— 命中时只是丢弃刚算完的结果，CPU 一点没省 | `forum.html` **18.5–22.6 ms**/请求 | **0.83 ms**（`admin.html` 16.5 → **0.13 ms**） |
| P0-4 | `apps/dashboard/views.py` | 表结构逐列 introspection（`products` 24 列 = 24 条查询），19 张表 189 条；metrics 又与 `snapshot` 重复 count | **284 次查询** / 55 ms | **47 次**（schema 缓存命中后），首次 277 |
| P1-5b | `apps/imaging/services.py:317` | 连通性测试复用 `timeout_seconds`（默认 360s、上限 900s） | 单请求最坏卡 **6–15 分钟** | `min(timeout, 15)` |
| P1-5c | `apps/imaging/skill_runtime.py:153` | 同上，列一次 `/models` 等 180s | 最坏 3 分钟 | `min(timeout, 15)` |
| P0-2 | `apps/rankings/analysis.py` `tag_trends` | 循环里逐项目查日志（N+1） | **74 次查询 / 24 ms** | **4 次查询**（一次批量取日志 + 内存分组），且与项目数无关 |
| P0-3 | `apps/forum/views.py` `like_topic` / `like_reply` | 对「点赞者 + 作者」各跑一次全量统计 + 勋章判定 | **56 次查询/次点赞** | **36 次**（`compute_users_stats` / `check_users_achievements` 批量版；取消赞 22 次） |
| P1-6 | `apps/forum/models.py`、`apps/rankings/models.py` | `author_username` / `username` / `uploader_username` / `seller_username` 等高频 filter 字段无索引 | 万级用户时单次点赞 0.5–1 s | 迁移 `0008_*`（forum）+ `0003_*`（rankings）补 7 个索引 |

### 待处理（按收益排序）

| # | 位置 | 问题 | 现状 | 建议 |
|---|---|---|---|---|
| P1-7 | `apps/catalog/views.py:90` | `prefetch_related("packages")` 被循环里的 `.order_by()` 重新打库 | 2 个产品 = 4 次查询；100 个 = 101 次 | 改 `Prefetch("packages", queryset=...order_by(...))` |
| P1-8 | `apps/publishing/views.py:56,113` | 审核列表每条 2–3 次查询，上限 300 条 | inbox 最坏 **900 次** | 先批量 finalize，再一条 `values().annotate()` 聚合 |
| P2-9 | `apps/forum/views.py:290`、`store/listing_views.py:43`、`downloads/views.py:56`、`imaging/views.py:173`、`rankings/views.py:69`、`gamification/views.py:287` | 6 处典型 N+1（`annotate` / `prefetch` 可解） | 每条 1+N | 逐个换 `annotate`，套路成熟 |
| P2-12 | `settings.py`（无 `CACHES`）、`points/services.py:74`、`forum/services.py:37,136`、`learn/views.py:70` | 积分规则 / 热榜权重 / 教程全表每次请求重读 | 每次 1–3 条查询 + JSON 反序列化 | `LocMemCache` + 在对应写接口显式失效 |
| P2-11 | 部署 | `runserver --noreload`、`CONN_MAX_AGE=0`、imaging 每个任务裸起线程 | 每请求新建 sqlite 连接；50 个任务 50 线程抢写锁 | gunicorn/uWSGI + `CONN_MAX_AGE=60` + `ThreadPoolExecutor(4)` |

### 不值得优化（当前数据量下）

`forum_topics=2`、`forum_replies=4`、`users=21`、`products=3` 的规模下，以下都别动：论坛列表的六次批量查询（写得很好，8 次/3.2 ms）、`topics()` 的 count+切片、legacy 表索引（已有 `*_legacy_indexes.py`）、`stats_contributors` 全量聚合、`refresh_*` 管理命令的逐用户循环。

---

## 三、本次改动文件

| 文件 | 改动 |
|---|---|
| `apps/core/pages.py` | 缓存 key 前置 + `_page_structure()` 结构缓存（连 `read_bytes` 都省掉） |
| `apps/dashboard/views.py` | `_table_columns()` schema 缓存；metrics 复用 `snapshot` 的 count/breakdown |
| `apps/imaging/services.py`、`skill_runtime.py` | 连通性测试超时压到 15s |
| `apps/rankings/analysis.py` | `tag_trends` 批量取 `ExternalMetricLog`，内存分组取代 N+1 |
| `apps/gamification/services.py` | 新增 `compute_users_stats` / `check_users_achievements` 批量版；`refresh_user_stats_table` / `refresh_all_levels` 改走批量；分组聚合统一 `order_by()` 清默认排序 |
| `apps/forum/views.py` | `like_topic` / `like_reply` 一次取出点赞者与作者，走批量统计与批量勋章；`liked` 由请求方法直接推导，省一次 `exists()` |
| `apps/forum/models.py`、`apps/rankings/models.py` | 7 个 username 类字段加索引（含迁移） |
| `static/forum.js`、`forum.html`、`src/forum.css` | 列表改每页 10 条 + 页码分页器，移除「加载更多」 |
| `comic-style.css` | 分页按钮豁免漫画主题的放大/旋转 hover，选中态用 `--color-base-content` |
| `apps/accounts/views.py` | `tokens_create` 等级不得超过创建者；`tokens_get` 按查看者等级过滤 |
| `apps/accounts/tests.py` | 新增 2 项：等级钳制、低等级看不到高等级令牌 |
| `apps/core/http.py`、`kflow/settings.py` | XFF 改为需显式开启 `TRUST_X_FORWARDED_FOR` |
| `static/user-login.html` | `next` 白名单（排除 `\` 与控制字符） |

新增回归测试（共 23 项）：

| 文件 | 覆盖 |
|---|---|
| `apps/rankings/test_analysis.py` | `tag_trends` 查询数与项目数无关、总量 ≤ 8、批量结果与朴素逐项目循环逐字段一致 |
| `apps/gamification/test_bulk_stats.py` | 批量统计与逐人统计逐字段相等；查询数不随人数增长且少于两次单人调用；批量勋章判定与逐人一致 |
| `apps/forum/tests.py` | 点赞/取消赞查询预算 ≤ 40；点赞仍给作者积分与通知；7 个 username 列有索引；每页 10 条分页边界与跨页不重复 |
| `apps/core/tests.py` | `forum.html` 有 `#topicPager` 且无 `#loadMore`；`forum.js` 含 `pageSize: 10` 与分页函数；构建产物与 `src/` 都有分页样式 |

验证：全量 **231 项**，仅剩 2 个既有基线失败（catalog `admin-console-8`、rankings rule channel），与本次无关。

---

## 四、建议的处理顺序

1. **今天**：设 `ADMIN_PASSWORD` / `DJANGO_SECRET_KEY` 环境变量（H1、H3）。换密钥前先跑一次兑换码重加密脚本，否则存量兑换码作废。
2. **本周**：登录失败限速（M1）；`SESSION_COOKIE_SECURE=1` + HTTPS（M5）。
3. **排期**：`catalog` 的 `Prefetch` 失效（P1-7）、publishing inbox 批量 finalize（P1-8）、6 处典型 N+1（P2-9）、规则/权重缓存（P2-12）；换 gunicorn（P2-11）。
