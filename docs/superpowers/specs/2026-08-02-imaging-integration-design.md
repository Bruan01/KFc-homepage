# “显影” Django 整合设计

- 日期：2026-08-02
- 状态：按用户授权的推荐方案执行
- 方案：统一迁入 Django `apps/imaging`

## 1. 目标与边界

将 `kflow/gpt-image-web` 的图片生成能力整合进 KFlow 当前 Django 主页：

1. 主页提供名为“显影”的入口；
2. 显影页面和接口使用现有 Django Session 用户；
3. 任务、历史图片和状态始终按用户隔离；
4. 每次生成在事务中扣除可配置积分，失败自动退款；
5. 任务、账本、文件和哈希均有可验证的持久化记录；
6. 删除旧 FastAPI 的共享 `history.json`、进程内任务字典和独立运行入口。

不引入 DRF、Redis 或 Celery；继续使用现有单机 Django 部署和本机 CPA 服务。生成执行采用 Django 数据库任务记录加后台线程，另提供管理命令用于补偿 queued/stale 任务，避免数据库记录与执行状态脱节。

## 2. 方案比较

### A：统一迁入 Django（采用）

新增 `apps/imaging`，复用 Django 用户、Session、CSRF、ORM 和 points service。页面由 Django 模板提供，图片通过校验归属的 Django endpoint 输出。

优点是用户隔离与扣费位于同一数据库事务，查询边界清晰，最终只有一个 Web 框架；代价是需要把旧 FastAPI 的 HTTP 客户端和前端适配为 Django 组件。

### B：保留 FastAPI，由 Django 代理

需要跨服务传递用户身份、签名请求、同步积分和处理两套任务状态。代理失败与扣费回滚复杂，不符合彻底迁入目标。

### C：主页 iframe/外链到独立服务

实现成本最低，但共享历史、独立认证和积分扣费问题仍然存在，直接排除。

## 3. 数据与业务流

`ImageGenerationJob` 使用 UUID 主键，保存用户、提示词、尺寸、质量、格式、状态、费用快照、幂等键、错误、时间、图片文件和 SHA-256。图片存储路径包含用户 ID，读取必须通过 owner filter 的接口，不暴露共享静态目录。

创建任务的事务步骤：

1. 校验请求字段并生成/读取用户范围内幂等键；
2. 锁定用户积分账户；
3. 写入负向 `PointLedger`，余额不足则整体回滚；
4. 写入 queued 任务并记录费用快照；
5. 事务提交后启动执行器。

生成成功后保存文件、哈希和完成状态；任何 provider、网络、文件或未预期异常均将任务置为 failed，并用独立幂等键写入正向退款账本。历史只读取当前用户的 completed 任务，最多返回最近 12 条。

## 4. HTTP 契约

- `GET /imaging`：登录用户的显影页面，未登录跳转 `/login?next=/imaging`；
- `POST /api/imaging/generations`：创建任务，返回 202；
- `GET /api/imaging/generations/<uuid>`：读取当前用户任务；
- `GET /api/imaging/history`：读取当前用户历史；
- `GET /api/imaging/generations/<uuid>/image`：只允许任务所属用户读取图片；
- `/api/generations`、`/api/history` 保留为兼容别名，但同样要求登录和用户过滤。

API 错误使用现有 `{error: ...}` 格式。前端展示当前积分余额和单次费用，并通过 polling 获取状态。

## 5. 外部服务与配置

Django imaging service 调用 `CPA_BASE_URL` 的 `/images/generations`，使用 `CPA_API_KEY`，支持现有尺寸、质量和 png/jpeg/webp。为避免泄漏密钥，不写入日志、不写入数据库。图片服务失败不影响任务记录和退款闭环。

积分成本加入现有 `SystemSetting` 规则，默认 10，可由管理员规则接口配置为非负整数；任务保存创建时的费用快照，后续规则变化不影响已扣任务。

## 6. 验证

测试覆盖：迁移、登录保护、用户 A/B 历史隔离、积分扣除及余额不足、幂等创建、成功文件落盘与哈希、失败退款、图片归属保护、主页入口和旧 FastAPI 代码清理。执行 `manage.py check`、`migrate --check`、完整 Django tests、数据库审计和 HTTP 冒烟测试。
