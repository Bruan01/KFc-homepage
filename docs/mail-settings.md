# 系统邮箱设置（后台）

后台位置：`/admin/settings` → 系统邮箱设置，仅 **lv3 及以上 / 主管理员**可见可改。

## 一、配置优先级

```
system_settings 里的 mail_smtp_*   ← 后台表单写入，优先
        ↓ 没有 host 时回落
settings.EMAIL_*（.env 的 SMTP_*）  ← 老部署不动也照常工作
        ↓ 都没有
未配置 → 发信直接报 503，不静默失败
```

关键实现：`apps/accounts/mailing.py::load_config()`。`source` 字段会告诉前端当前用的是哪一层（`database` / `environment` / `none`）。

## 二、存了哪些键

| key | 说明 |
|---|---|
| `mail_smtp_host` / `mail_smtp_port` | 主机与端口 |
| `mail_smtp_username` | 账号 |
| `mail_smtp_password_enc` | **密码密文**（Fernet，密钥由 `SECRET_KEY` 派生） |
| `mail_smtp_from` | 发件人，留空则用账号 |
| `mail_smtp_use_tls` / `mail_smtp_use_ssl` | 二者互斥，同时为真会被拒 |
| `mail_smtp_timeout` | 1–60 秒 |
| `mail_event_user_registered` | JSON：`{enabled, admins, emails}` |

密码永不出库明文，接口只回 `passwordSet: true`。表单留空 = 保持原密码，换密码才填。

> `SECRET_KEY` 换了会导致旧密文解不开，`decrypt_secret()` 会打 warning 并返回空串——这时在后台重填一次密码即可。

## 二之二、邮件正文模板

`apps/accounts/mail_templates.py` 提供三类 HTML：验证码、注册通知、测试邮件。
每封都是 `text/plain` + `text/html` 双版本（`EmailMultiAlternatives`），
纯文本客户端也能正常阅读。

改模板时的三条红线：

1. **只用 table 布局** —— Outlook 用 Word 引擎渲染，flex / grid 全部失效
2. **样式必须内联** —— Gmail 会剥掉 `<head>` 里的 `<style>`
3. **图片必须是公网绝对地址** —— 邮件客户端不认相对路径，也不支持 SVG，所以 logo 用的是
   `static/kflow-mark-light.png` / `kflow-mark-dark.png`（由 `kflow-mark.svg` 渲染出的 320px PNG）

logo 与按钮都拼在 `SITE_BASE_URL` 上：

```bash
# .env
SITE_BASE_URL=https://你的域名
```

不配则默认 `http://127.0.0.1:9000`，本地预览能加载，线上会显示破图。

页脚统一包含「这封邮件由 KFlow 系统自动发送」和「如果不是你本人的操作，忽略即可」。
事件通知的页脚会说明为什么收到（后台开关 + 收件人来源）。

## 三、投递日志（`email_deliveries`）
每条信都先落 `pending` 再发，成功改 `sent`，失败改 `failed` 并保留原始 `error`。

| 字段 | 说明 |
|---|---|
| `category` | `verification` 验证码 / `event` 事件通知 / `test` 测试与重发 |
| `event` | `verification_register` / `verification_login` / `verification_bind` / `user_registered` / `manual_test` / `manual_retry` |
| `to_email` | 多个收件人用 `, ` 连接 |
| `status` | `pending` / `sent` / `failed` |
| `error` | 原始异常（后台显示时经 `friendly_error()` 翻译成可操作提示） |

后台统计口径：累计、今日（**Asia/Shanghai 本地日界**）、近 7 天、失败数、成功率、近 7 日每日柱状。

## 四、事件通知

后台的收件人选择是一个**拖拽池**：左边是所有管理员（圆圈），右边是篮子。
把圆圈拖进篮子 = 选中，事件触发时只发给篮子里的人。

- **绑了邮箱的圆圈是绿色**，可以拖；没绑的是灰色，拖不动，点击会弹出绑定邮箱的输入框
- 也可以直接点圆圈加入/移出，触屏和键盘都能用（拖拽不是唯一路径）
- 篮子里点 chip 可以移出
- 额外收件邮箱（逗号分隔）与篮子是**并集**，会去重
- 发信跑在后台线程（`daemon=True`），SMTP 慢或挂掉都**不影响注册响应**
- 线程里动手前 `close_old_connections()`，避免连接泄漏

存储结构：

```json
// system_settings.mail_event_user_registered
{ "enabled": true, "recipients": ["ops", "kieran"], "emails": ["extra@example.com"] }
```

