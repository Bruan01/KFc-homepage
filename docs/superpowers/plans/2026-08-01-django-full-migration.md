# KFlow Django 全量迁移实施计划

> 设计来源：`docs/superpowers/specs/2026-08-01-django-full-migration-design.md`
>
> 执行原则：每个阶段先建立可验证的 Django 能力，再删除对应旧实现；任何阶段不得破坏现有 SQLite 数据和外部 API 契约。

## 阶段 0：基线与安全护栏

### 任务 0.1：记录工作区和数据基线

- 保留当前用户未提交的 `.gitignore` 改动；
- 将先前生成的 `requirements.txt`、`CLAUDE.md` 调整纳入 Django 迁移提交；
- 记录 61 条现有路由；
- 记录当前数据库表、row count、主键最大值和 `PRAGMA integrity_check`；
- 创建只读/临时数据库验证脚本，不修改生产数据库。

验证：

```bash
git status -sb
python scripts/django_migration_audit.py --database data/homepage.db
```

### 任务 0.2：建立契约测试输入

新增：

- `tests/contracts/routes.json`
- `tests/contracts/schema.json`
- `tests/test_migration_contract.py`

验证旧系统与目标 Django 系统必须满足相同路由和 schema 基线。

## 阶段 1：Django 基座

### 任务 1.1：依赖与项目入口

修改：

- `requirements.txt`
- `README.md`
- `CLAUDE.md`

新增：

- `manage.py`
- `kflow/__init__.py`
- `kflow/settings.py`
- `kflow/urls.py`
- `kflow/wsgi.py`
- `kflow/asgi.py`
- `apps/__init__.py`

设置 SQLite、static、templates、uploads、Material、SMTP、Session Cookie 和环境变量。

验证：

```bash
python manage.py check
python manage.py diffsettings
```

### 任务 1.2：core 基础能力

新增：

- `apps/core/apps.py`
- `apps/core/responses.py`
- `apps/core/permissions.py`
- `apps/core/middleware.py`
- `apps/core/files.py`
- `apps/core/views.py`
- `apps/core/urls.py`

先实现 `/api/health`、统一 JSON 错误、客户端 IP、页面守卫和静态/Material 文件安全响应。

验证：Django test client 返回 health JSON，路径穿越被拒绝。

## 阶段 2：Legacy Models 与 migrations

### 任务 2.1：accounts models

新增：

- `apps/accounts/models.py`
- `apps/accounts/managers.py`
- `apps/accounts/migrations/0001_initial.py`

模型：User、AdminAccount、AdminRegisterToken、EmailVerificationCode、LegacySession、Subscriber、UserSubscription。

### 任务 2.2：catalog models

新增 Product、ProductPackage、ProductVersion、AdminUploadEvent、SystemSetting 及 initial migration。

### 任务 2.3：downloads models

新增 Download、DownloadRequest、DownloadEntitlement 及 initial migration。

### 任务 2.4：points models

新增 PointAccount、PointLedger、UserDailyActivity 及 initial migration。

### 任务 2.5：publishing models

新增 PublishRequest、PublishRequestVote、ProductDeleteRequest 及 initial migration。

### 任务 2.6：existing/fresh 双路径

新增：

- `scripts/django_migration_audit.py`
- `tests/test_django_migrations.py`

验证：

1. 空临时目录普通 `migrate` 创建 21 张业务表；
2. 当前 schema 副本 `migrate --fake-initial` 后可 ORM 查询；
3. row count 与主键不变；
4. Django 自带表正常创建。

## 阶段 3：认证、密码、Session 与权限

### 任务 3.1：Legacy 密码 hasher

新增：

- `apps/accounts/hashers.py`
- `tests/test_django_password_compat.py`

验证旧 hex PBKDF2、历史明文和 Django 新密码；登录成功自动升级。

### 任务 3.2：认证 backend

新增：

- `apps/accounts/backends.py`
- `apps/accounts/services.py`

支持 username/password、email/password、email/code 与管理员身份派生。

### 任务 3.3：Session 兼容 middleware

读取旧 `user_session` / `admin_session`，换发 Django session；新 Cookie 名保持 `user_session`。

### 任务 3.4：账户 API

迁移：

