# KFlow 全量迁移至 Django 设计规范

- 日期：2026-08-01
- 状态：已获用户口头批准，等待书面规范复核
- 方案：原地全量替换，保留数据与外部契约
- 目标框架：Django 5.2 LTS（`Django>=5.2,<5.3`）

## 1. 目标

将 KFlow Homepage 从基于 Python 标准库的自研 HTTP 服务完整迁移为 Django 应用。

迁移完成后：

1. HTTP 请求由 Django WSGI/ASGI 栈处理；
2. URL 由 Django URLconf 管理；
3. 数据访问由 Django ORM 和事务系统管理；
4. 用户认证、Session、权限和 CSRF 接入 Django 生命周期；
5. 静态页面、上传下载、积分、审批与后台管理行为保持兼容；
6. 现有 `data/homepage.db` 可原地升级，业务数据和主键不丢失；
7. 旧 `ThreadingHTTPServer`、`AppHandler`、自建路由注册器及手写 SQLite 连接层全部退出运行链路并最终删除。

## 2. 已确认的兼容边界

采用最保守的兼容策略：

- 保留现有 SQLite 文件位置：`data/homepage.db`；
- 保留现有业务表名与已有主键；
- 保留全部现有 API URL；
- 保留 JSON 字段、HTTP 状态码和主要错误结构；
- 保留现有页面 URL；
- 保留 `user_session` Cookie 名称；
- 兼容尚未过期的旧 `user_session` / `admin_session`；
- 保留 `uploads/` 和 `Material/` 文件路径；
- 保留用户、管理员、积分、审批、下载和产品历史；
- 保留当前单机启动方式和 `PORT`、SMTP、管理员环境变量。

不在本次迁移中进行：

- 视觉重设计；
- API v2 或字段重命名；
- SQLite 到 PostgreSQL/MySQL 的切换；
- 产品规则、积分规则或管理员等级规则重做；
- 引入 Django REST Framework；
- 删除现有业务数据。

## 3. 当前系统基线

当前运行链路由以下部分组成：

- `server.py` / `app/server.py`：`ThreadingHTTPServer` 启动入口；
- `app/routes.py` / `app/utils/routes.py`：自建正则路由；
- `app/handlers/base.py`：请求、响应、认证、静态文件和 Dashboard 基类；
- `app/handlers/*.py`：61 条 HTTP 路由对应的领域函数；
- `app/db/*.py`：SQLite schema、连接复用、备份和初始化；
- `app/services/*.py`：Session、积分、邮件和备份 worker；
- `static/`：无构建步骤的 HTML/CSS/JS；
- `tests/`：26 个现有单元及集成测试。

现有业务表共 21 张，另有 1 张 SQLite 内部表：

1. `sessions`
2. `products`
3. `product_packages`
4. `product_versions`
5. `downloads`
6. `download_requests`
7. `users`
8. `point_accounts`
9. `point_ledger`
10. `user_daily_activity`
11. `download_entitlements`
12. `email_verification_codes`
13. `admin_accounts`
14. `admin_register_tokens`
15. `admin_upload_events`
16. `publish_requests`
17. `publish_request_votes`
18. `product_delete_requests`
19. `subscribers`
20. `user_subscriptions`
21. `system_settings`
22. `sqlite_sequence`（SQLite 内部表，不建 Django Model）

## 4. 备选方案与决策

### 4.1 方案 A：原地全量替换（采用）

Django Models 直接映射现有表，Django views 替换全部旧 handlers，迁移结束后删除旧运行链路。

优点：

- 业务数据和 ID 原样保留；
- 前端无需同步推倒重写；
- 最终不存在双框架债务；
- 可用当前 API 测试验证契约。

代价：

- 初始 migrations 必须精确匹配 legacy schema；
- 密码、Session、管理员双身份和 Range 下载需要专门兼容。

### 4.2 方案 B：Django 代理旧 handlers（拒绝）

Django 只做入口，内部仍调用 `AppHandler`。

拒绝原因：旧架构继续存在，不属于全量迁移，并形成双生命周期和双响应对象。

### 4.3 方案 C：新库重建后 ETL（拒绝）

建立全新标准 Django schema，再导入旧数据。

拒绝原因：用户 ID、外键、积分幂等键和下载凭证存在迁移偏移风险，且不符合原地兼容要求。

## 5. 目标目录结构