`recipients` 存的是**管理员用户名**，解析时才查邮箱，所以改了管理员邮箱不需要重存名单。
没绑邮箱的用户名在保存时会被静默剔除，不允许进篮子。

> **向后兼容**：老配置里的 `"admins": true`（发给全体）读出来会标成 `selectAll`，
> 由 `resolve_recipients()` 展开成全员，升级不会让线上已有的开关失效。一旦在后台保存一次，
> 结构就固化成明确的 `recipients` 列表。

### 管理员邮箱从哪来

`admin_accounts.email` 只在「注册成管理员」时写入，没有独立的编辑页。
所以拖拽池里灰色圆圈点一下会弹输入框，直接补绑——这个邮箱**只用于收通知**，
不改 `users.email`，不影响该账号的登录方式。

超级管理员（`ADMIN_USERNAME` 环境变量配置的那个）不在 `admin_accounts` 表里，
不会出现在池子里。这种情形直接在「额外收件邮箱」填地址即可。

## 五、接口

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/api/admin/mail/settings` | 配置 + 事件 + 统计 + 最近 10 条 |
| POST | `/api/admin/mail/settings` | 保存，body 可只含 `config` 或 `events` |
| POST | `/api/admin/mail/test` | 发测试信，`{to}` 可省略（回落到当前管理员） |
| GET | `/api/admin/mail/deliveries` | 分页，支持 `status` / `event` 过滤 |
| POST | `/api/admin/mail/deliveries/<id>/retry` | 重发，生成一条 `manual_retry` 记录 |
| POST | `/api/admin/mail/admin-email` | 给管理员补绑接收通知的邮箱（只写 `admin_accounts.email`） |
| GET | `/api/admin/mail/capabilities` | 轻量探测：是否已配置、用的哪层 |

全部 `require_admin(3)`，返回 `Cache-Control: private, no-store`。

## 六、验证码链路的影响

`apps/accounts/services.py::_send_code()` 改成走 `send_mail_logged()`：

- 原来 `_email_backend_available()` 只看 `EMAIL_HOST`，现在看 `load_config().configured`
- 发信失败仍然抛 `AccountError(503)`，注册/登录接口行为不变
- 好处：验证码也进投递日志，用户在后台能查到「到底发了没有」

## 七、排查清单

| 现象 | 先看哪 |
|---|---|
| 点「发送测试邮件」报 502 | 错误文案已带原始异常，按提示改主机/端口/加密方式 |
| 报 `CERTIFICATE_VERIFY_FAILED` | Python 缺根证书。代码会在 `_ensure_ca_bundle()` 里自动回填 `SSL_CERT_FILE`（macOS 用 `/etc/ssl/cert.pem`）；也可在 `.env` 手动指定 |
| 报「没有可用的收件人」 | 没有任何管理员绑邮箱。表单里的「测试收件邮箱」留空时会自动用发件人地址 |
| 保存后仍是「环境变量生效」 | `mail_smtp_host` 为空 → 表单里 host 必须填才会覆盖 |
| 有记录但用户没收到 | `status=sent` 说明已投给 SMTP，查对方垃圾箱与发件域 SPF |
| 后台看不到记录 | 确认 `email_deliveries` 表已迁移（`./redeploy.sh` 会自动 migrate） |
| 密码提示解不开 | `SECRET_KEY` 变过，后台重填密码 |

## 七之二、为什么macOS上容易踩证书坑

Homebrew 的 Python 里 `ssl.get_default_verify_paths()` 常返回 `cafile=None`（编译时没写死
证书位置），于是 STARTTLS 直接失败：

```
[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate
```

`mailing._ensure_ca_bundle()` 按 `/etc/ssl/cert.pem` → `/etc/ssl/certs/ca-certificates.crt`
→ `/etc/pki/tls/certs/ca-bundle.crt` 的顺序找一个可用的 bundle 回填 `SSL_CERT_FILE`。
Linux 服务器通常自带完整证书，这段不会触发。

手动临时绕过：

```bash
export SSL_CERT_FILE=/etc/ssl/cert.pem
```


## 八、命令行速查

```bash
# 最近 20 条投递
sqlite3 data/homepage.db "select id,category,event,to_email,status,created_at from email_deliveries order by id desc limit 20;"

# 今日按事件统计
sqlite3 data/homepage.db "select event,count(*),sum(status='failed') from email_deliveries where created_at >= datetime('now','start of day') group by event;"

# 清空 SMTP 后台配置（回落到 .env）
sqlite3 data/homepage.db "delete from system_settings where setting_key like 'mail_smtp_%';"
```
