# KFlow Homepage TODO

按 ROI 排序。每项都是"改哪儿 / 改成什么 / 完成标准"三段式。

---

## P0 — 立即（本周）

### 1. 下载改为流式 + 支持 Range
- 位置：`app/handlers/download.py:161-169`
- 现状：`f.read()` 一次性把整个文件读进内存后 `wfile.write(blob)`，500MB 包并发几个就 OOM。
- 做法：参考 `app/handlers/base.py:serve_material_file` 的分块 + Range 实现，复用 `STREAM_CHUNK_SIZE`。
- 完成标准：单次下载常驻内存 ≤ 一个 chunk；断网续传能从 Range 起点继续。

### 2. `/api/user/me` 去掉写事务
- 位置：`app/handlers/auth_user.py:451-466`（`_award_daily_for_session`）
- 现状：读接口每次调用都 `BEGIN IMMEDIATE`，前端轮询→写锁竞争。
- 做法：日活奖励只在登录成功时（`_start_user_session`）触发一次，或用 `INSERT OR IGNORE` 无锁路径。
- 完成标准：`/api/user/me` 只做 SELECT。

### 3. DB 连接生命周期修正
- 位置：`app/db/__init__.py:16-95` + 所有 `finally: conn.close()` 的 handler
- 现状：`_ReusableConnection` 号称线程缓存，但每个 handler 都 `conn.close()` 把它关掉，缓存作废；`finish()` 里的 `release_db()` 又重复一遍。
- 做法：二选一 — (a) 删掉线程缓存，`get_db()` 每次新建；(b) 保留缓存，handler 不再 `close()`，统一由 `finish()` 释放。
- 完成标准：一个请求内多次 `get_db()` 拿到同一连接；请求结束保证连接归还。

### 4. 静态资源加 ETag / 304
- 位置：`app/handlers/base.py:serve_static`
- 现状：只发 `Cache-Control: max-age`，文件更新后浏览器不会重新拉；反过来每次都全量传输。
- 做法：用 `mtime + size` 生成弱 ETag，命中 `If-None-Match` 返回 304。
- 完成标准：curl `-H "If-None-Match: ..."` 二次请求返回 304，Content-Length 为 0。

### 5. Dashboard 分表懒加载
- 位置：`app/handlers/base.py:707-829`（`dashboard_get`）
- 现状：一次拉回 ~27 张表全部行，还带 `GROUP BY status` 的额外扫表。
- 做法：`/api/admin/dashboard` 只返回统计计数；行数据挪到 `/api/admin/dashboard/tables/:name?limit=&offset=` 分页拉。
- 完成标准：dashboard 首屏 payload ≤ 50KB。

### 6. 验证码接口 IP 限速
- 位置：`app/handlers/auth_user.py:handle_user_verification_code`
- 现状：只按邮箱做 60 秒冷却，同 IP 可以对任意邮箱发；SMTP 反射风险。
- 做法：加 IP 维度滑窗（内存字典或复用 `email_verification_codes` 表）；每 IP 每小时上限（如 20）。
- 完成标准：脚本用同 IP 打不同邮箱能被 429 拦。

### 7. 关键表加索引
- 位置：`app/db/schema.py`
- 目标索引：
  - `downloads(user_id, product_id)`
  - `download_requests(product_id, user_id, status)`
  - `email_verification_codes(email, purpose, expires_at)`
  - `products(status, published_at)`
- 完成标准：`EXPLAIN QUERY PLAN` 上述 SELECT 都是 SEARCH ... USING INDEX。

### 8. 分片上传的累计大小与哈希对账
- 位置：`app/handlers/chunk_uploads.py`
- 现状：`create` 时按声明 size 算 chunk 数，但 chunk 阶段没检查累计写入是否超过声明；`complete` 时不核对客户端预期 SHA256。
- 做法：session 里维护 `written_bytes`，每 chunk 累加校验；`complete` 请求带 `expected_sha256` 并对账。
- 完成标准：伪造 size 或篡改 chunk 都会被 4xx 拒。

### 9. 删掉根目录 `server.py` 死代码
- 位置：`/server.py`（315KB）
- 现状：入口已改为 `app.server:run_server`，根文件只是 shim + 一堆遗留代码。
- 做法：把根 `server.py` 精简到只 import 并调用 `app.server.run_server`（≤ 5 行），或直接删除，让入口只保留 `python -m app`。
- 完成标准：`git grep` 找不到根 `server.py` 的实体实现。

---

## P1 — 近期（两到四周）

### 10. Session 外置
- 现状：`SESSIONS` 是 `app/config.py:108` 的内存 dict，重启即失效，也无法多进程。
- 做法：新建 `sessions` 表（token / role / user_id / exp / created_ip / last_seen_ip），或接 Redis。
- 迁移点：`_start_user_session`、`_start_admin_only_session`、`get_session`、`get_user_session`、`handle_user_logout`。
- 完成标准：重启进程后已登录用户不掉线。

### 11. 路由重写（去掉 if 链 + 字符串反射）
- 位置：`app/handlers/base.py:78-274`
- 做法：写 50 行左右的装饰器路由表：
  ```python
  @route("GET", r"^/api/products/(?P<slug>[^/]+)$")
  def public_product_detail(handler, slug): ...
  ```
  在模块导入时注册，`do_*` 只做 dispatch。