```text
manage.py
kflow/
  __init__.py
  settings.py
  urls.py
  wsgi.py
  asgi.py

apps/
  core/
    middleware.py
    responses.py
    permissions.py
    files.py
    management/commands/
  accounts/
    models.py
    backends.py
    hashers.py
    views.py
    urls.py
    services.py
  catalog/
    models.py
    views.py
    urls.py
    services.py
  downloads/
    models.py
    views.py
    urls.py
    services.py
  points/
    models.py
    views.py
    urls.py
    services.py
  publishing/
    models.py
    views.py
    urls.py
    services.py
  dashboard/
    views.py
    urls.py
    services.py

templates/
static/
uploads/
data/homepage.db
```

约束：

- views 负责 HTTP I/O；
- services 负责事务和业务规则；
- models 只维护数据结构和局部领域行为；
- 不把所有逻辑重新堆进单个 Django view；
- 不把旧 handler 当作长期兼容层。

## 6. Django 配置

### 6.1 基础设置

- `BASE_DIR` 指向仓库根目录；
- SQLite `NAME` 指向 `data/homepage.db`；
- `STATIC_URL=/static/`，静态目录继续使用现有 `static/`；
- `MEDIA_ROOT=uploads/`；
- `MATERIAL_ROOT=Material/`；
- 时区采用 `Asia/Shanghai`，数据库时间统一使用 timezone-aware datetime；
- `SESSION_COOKIE_NAME=user_session`；
- `SESSION_COOKIE_HTTPONLY=True`；
- `SESSION_COOKIE_SAMESITE=Lax`；
- 生产环境通过环境变量控制 `DEBUG`、`SECRET_KEY`、`ALLOWED_HOSTS`；
- `.env` 保留现有轻量读取方式，或在 settings 中实现等价安全加载，不新增 dotenv 依赖。

### 6.2 依赖

`requirements.txt` 改为：

```text
Django>=5.2,<5.3
```

本次不强制引入 DRF、Celery、Redis 或第三方调度器。

## 7. 数据模型设计

### 7.1 Legacy schema 接管原则

每个业务 Model：

- 设置原始 `db_table`；
- 显式声明原字段名和 `db_column`；
- 保留主键值；
- 使用 `managed=True`，使后续 schema 由 Django migrations 管理；
- 第一版 migration 必须与当前表结构一致；
- 现有数据库执行 `migrate --fake-initial` 接管基线；
- 全新数据库执行普通 `migrate` 创建相同表；
- 为两条路径分别建立自动化测试。

不使用 `inspectdb` 输出作为最终模型；可用于交叉核对，但关系、空值、默认值、索引与级联行为必须人工确认。

### 7.2 Model 归属

#### accounts

- `User` → `users`
- `AdminAccount` → `admin_accounts`
- `AdminRegisterToken` → `admin_register_tokens`
- `EmailVerificationCode` → `email_verification_codes`
- `LegacySession` → `sessions`（只用于旧 Session 兼容和过期清理）
- `Subscriber` → `subscribers`
- `UserSubscription` → `user_subscriptions`

#### catalog

- `Product` → `products`
- `ProductPackage` → `product_packages`
- `ProductVersion` → `product_versions`
- `AdminUploadEvent` → `admin_upload_events`
- `SystemSetting` → `system_settings`

#### downloads

- `Download` → `downloads`
- `DownloadRequest` → `download_requests`
- `DownloadEntitlement` → `download_entitlements`

#### points

- `PointAccount` → `point_accounts`
- `PointLedger` → `point_ledger`
- `UserDailyActivity` → `user_daily_activity`

#### publishing

- `PublishRequest` → `publish_requests`
- `PublishRequestVote` → `publish_request_votes`
- `ProductDeleteRequest` → `product_delete_requests`

### 7.3 外键与删除策略

迁移后的 ORM 关系必须匹配现有业务语义：

- 产品包、版本、下载、审批记录关联产品；
- 积分账户、流水、每日活跃和下载凭证关联用户；
- 删除产品仍通过受控 service 删除文件和关联数据；
- 不依赖不明确的数据库级级联；
- 涉及文件删除时采用“数据库事务决策 + 提交后文件清理”，避免数据库回滚但文件已丢失。

## 8. 认证与 Session

### 8.1 Django 用户模型

`AUTH_USER_MODEL` 使用映射 `users` 表的自定义 `User`。

为保持初始 schema 精确兼容：

- `password` 继续映射现有字段；
- `username` 继续作为 `USERNAME_FIELD`；
- `created_at` 作为注册时间；
- `email_verified_at` 保留；
- `is_active` 默认由账户状态规则计算；
- `is_staff` / `is_superuser` 从 `AdminAccount` 派生；
- 当前系统不依赖 Django 内置 Group/Permission 表完成 lv1/lv2/lv3 授权。

