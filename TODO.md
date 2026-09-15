# KFlow Homepage TODO

迁移已完成，以下是 Django 运行阶段的后续优化，不影响现有页面、API 和 SQLite 数据兼容。

## P1

### 1. 统一超级管理员持久化
- 位置：`apps/accounts/views.py`、`kflow/settings.py`
- 目标：首次部署时将环境变量管理员安全写入 `admin_accounts`，登录逻辑统一走数据库哈希。

### 2. 存储抽象层
- 位置：`apps/downloads/services.py`、`apps/catalog/admin_views.py`
- 目标：抽象本地文件存储接口，为对象存储和签名 URL 做准备。

### 3. 结构化日志与请求 ID
- 位置：Django middleware 和 settings logging 配置
- 目标：为登录、上传、下载、审批和删除动作提供可检索的请求日志。

## P2

### 4. 前端构建拆分
- 位置：`static/`
- 目标：接入构建工具，输出带 hash 的静态资源并降低后台页面首屏体积。

### 5. CI 与覆盖率
- 位置：`apps/*/tests.py`、CI 配置
- 目标：在 CI 中执行 `manage.py check`、迁移漂移检查、测试和关键 HTTP 冒烟。

### 6. 审计日志
- 目标：记录登录、上传、下载、发布、审批、删除和管理员调整等关键动作。

## P3

### 7. 生产部署
- 目标：Gunicorn/Uvicorn、Nginx、TLS、对象存储和 PostgreSQL 按实际并发需求逐步引入。