- `/api/user/verification-code`
- `/api/user/register`
- `/api/user/login`
- `/api/user/email/bind`
- `/api/user/logout`
- `/api/user/me`
- `/api/account/me`
- `/api/admin/login`
- `/api/admin/logout`
- `/api/admin/me`
- `/api/admin/register`（410）
- `/api/admin/tokens`
- `/api/admin/users`

将 `tests/test_user_auth.py` 改为 Django client 测试并保持全部旧断言。

## 阶段 4：页面、产品与订阅

### 任务 4.1：页面路由

迁移 `/`、`/login`、`/account`、`/points`、`/admin`、`/admin/bigscreen`、`/product/<slug>`、`/cardloom`、旧 admin 重定向。

### 任务 4.2：公开产品 API

迁移 products、meta、detail；保持 JSON serializer 和 ETag/缓存语义。

### 任务 4.3：订阅和通知

迁移 subscribe、notifications、user history/requests/quota。

验证：页面状态码、重定向和产品 JSON contract。

## 阶段 5：下载、上传与积分

### 任务 5.1：下载资格和 Range

迁移 `/download/<slug>`，支持 `?pkg=`、206、416、流式读取和原子凭证消费。

### 任务 5.2：下载审批

迁移申请、列表、批准、拒绝及用户记录。

### 任务 5.3：分片上传持久化

新增 `UploadSession` Django 模型/表，替代进程 dict；迁移创建、chunk、complete 和超时清理。

### 任务 5.4：积分

迁移 points me/rules/ledger/entitlements/redeem/settings/accounts/adjust/freeze/unfreeze。

使用 `transaction.atomic()`、唯一幂等键和条件更新。

验证：现有 points tests、并发消费、文件缺失不扣额度、分片重启恢复。

## 阶段 6：后台产品、版本和审批

### 任务 6.1：后台产品 CRUD

迁移管理列表、创建、更新、删除、包管理和直接上传。

### 任务 6.2：版本快照与回滚

迁移 versions、rollback 和历史展示。

### 任务 6.3：发布与删除审批

迁移发布申请、投票、inbox、删除批准/拒绝和超时决策。

验证管理员等级、owner 边界、权重和原子状态转换。

## 阶段 7：Dashboard、维护命令与前端安全

### 任务 7.1：Dashboard

通过 ORM/白名单元数据实现统计和表预览，保留敏感字段遮罩。

### 任务 7.2：management commands

新增：

- `cleanup_sessions`
- `backup_database`
- `cleanup_upload_sessions`
- `audit_legacy_database`

### 任务 7.3：CSRF

更新所有静态页面 fetch helper，写请求发送 `X-CSRFToken`；启用 Django CSRF middleware。

### 任务 7.4：启动脚本

修改 `start.sh`：依赖检查、migrate、backup、Django runserver、日志与 PID 检查。

## 阶段 8：切换、清理与验证

### 任务 8.1：删除旧运行链路

删除：

- `app/server.py`
- `app/routes.py`
- `app/utils/routes.py`
- `app/handlers/`
- `app/db/__init__.py`
- 不再需要的旧 services/utils
- 根 `server.py` 旧 shim

仅在 Django 已覆盖全部功能且测试通过后执行。

### 任务 8.2：全量验证

```bash
python manage.py check --deploy
python manage.py makemigrations --check --dry-run
python manage.py test
python scripts/django_migration_audit.py --database <backup-copy>
./start.sh
curl -i http://127.0.0.1:$PORT/api/health
```

验证 61 条路由、页面、认证、上传、下载、积分、审批和 Dashboard。

### 任务 8.3：回滚演练

在临时副本执行：旧库备份 → Django migrate → 验证 → 恢复备份 → 验证旧提交可启动。

## 提交策略

建议按阶段提交：

1. `chore: scaffold Django project`
2. `feat: map legacy database models`
3. `feat: migrate authentication to Django`
4. `feat: migrate catalog and public pages`
5. `feat: migrate downloads uploads and points`
6. `feat: migrate admin publishing and dashboard`
7. `refactor: remove legacy HTTP server`
8. `test: verify Django migration compatibility`
9. `docs: document Django operation and rollback`

每次提交前执行该阶段相关测试与 `git diff --check`。
