# 账号找回：换绑邮箱与忘记密码

两个入口都建立在同一套验证码机制上（`email_verification_codes` + `EMAIL_CODE_*` 限流）。

## 一、换绑邮箱

**入口**：`/account/settings` → 账号与安全 → 登录邮箱 → 「更换邮箱」

**接口**：`POST /api/user/email/bind`

```json
{ "email": "new@example.com", "code": "123456", "currentPassword": "……" }
```

**流程**：当前密码校验 → 新邮箱验证码校验 → 写 `users.email` + `email_verified_at`。

**约束**：

| 情况 | 结果 |
|---|---|
| 新邮箱与当前邮箱相同 | 409 |
| 新邮箱已被他人验证 | 409 |
| 当前密码错误 | 401 |
| 验证码错误 / 过期 / 超次数 | 400 |
| 首次绑定（原本没邮箱） | 200，`rebound: false` |
| 换绑（原本有邮箱） | 200，`rebound: true` |

**两个容易踩的点**：

1. **换绑后必须保持登录态**。历史实现里有一行 `user.set_password(currentPassword)`，即使密码相同，
   重新哈希也会改变 `get_session_auth_hash()`，Django 下次请求就判定会话失效——表现为「换完邮箱立刻掉登录」。
   现在只更新 `email` 与 `email_verified_at` 两个字段。legacy 明文密码的升级由 `verify_user_password()` 负责，不需要在这里重设。
2. **旧邮箱会收到一封变更通知**（`mailing.notify_email_changed`，异步）。
   这不是礼貌，是防线：账号被盗后攻击者可以换绑邮箱，再走「邮箱验证码登录」把原主人彻底锁在门外。
   通知里带新邮箱和时间，原主人至少能在旧邮箱里看到异动。

## 二、忘记密码

**入口**：`/login` → 登录按钮下方「忘记密码？用邮箱验证码重置」

**接口**：

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/api/user/verification-code` | 发码，`purpose` 传 `reset` |
| POST | `/api/user/password/reset` | 校验并重置 |

```json
{ "email": "…", "code": "123456", "newPassword": "…", "confirmPassword": "…" }
```

**安全设计**：

- **不泄露邮箱是否注册**：`purpose=reset` 对未注册邮箱**静默返回成功但不发信**；
  接口层对查不到的账号也回同一个「invalid or expired verification code」，和验证码错误无法区分。
- **只发往已绑定邮箱**：`users.email_verified_at` 为空的账号收不到码，走不通这条路。
- **验证码单次使用**：消费后立即标记 `used_at`，重复提交返回 400。
- **重置后清空所有旧会话**：`services.revoke_other_sessions()` 扫 `django_session` 与 `legacy_sessions`，
  把该账号在其它设备上的登录态全部删除。当前请求本身也会失效（不自动登录），
  用户必须用新密码重新登一次——这既是安全要求，也能帮他确认记住了新密码。
- **管理员密码同步**：账号若同时有 `admin_accounts` 记录，`password_hash` 一并更新，避免两套密码不一致。
- **限流**：沿用邮箱维度（每小时 5 次）与 IP 维度（每小时 20 次）。

**成功后**会向该邮箱发一封安全通知（`mailing.notify_password_reset`），内容是时间 + 来源提示。

## 三、相关邮件

两类通知都走 `mail_templates.render_security_notice()`，黑色主题、table 布局、内联样式。
投递记录里 `category="security"`，`event` 分别是 `email_changed` / `password_reset`，
可在后台「系统邮箱设置 → 投递记录」里按事件筛选。

## 四、测试

`apps/accounts/test_account_recovery.py`，18 个用例：

- 换绑成功 / 同邮箱拒绝 / 他人邮箱拒绝 / 密码错误拒绝 / 首次绑定标记 / **换绑后会话保持** / 旧邮箱收到通知
- 重置成功 / 验证码错误 / 未知邮箱不泄露 / 短密码 / 两次不一致 / 验证码单次使用
- `reset` 用途对未知邮箱静默、`reset` 会写入 pbkdf2 哈希