### 8.2 旧密码兼容

现有密码格式：

```text
pbkdf2_sha256$<iterations>$<hex-salt>$<hex-digest>
```

实现 `LegacyHexPBKDF2PasswordHasher`：

1. 识别并验证旧格式；
2. 登录成功后调用 Django `set_password()` 自动升级为 Django 标准格式；
3. 对历史明文兼容仅保留现有一次性验证逻辑，成功后立即重哈希；
4. 新密码全部使用 Django 默认 PBKDF2 hasher；
5. 测试验证升级前后账号均可登录。

### 8.3 管理员身份

- 普通用户记录保存在 `users`；
- 管理权限来源于同 username 的 `admin_accounts`；
- 注册时使用有效管理员邀请码，原子创建/升级用户与管理员身份；
- `admin_level` 保留 lv1/lv2/lv3；
- `is_super` 保留主管理员语义；
- 权限 decorators 返回与旧接口一致的 401/403。

### 8.4 Session 切换

新 Session 使用 Django session engine，Cookie 仍名为 `user_session`。

兼容 middleware：

1. 优先解析 Django session；
2. 若失败，读取旧 `user_session` 或 `admin_session` token；
3. 通过 `LegacySession` 校验 token 和过期时间；
4. 恢复用户/管理员身份并创建 Django session；
5. 删除或标记已迁移的 legacy session；
6. 兼容期结束后删除旧 Session 读取代码，但保留历史表直到明确清理。

## 9. HTTP 与 API 设计

### 9.1 响应契约

使用 Django `JsonResponse` 和统一异常转换函数，保留：

- JSON key；
- HTTP status；
- `error` 字段；
- 成功响应中的 `ok`、`items`、分页和统计字段；
- 401、403、404、409、410、429、503 等语义。

不得依赖 Django 默认 HTML 错误页处理 `/api/` 请求。

### 9.2 CSRF

- GET/HEAD 保持无副作用；
- 登录后写操作启用 Django CSRF；
- 现有 HTML 注入或读取 `csrftoken`；
- `fetch()` 统一发送 `X-CSRFToken`；
- 邮箱验证码、登录、注册等匿名写接口使用明确的 CSRF 策略和 SameSite/Origin 校验；
- 不以全局 `csrf_exempt` 作为最终方案。

### 9.3 页面与静态文件

页面 URL 保持不变：

- `/`
- `/login`
- `/account`
- `/points`
- `/admin`
- `/admin/bigscreen`
- `/product/<slug>`
- `/cardloom`

现有 HTML 迁入 templates 或由 Django `TemplateView` 服务。CSS/JS 和媒体资源继续放置于 static；前端业务行为只修改认证、CSRF 和必要的 API 适配部分。

旧入口：

- `/admin/login`
- `/admin/register`

继续 302 到 `/login?next=/admin`。

## 10. 领域迁移

### 10.1 accounts

迁移：

- 邮箱验证码发送、频率限制和尝试次数；
- 注册和 legacy 账户升级；
- username/password、email/code、email/password 三种登录；
- 邮箱绑定；
- 用户/管理员统一登录；
- 邀请码消费；
- 管理员列表和用户列表；
- 登录、登出、当前身份接口。

数据库写操作使用 `transaction.atomic()`；邀请码和验证码消费使用 `select_for_update()` 或 SQLite 可实现的等价原子条件更新。

### 10.2 catalog

迁移：

- 产品公开列表和 meta；
- 产品详情；
- 管理端产品 CRUD；
- 名称/slug 重复校验；
- 产品包管理；
- 版本快照和回滚；
- 发布状态；
- 上传限制设置。

### 10.3 downloads

迁移：

- 下载申请；
- 管理员审批；
- 免费次数与批准凭证；
- 积分兑换凭证；
- 下载历史；
- 文件 SHA-256；
- 下载统计；
- 多包查询参数 `?pkg=<id>`；
- HTTP Range、206、Content-Range、Content-Length；
- 分片上传、完成、过期清理和累计大小限制。

分片状态不继续保存在进程级 dict；改为数据库模型或受控临时目录元数据，使多线程/重启后行为可预测。

### 10.4 points

保留：

- 注册奖励；
- 每日活跃奖励；
- 手工积分调整；
- 冻结/解冻；
- 下载兑换；
- `idempotency_key`；
- 余额、累计获得、累计消费和贡献值；
- 积分流水分页。

