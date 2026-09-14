# KFlow Homepage

企业产品官网 + 后台管理，运行于 Django 5.2 LTS。

## 功能

- 用户邮箱验证注册
- 支持账号密码、邮箱验证码、邮箱密码三种登录方式
- 官网展示已发布产品
- 产品详情（简介、更新日志、哈希）
- 代码包下载（记录下载次数）
- “显影”图片生成：登录用户独立历史，积分扣费与失败退款可追溯
- K 士多：主管理员维护加密数字兑换码库存，用户用 K 积分兑换
- 后台登录、产品新增/编辑/删除
- 代码包上传并绑定产品

## 目录

- `manage.py` / `kflow/`：Django 项目入口与配置
- `apps/`：Django 领域应用和 legacy-compatible Models
- `start.sh`：带 WAL 安全备份、迁移和健康检查的推荐启动方式
- `static/`：前端页面与样式
- `uploads/`：上传的代码包
- `data/homepage.db`：SQLite 数据库

## 启动

```bash
cd homepage
./start.sh
```

默认地址：`http://127.0.0.1:9000`

## 重新部署（后台运行与外部访问）

使用当前工作区代码重新部署：

```bash
./redeploy.sh
```

拉取 Git 最新代码后重新部署，并验证公网域名：

```bash
PUBLIC_URL=https://你的域名/ ./redeploy.sh --pull
```

脚本默认监听 `0.0.0.0:9000`，会自动安装依赖、检查 Django、备份数据库、执行迁移、停止旧进程，并通过 `setsid` 在后台启动 Web 服务和显影 worker。可用 `HOST`、`PORT`、`PUBLIC_URL` 覆盖监听地址、端口和公网健康检查地址。公网访问还需确保防火墙已开放对应端口，或由 Caddy/Nginx 将域名反向代理到该端口；域名或公网 IP 也必须包含在 `.env` 的 `ALLOWED_HOSTS` 中。

## Django 迁移开发命令

```bash
.venv/bin/pip install -r requirements.txt
.venv/bin/python manage.py check
.venv/bin/python manage.py migrate --fake-initial
.venv/bin/python manage.py test
.venv/bin/python manage.py audit_legacy_database
.venv/bin/python manage.py cleanup_sessions
.venv/bin/python manage.py cleanup_upload_sessions
.venv/bin/python manage.py process_imaging_jobs --once
```

`start.sh` 会在应用迁移前自动备份 `data/homepage.db`，迁移后幂等同步成就、教程和词条，并尝试安装榜单定时任务，然后启动 Django `runserver`。生产环境应使用 Gunicorn/Uvicorn 等进程管理器承载 `kflow.wsgi:application` 或 `kflow.asgi:application`。

显影使用本机 CPA 的 OpenAI-compatible 图片接口。请通过环境变量配置：

```bash
CPA_BASE_URL=http://127.0.0.1:8317/v1
CPA_API_KEY=your-cpa-key
```

`CPA_BASE_URL` 表示 OpenAI-compatible API 根地址。裸域名会自动补为 `/v1`，例如 `https://gateway.example.com` 会使用 `https://gateway.example.com/v1/images/generations`；已经包含代理路径的地址（例如 `https://gateway.example.com/openai/v1`）会保留原路径。管理员后台的“配置检查”仅调用 `/models` 验证密钥和模型可见性，不会生成图片或产生生图费用。

单次生成默认消耗 10 积分，可在管理员积分设置接口中调整 `image_generation_default_cost`。相同用户在 30 天内提交完全相同的提示词、尺寸、质量和格式时，会复用已有图片但仍按原价扣除积分；可通过 `IMAGING_CACHE_DAYS` 调整有效期。生成图片保存前会按所选 PNG/JPEG/WebP 格式进行压缩优化，并保持原始像素尺寸。

显影任务会先写入数据库，再由后台 worker 执行；关闭浏览器不会中断任务，服务进程意外退出后，worker 会将超时的中断任务重新排队，且不会重复扣除积分。图片预览支持私有浏览器缓存、ETag 和 Last-Modified 条件请求。

`start.sh` 会自动启动显影 worker。若使用 Gunicorn/Uvicorn 或手工启动 Django，请额外运行一个长期 worker：

```bash
.venv/bin/python manage.py process_imaging_jobs --interval 2
```

也可以使用 `--once` 手动处理当前队列并退出。

生产部署前运行：

```bash
.venv/bin/python manage.py collectstatic --noinput
```

应由 Nginx/CDN 从 `.staticfiles/` 提供带内容哈希的静态资源，并为这些哈希文件设置 `Cache-Control: public, max-age=31536000, immutable`。Django 已启用 GZip 中间件压缩适合压缩的文本响应。

## K 士多

- `/store`：查看可兑换的数字商品、库存和本人兑换码；兑换采用幂等键，库存、扣分和发码处于同一事务。

## 管理后台

- 统一登录与注册页：`/login`
- 访问旧入口 `/admin/login` 或 `/admin/register` 会跳转到 `/login?next=/admin`
- 注册时填写有效管理员邀请码，会同时创建普通用户身份和管理员身份；一次登录即可访问前台与后台
- 默认账号：`admin`
- 默认密码：`admin123`

建议生产前通过环境变量覆盖：

```bash
ADMIN_USERNAME=your_admin ADMIN_PASSWORD=your_password PORT=9000 ./start.sh
```

## 用户注册与邮箱验证码

普通用户在 `/login` 页面完成注册。注册信息包括账号、邮箱、密码和 6 位邮箱验证码；登录不再自动创建账号。

邮件发送使用通用 SMTP，请复制 `.env.example` 中的配置并填写邮箱服务商提供的 SMTP 地址与授权码：

```bash
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=no-reply@example.com
SMTP_PASSWORD=your-mailbox-app-password
SMTP_FROM=KFlow <no-reply@example.com>
SMTP_USE_TLS=true
SMTP_USE_SSL=false
SMTP_TIMEOUT_SECONDS=10
```

- STARTTLS 通常使用端口 `587`，设置 `SMTP_USE_TLS=true`。
- SMTP SSL 通常使用端口 `465`，设置 `SMTP_USE_SSL=true`、`SMTP_USE_TLS=false`。
- `SMTP_PASSWORD` 应填写邮箱服务商生成的应用专用密码或 SMTP 授权码，不要提交真实凭据。
- 验证码有效期为 10 分钟，同一邮箱 60 秒内不可重复发送。
- 历史未验证账号不能继续直接登录；需在注册页使用原账号和原密码，通过邮箱验证码完成激活。

## 上传限制

- 类型：`.zip`, `.rar`, `.7z`, `.tar`, `.gz`, `.tgz`
- 大小：最大 500MB

## 说明

- 仅对 `published` 状态的产品开放下载。
- 删除产品会同时删除其上传包文件。

### 显影原图下载

新生成的图片分别保存压缩预览和服务商返回的原始文件。原始文件保存在 `data/imaging-originals/` 私有目录，备份时需同时备份此目录，不能由静态服务器公开。每次点击下载须确认支付 1 积分；同一请求的网络重试不会重复扣分。取消、余额不足或原图缺失时不扣分。历史图片未保留原始文件，页面显示“原图未保留”，也不会作为新生成任务的缓存来源。

更新后执行 `.venv/bin/python manage.py migrate imaging` 并由运行环境负责人重启应用。原图下载接口为 `POST /api/imaging/generations/<id>/download`，JSON 请求包含 `confirmed: true` 和 UUID 格式的 `idempotency_key`；成功返回原始文件及 `X-Points-Balance` 余额响应头，禁止缓存。