- 完成标准：IDE 能从 URL 跳到处理函数；路径改动只需改一处。

### 12. 拆解 `AppHandler` 上帝对象
- 位置：`app/handlers/base.py`（1323 行）
- 做法：把 Dashboard、Agnes 视频/聊天、产品序列化 helper 分别挪到 `services/` 或独立 mixin；`AppHandler` 只保留 HTTP I/O + 会话 + 路由分派。
- 完成标准：`base.py` ≤ 400 行。

### 13. 迁移框架
- 位置：`app/db/schema.py:483` 的 `init_db`
- 现状：新增列靠 hardcode dict + `ALTER TABLE`，无版本号无法回滚。
- 做法：`schema_migrations` 表 + `migrations/NNNN_description.sql` 顺序执行；启动时应用未执行项。
- 完成标准：新环境和旧环境跑起来 schema 一致，可查已执行版本。

### 14. 结构化日志
- 现状：全 `print`，无 level、无请求 ID。
- 做法：`logging` + JSON formatter；在 `BaseHTTPRequestHandler.log_request` 打请求 ID，handler 里 `logger.info/warn`。
- 完成标准：能按 request_id / user / route 过滤。

### 15. 产品包冗余合并
- 位置：`app/db/schema.py` 中 `products.file_*` 与 `product_packages`
- 现状：两份数据源、`_migrate_product_packages` 一次性搬运；写入路径分散。
- 做法：`products.file_*` 改成计算属性（VIEW 或读时聚合），单一真相来源为 `product_packages` + `product_versions`。
- 完成标准：产品详情、下载、上传只操作 `product_packages`；`products` 上无冗余文件字段。

### 16. 存储抽象层
- 做法：新建 `app/services/storage.py`：`save_stream / open_stream / delete / stat`，先做本地实现，为后续接 S3/OSS/CDN 做接口。
- 完成标准：`chunk_uploads`、`download`、`admin_products` 都通过 storage 接口访问文件。

### 17. 超级管理员账号统一化
- 位置：`app/config.py:56-57`、`_find_admin_credentials`
- 现状：`ADMIN_USERNAME/PASSWORD` env 硬编码走单独分支，与 `admin_accounts` 表逻辑不一致。
- 做法：首次启动时把它作为 seed 写入 `admin_accounts`（`is_super=1, admin_level=3`）；`_find_admin_credentials` 只查表。
- 完成标准：无 env 分支残留；密码只以 hash 存在。

### 18. CSRF 起码校验
- 做法：所有非 GET 请求校验 `Origin` 或 `Referer` 属于本站 host，不符合即 403。
- 完成标准：跨站页面用 fetch 打 `/api/admin/products` 会被拒。

---

## P2 — 中期（一到两月）

### 19. 前端拆分与构建
- 位置：`static/admin.html`（88KB）、`chat-home.js`（68KB）、`styles.css`（52KB）
- 做法：接入 esbuild/vite，产出带内容 hash 的产物；HTML 保持无逻辑；后端加 `Cache-Control: immutable`。
- 完成标准：改一个 tab 只重下相关 chunk；打开首页首屏 JS ≤ 100KB gzip。

### 20. 切换到 ASGI / gunicorn
- 现状：`ThreadingHTTPServer` 是 stdlib 玩具级实现，每请求一线程，无限流/无优雅关闭。
- 做法：迁到 FastAPI/Starlette + uvicorn（或 Flask + gunicorn+gevent），保留同一路由约定。
- 完成标准：`SIGTERM` 能优雅关闭；SSE 与大文件下载并发下不再拖住主进程。

### 21. 测试脱离 gitignore + CI
- 位置：`.gitignore` 里的 `tests/`
- 做法：`tests/` 出 gitignore；新增审批流、权限边界（TODO 原 P2）、上传下载权限的 pytest；GitHub Actions 跑 lint + pytest。
- 完成标准：主分支保护，PR 必须 CI 通过。

### 22. 操作审计日志
- 做法：`audit_log(id, actor, ip, action, target_type, target_id, result, request_id, created_at)`；关键动作（登录、上传、发布、审批、删除、升级）落表；dashboard 加筛选检索。
- 完成标准：能查"某个包被谁在何时上传/删除"。

### 23. 发布审批明细页
- TODO 原 P0 项；`publish_request_votes` 表已存在但无明细 UI。
- 做法：`/api/admin/publish-requests/:id` 返回投票明细，前端在后台加只读归档视图。
- 完成标准：审批结束的申请仍可查完整投票记录。

---

## P3 — 长期（结构性演进）

### 24. 对象存储 + 签名 URL 下载
- 依赖：#16 存储抽象层落地。
- 做法：本地 → S3/OSS；下载走签名 URL + 时效控制 + 防盗链。

### 25. Postgres 替换 SQLite
- 触发条件：写并发或多实例上来后。
- 做法：DAO 层抽象出来（可基于 SQLAlchemy Core），Postgres 化只改 driver + schema 语法差异。

### 26. 容器化 + Nginx 反代 + 进程管理
- 做法：Dockerfile + docker-compose；Nginx 处理静态与 TLS，应用只跑业务。

---

## 完成后建议的执行顺序

先做 P0 的 #1 #2 #3 —— 这三条把最容易被生产击穿的洞先堵上，代价都是几十行改动。之后按数字顺序推。