所有余额变更必须位于同一 `transaction.atomic()` 中，并以条件更新/锁和唯一幂等键防止重复消费。

### 10.5 publishing

保留：

- 发布申请；
- reviewer scope；
- lv2/lv3 权重；
- 超时决策；
- 投票幂等；
- 删除申请；
- 管理员 inbox 聚合。

### 10.6 dashboard

Dashboard 通过 ORM 和受控数据库元数据查询生成：

- 服务状态；
- Session 数量；
- 产品、用户、下载和审批指标；
- 允许展示的表快照；
- 敏感字段遮罩。

不允许通过客户端输入任意表名执行 SQL。

## 11. 上传、下载与文件一致性

### 11.1 上传

- Django 上传大小配置与现有限制一致；
- 分片直接流式写盘，禁止整块读入内存；
- 校验 upload session owner、chunk index、总大小和 SHA-256；
- 完成后使用原子 rename；
- 失败时清理临时文件；
- 文件路径仍保存相对仓库路径或受控 media 相对路径。

### 11.2 下载

- 使用 Django streaming response；
- 自定义 Range 解析并返回 206；
- 非法范围返回 416；
- 正确设置 `Accept-Ranges`、`Content-Range`、`Content-Length` 和 `Content-Disposition`；
- 下载资格和凭证消费与下载记录写入保持原子；
- 文件不存在不消耗凭证。

## 12. 邮件与后台任务

SMTP 改为 Django email backend，继续读取：

- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `SMTP_FROM`
- `SMTP_USE_TLS`
- `SMTP_USE_SSL`
- `SMTP_TIMEOUT_SECONDS`

后台维护改为 management commands：

- `cleanup_sessions`
- `backup_database`
- `cleanup_upload_sessions`

不在 `AppConfig.ready()` 启动无限循环，避免 autoreload 或多 worker 重复执行。

当前单机模式下，`start.sh`：

1. 检查 Python 和依赖；
2. 执行 `manage.py migrate --noinput`；
3. 执行一次数据库备份；
4. 以 `python manage.py runserver 0.0.0.0:$PORT --noreload` 启动当前单机服务；
5. 保留 PID、端口和日志提示。

周期任务通过 cron/systemd timer 或单独 management command 进程运行，不绑死在 Web worker 生命周期。

## 13. URL 契约清单

迁移后必须保留以下 61 条路由及其精确匹配语义。

### GET

- `/api/health`
- `/api/admin/dashboard`
- `/material/<path>`
- `/api/user/me`
- `/api/account/me`
- `/api/user/history`
- `/api/user/download-quota`
- `/api/user/requests`
- `/api/user/notifications`
- `/api/points/me`
- `/api/points/rules`
- `/api/points/ledger`
- `/api/points/download-entitlements`
- `/api/admin/download-requests`
- `/api/admin/users`
- `/api/admin/me`
- `/api/admin/tokens`
- `/api/admin/upload-settings`
- `/api/admin/points/settings`
- `/api/admin/points/accounts`
- `/api/admin/publish-requests`
- `/api/admin/inbox`
- `/api/products`
- `/api/products/meta`
- `/api/products/<slug>`
- `/api/admin/versions/<id>`
- `/api/admin/products/<id>/packages`
- `/api/admin/products`
- `/api/admin/products/<id>`
- `/download/<slug>`

### POST

- `/api/admin/register`（保持 410）
- `/api/admin/login`
- `/api/admin/logout`
- `/api/admin/tokens`
- `/api/admin/upload-settings`
- `/api/admin/points/settings`
- `/api/admin/points/adjust`
- `/api/admin/points/freeze`
- `/api/admin/points/unfreeze`
- `/api/admin/publish-requests`
- `/api/admin/publish-requests/<id>/vote`
- `/api/admin/delete-requests/<id>/approve`
- `/api/admin/delete-requests/<id>/reject`
- `/api/admin/versions/<id>/rollback`
- `/api/user/verification-code`
- `/api/user/register`
- `/api/user/login`
- `/api/user/email/bind`
- `/api/user/logout`
- `/api/points/redeem-download`
- `/api/subscribe`
- `/api/products/<slug>/request-download`
- `/api/admin/products`
- `/api/admin/products/<id>/upload`
- `/api/admin/download-requests/<id>/approve`
- `/api/admin/download-requests/<id>/reject`
- `/api/admin/products/<id>/upload-sessions`
- `/api/admin/upload-sessions/<id>/complete`
- `/api/admin/upload-sessions/<id>/chunks/<index>`

### PUT

- `/api/admin/products/<id>`

### DELETE

