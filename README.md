# KFlow Homepage

企业产品官网 + 后台管理，运行于 Django 5.2 LTS。

## 功能
- 用户邮箱验证注册
- 支持账号密码、邮箱验证码、邮箱密码三种登录方式
- 官网展示已发布产品
- 产品详情（简介、更新日志、哈希）
- 代码包下载（记录下载次数）
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

## Django 迁移开发命令

```bash
.venv/bin/pip install -r requirements.txt
.venv/bin/python manage.py check
.venv/bin/python manage.py migrate --fake-initial
.venv/bin/python manage.py test
.venv/bin/python manage.py audit_legacy_database
.venv/bin/python manage.py cleanup_sessions
.venv/bin/python manage.py cleanup_upload_sessions
```

`start.sh` 会在应用迁移前自动备份 `data/homepage.db`，然后启动 Django `runserver`。生产环境应使用 Gunicorn/Uvicorn 等进程管理器承载 `kflow.wsgi:application` 或 `kflow.asgi:application`。

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
