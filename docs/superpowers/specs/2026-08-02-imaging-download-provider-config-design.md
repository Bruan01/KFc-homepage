# 显影下载与 CPA 配置设计

- 日期：2026-08-02
- 状态：已获用户批准，按方案 A 执行
- 范围：一键下载、管理员生图服务配置

## 1. 目标

为 Django 显影补充可验证的一键下载能力，并允许主管理员在现有后台配置 CPA 生图服务所需参数。

## 2. 设计决策

### 下载

新增当前用户范围内的下载 endpoint。接口复用现有图片归属校验，只允许任务所属用户访问，并返回 `Content-Disposition: attachment`，避免浏览器将图片仅作为预览打开。结果卡片和私有历史记录均指向该 endpoint；图片预览仍使用 inline endpoint。

### Provider 配置

复用现有 `catalog.SystemSetting`，不新增配置表和迁移。配置键为：

- `imaging.cpa.base_url`
- `imaging.cpa.api_key`
- `imaging.cpa.model`
- `imaging.cpa.timeout_seconds`

数据库配置优先于环境变量；未配置时回退 `CPA_BASE_URL`、`CPA_API_KEY` 和本机 CPA 配置文件。API Key 只允许主管理员更新，GET 接口只返回是否已配置和末四位掩码，不返回完整密钥。空的 API Key 默认保留原值，提供显式清除动作。

配置保存与字段校验在事务内完成：Base URL 仅允许 HTTP/HTTPS 且必须有 host；模型非空；超时限制在 30～900 秒。生图服务在任务执行时读取最新配置，因此无需重启应用。

## 3. HTTP 契约

- `GET /api/imaging/generations/<uuid>/download`：当前用户下载自己的已完成图片；
- `GET /api/generations/<uuid>/download`：兼容别名；
- `GET /api/admin/imaging/settings`：主管理员读取脱敏配置；
- `POST /api/admin/imaging/settings`：主管理员更新配置，可传 `clearApiKey: true` 清除密钥。

下载失败使用现有 JSON 错误格式。配置接口不将密钥写入日志、响应或前端源码。

## 4. 前端

管理员后台增加“显影配置”模块，显示 URL、模型、超时、密钥掩码和写入框；显影结果与历史预览均提供下载按钮。保存成功后重新读取脱敏配置。

## 5. 验证

覆盖主管理员权限、普通管理员拒绝、掩码不泄密、配置持久化和环境回退；覆盖用户下载隔离、附件响应头和不存在/未完成任务拒绝。执行完整 Django 测试、迁移检查和 HTTP 冒烟测试。
