# KFlow Homepage

企业产品官网 + 后台管理，正在全量迁移至 Django 5.2 LTS。

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
- `server.py` / `app/`：迁移期间保留的旧服务，完成切换后删除
- `static/`：前端页面与样式
- `uploads/`：上传的代码包
- `data/homepage.db`：SQLite 数据库

## 启动
```bash
cd homepage
python3 server.py
```

默认地址：`http://127.0.0.1:8088`

## Django 迁移开发命令

```bash
.venv/bin/pip install -r requirements.txt
.venv/bin/python manage.py check
.venv/bin/python manage.py migrate --fake-initial
.venv/bin/python manage.py test
```

正式数据库迁移前必须先备份 `data/homepage.db`。当前 `start.sh` 在 API 全量接管前仍启动旧服务。

## 管理后台
- 统一登录与注册页：`/login`
- 访问旧入口 `/admin/login` 或 `/admin/register` 会跳转到 `/login?next=/admin`
- 注册时填写有效管理员邀请码，会同时创建普通用户身份和管理员身份；一次登录即可访问前台与后台
- 默认账号：`admin`
- 默认密码：`admin123`

建议生产前通过环境变量覆盖：
```bash
ADMIN_USERNAME=your_admin ADMIN_PASSWORD=your_password PORT=8088 python3 server.py
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