- `/api/admin/packages/<id>`
- `/api/admin/products/<id>`

## 14. 数据迁移与回滚

### 14.1 迁移前

- 检查工作区和数据库文件；
- 对 `homepage.db` 执行 SQLite backup API；
- 记录所有业务表 row count；
- 记录关键表主键最大值；
- 执行 `PRAGMA integrity_check`；
- 检查 WAL/SHM 状态；
- 阻止 Web 写入后再进行正式切换。

### 14.2 基线接管

- 第一批 Django migrations 精确描述现有业务表；
- 现有库使用 `--fake-initial`；
- Django 自带表正常创建；
- 后续 migration 添加 Django 所需的辅助表或索引；
- migration 前后执行 schema diff 和数据计数对比。

### 14.3 回滚

发生失败时：

1. 停止 Django 服务；
2. 恢复迁移前 SQLite backup；
3. 恢复旧启动提交或旧可执行入口；
4. 验证 health、登录和产品列表；
5. 不在失败现场继续手改生产数据库。

## 15. 测试策略

### 15.1 迁移现有测试

当前 26 个测试全部改为 Django `TestCase` / `TransactionTestCase` / test client，保持原断言语义。

覆盖：

- 三种登录；
- legacy 用户升级；
- 管理邀请码；
- SMTP 失败；
- 验证码次数和过期；
- admin 页面重定向；
- 下载 query string；
- 积分幂等和原子性。

### 15.2 新增测试

- 61 条 URL 名称、method 和 exact match；
- API JSON contract 快照；
- 旧密码首次登录自动升级；
- 旧 Session 换发 Django session；
- existing DB `--fake-initial`；
- fresh DB 普通 migrate；
- 迁移前后 row count 与主键一致；
- 分片上传重启恢复；
- Range 206/416；
- 下载凭证并发消费；
- CSRF；
- 文件缺失不扣额度；
- 产品删除的数据库/文件一致性；
- start.sh 启动和 `/api/health`。

## 16. 实施顺序

1. 建立 Django project、settings、URLconf 和测试基座；
2. 建立 legacy-compatible Models 和 initial migrations；
3. 接管认证、密码和 Session；
4. 迁移公开产品及静态页面；
5. 迁移用户中心和下载；
6. 迁移积分；
7. 迁移后台产品、上传和版本；
8. 迁移发布/删除审批；
9. 迁移 Dashboard 和维护命令；
10. 更新前端 CSRF 和启动脚本；
11. 数据库原地迁移演练；
12. 全量测试与旧代码删除；
13. 最终切换和回滚演练。

每一步必须保持测试可运行；不能在所有模块尚未接管时提前删除旧实现。

## 17. 完成定义

只有同时满足以下条件才算“全量迁移完成”：

- Django 是唯一 Web 运行入口；
- 61 条现有 API 路由完成迁移；
- 所有现有页面可访问；
- 21 张现有业务表完成 ORM 接管；SQLite 内部表不纳入 ORM；
- 现有数据库原地升级成功且业务 row count/主键一致；
- 旧账号、密码和 Session 兼容验证通过；
- 上传、分片、Range 下载、积分和审批通过回归；
- 现有测试迁移并全部通过；
- 新增迁移、契约和文件传输测试通过；
- `requirements.txt` 包含 Django；
- `start.sh` 使用 Django 启动；
- `ThreadingHTTPServer`、`AppHandler`、自建 routes、手写 DB connection wrapper 不再存在；
- 文档不再宣称“无第三方依赖”；
- 工作区无未解释的迁移残留；
- 已形成可执行回滚方案并完成至少一次演练。

## 18. 风险与控制

### 高风险：认证格式

控制：Legacy hasher、登录升级测试、真实备份副本演练。

### 高风险：legacy schema 与 migration state 不一致

控制：精确 0001 基线、existing/fresh 双路径测试、schema diff。

### 高风险：SQLite 并发积分消费

控制：短事务、唯一幂等键、条件更新、`TransactionTestCase` 并发验证。

### 高风险：大文件内存占用

控制：上传和下载均流式处理，测试 500MB 边界时使用稀疏/生成文件，避免内存复制。

### 高风险：双服务切换期间写入分叉

控制：正式切换采用短暂停写，不使用双写；备份后一次性切换。

### 中风险：CSRF 导致旧前端写接口失败

控制：统一 fetch helper、页面级冒烟测试、禁止永久全局豁免。

### 中风险：后台 worker 重复执行

控制：维护任务独立 management command，不在 `AppConfig.ready()` 启动循环。
