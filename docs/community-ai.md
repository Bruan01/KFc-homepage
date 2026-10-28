# 小 K AI 助手

第一版处理两类明确请求：碎碎念中帖子/评论 @ 当前官方用户名，或回复小 K 已发布的 AI 评论；以及与官方账号的私信（发给小 K 的私信会自动排队回复）。不会主动发帖、参与其他讨论或回复自己的内容。人工使用官方账号发表的评论不会自动接管对话。

## 基础配置

主管理员在 `/admin/users` 的「小 K AI 助手」中单独配置：

- 启用开关（默认关闭）。启用前先在上方选择官方账号。
- API 地址（HTTP/HTTPS，兼容 Chat Completions），API Key、模型名称。
- 角色设定、社区资料与常见问题。

支持根地址（自动补 `/v1`）、含 `/v1` 或代理前缀的地址，以及完整 `/chat/completions` 地址。小 K 的配置、密钥和进程与显影服务池独立，无配置回退或密钥共享。Key 以独立派生密钥的 Fernet 密文保存，依赖 `DJANGO_SECRET_KEY`，更换该值后须重新填写 Key。后台响应只返回 `has_api_key`，留空保留已有密钥，勾选清除后保存可删除密钥。本地无鉴权 API 可不填 Key。

「测试回复」使用当前表单（可以尚未保存），实际调用配置的文本接口，结果只在后台展示，不创建社区内容、任务或通知。请求格式参考 [OpenAI Chat Completions API](https://developers.openai.com/api/reference/resources/chat)，使用 `model`、`messages`、`stream: false`。接口不开放模型工具调用。

没有高级设置。程序固定限制回复至 500 字以内（提示模型尽量 300 字），读取当前公开帖子和最多 10 条回复链上下文；不会读取其他讨论、用户邮箱、后台私密配置或图片字节。原文通过 user 消息传入，与角色及社区资料分开。

## 限额与防刷

后台「回复限额」提供三项设置，均按 0 表示不限制：

- 每位用户每天最多（默认 20 次），按北京时间自然日计算；
- 每天总回复最多（默认 200 次），所有用户合计；
- 同一用户最短间隔（默认 0 秒，即不限制频率）。

超限请求在入队前直接忽略：不回复、不写任务、不产生额外数据库写入，用户端只看到「未收到 AI 回复」的结果。额度统计当天已入队且未被跳过的任务，昨天及更早的任务、因原帖删除/屏蔽/配置变更而跳过的任务都不占用额度。后台配置区显示今天已排队的次数和总限额剩余。

## 回复与任务

发布内容时，在同一事务中写入任务；每个原帖/评论有唯一任务标识，提交失败回滚时不会留下任务。普通 @ 需满足现有关注关系与双向屏蔽规则，明确回复既有 AI 评论可以继续对话。新任务立即返回提交成功提示，后台生成后用官方账号发表评论，并通知提问者，通知定位到具体 AI 回复。评论带「AI 助手」标识。

后台「最近回复记录」显示最近 20 条任务的状态、原始提问、回复和跳转入口；失败任务可手动重试。服务超时/限流等暂时故障最多自动重试一次。请求使用 60 秒超时，日志不保留上游响应正文或可能包含密钥的异常文本。发布前再次检查删除、屏蔽、启用状态、官方身份和配置版本。

多进程通过条件更新领取任务；超时任务用租约回收，旧进程失去领取凭据后不能发布。回复、任务完成和通知在同一数据库事务中提交；稳定发布标识和结果关联避免重复回复。关闭浏览器不影响后台任务。

## 私信回复

用户给官方账号发私信后，`POST /api/messages/<username>` 在消息落库成功后调用 `enqueue_direct_reply`：仅当助手已启用、收件人是当前官方账号、发信人是真实用户且未被双向屏蔽时入队；同一用户最多保留一条待处理私聊任务，响应以 `ai_reply_queued` 告知前端。上下文取该对话最近 10 条消息，官方发出的按 assistant 角色、用户消息按 user 角色传入；私聊场景提示词限定 200 字以内（上限 500 字）。回复以官方账号私信发布（发布标识 `community-ai-<job>`），并发送私信通知；后台记录中 `source=dm`，跳转入口指向对应用户的私信页。人工先用官方账号回复不会取消任务，但发布前会重新校验启用状态、身份、屏蔽与配置版本。

## 部署

先 `manage.py backup_database`，再 `manage.py migrate --noinput`。新增应用 `community_ai` 和 `community_ai.0001_initial`，使用独立的 `community_ai_settings`、`community_ai_reply_jobs` 表。`0002` 允许任务不关联帖子并新增 `source_message`/`result_message` 外键以支持私信回复；`0003` 为设置表增加三个限额字段（每用户每日、每日总计、最短间隔）。

常驻回复进程：

```bash
.venv/bin/python manage.py process_community_ai_jobs --interval 2
# 排空当前可处理队列后退出
.venv/bin/python manage.py process_community_ai_jobs --once
```

`start.sh`、`redeploy.sh`、`scripts/start_windows.ps1` 已包含该独立进程。生产进程管理器也需要托管该命令。后台根据心跳显示回复服务是否在线。Windows 日志在 `data/logs/community-ai.*.log`；Linux 启动脚本和部署脚本各使用其 runtime 日志目录。

接口均仅主管理员可访问，写入校验 CSRF：

- `GET/POST /api/admin/community-ai/settings`
- `POST /api/admin/community-ai/test`
- `GET /api/admin/community-ai/records`
- `POST /api/admin/community-ai/records/<uuid>/retry`

验证：`manage.py test apps.community_ai apps.murmurs apps.accounts apps.notifications`。
