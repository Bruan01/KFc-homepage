# 线上性能改造 · 部署说明

> 2026-11-03 · 针对 mg.kfc-linlin.top（2C2G / 美国 / Caddy / Cloudflare）

本次改了四件事：

| # | 改动 | 文件 |
|---|---|---|
| 1 | HTML 允许 CDN 缓存（匿名可复用） | `apps/core/middleware.py`、`kflow/settings.py`、`apps/core/pages.py`、`static/csrf.js`、`apps/core/views.py`、`apps/core/urls.py` |
| 2 | `runserver` → gunicorn 3×4 | `requirements.txt`、`deploy/gunicorn.conf.py`、`redeploy.sh` |
| 3 | SQLite 增加页缓存与临时表配置 | `apps/core/db.py` |
| 4 | Caddy 生产配置 | `deploy/Caddyfile` |

---

## 一、为什么能缓存 HTML

KFlow 的页面 HTML 是**静态壳**：服务端只注入资源指纹和内联脚本，
头像 / 积分 / 未读数都由前端脚本拉接口填充。`apps/core/pages.py` 的
`_html_cache_key` 也证明了这一点——渲染缓存的 key 只跟被引用资源的签名有关，
跟用户无关。

也就是说，同一个 URL 返回的 HTML 对所有访客是**同一份字节**。

那为什么以前 CF 不缓存？两个原因：

1. `Vary: Cookie` —— Django 的 Session/CSRF 中间件自动加的，CF 见到就放弃缓存
2. 每个页面响应都 `Set-Cookie: csrftoken` —— 现在的 `HTMLCacheMiddleware` 遇到带
   `Set-Cookie` 的响应会立刻降级 `private, no-store`，所以必须把 CSRF cookie 从页面响应里拿掉

改动后：

- 页面视图不再带 `@ensure_csrf_cookie`
- 前端第一次写操作前向 `/api/csrf` 领 cookie（`csrf.js` 里做了并发复用和空闲预热）
- `HTMLCacheMiddleware` 把 `Vary` 改回 `Accept-Encoding`，并设置
  `public, max-age=30, s-maxage=300, stale-while-revalidate=600`

**安全边界**：只要响应里出现 `Set-Cookie`（登录、legacy 会话升级），
中间件会把 `Cache-Control` 改成 `private, no-store` 并保留 `Vary: Cookie`。
不会把某人的 cookie 缓存给下一个人。

---

## 二、部署步骤

```bash
cd ~/kfc-homepage        # 你的项目目录

# 1. 装新依赖（gunicorn）
.venv/bin/pip install -r requirements.txt

# 2. 自检
.venv/bin/python manage.py check

# 3. 部署（会自动备份数据库、迁移、重启 worker 与 Web）
./redeploy.sh
```

`redeploy.sh` 现在启动的是：

```
.venv/bin/python -m gunicorn -c deploy/gunicorn.conf.py kflow.wsgi:application
```

默认监听 **127.0.0.1:9000**（只给同机 Caddy 用）。想临时直连调试：

```bash
GUNICORN_BIND=0.0.0.0:9000 ./redeploy.sh
```

### Caddy

```bash
sudo cp /etc/caddy/Caddyfile /etc/caddy/Caddyfile.bak.$(date +%F)
sudo cp deploy/Caddyfile /etc/caddy/Caddyfile
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

**先改这一行**：文件里所有 `/srv/kfc-homepage` 都要换成你服务器的实际项目路径。

---

## 三、Cloudflare 必须配的一条规则

**不做这一步，HTML 仍然不会进缓存**——Cloudflare 默认只缓存静态后缀，
HTML 要靠 Cache Rules 显式允许。

后台 → **Caching → Cache Rules → Create rule**

**When incoming requests match**（表达式模式，直接粘贴）：

```
(http.request.method eq "GET"
 and not starts_with(http.request.uri.path, "/api/")
 and not starts_with(http.request.uri.path, "/admin")
 and not starts_with(http.request.uri.path, "/uploads/")
 and not starts_with(http.request.uri.path, "/static/"))
```

**Then**：

| 设置 | 值 |
|---|---|
| Cache eligibility | **Eligible for cache** |
| Edge TTL | **Use cache-control header if present** |
| Browser TTL | Respect origin TTL |
| Cache key | 默认（含 query string） |

保存后清一次缓存：**Caching → Configuration → Purge Everything**。

> 缓存 key 必须包含 query string（默认行为），否则 `/forum?topic=36` 和
> `/forum?topic=37` 会互相污染。

---

## 四、部署后必须清一次 CDN 缓存

**这一步不是可选的。**

页面 HTML 里的资源地址是 `?v=<内容哈希>`，而真实文件路径不变。如果 CF 里留着一份
部署前的 HTML，访客拿到的就是旧的 `?v=`，而那些 URL 在浏览器里是 **immutable
缓存一年** 的——改完样式后有人会一直看到旧界面，直到他手动清缓存。

所以每次 `./redeploy.sh` 之后：

**Cloudflare → Caching → Configuration → Purge Everything**

嫌手点麻烦的话，可以在 `redeploy.sh` 末尾加一段调 CF API 的 curl：

```bash
curl -s -X POST "https://api.cloudflare.com/client/v4/zones/$CF_ZONE_ID/purge_cache" \
  -H "Authorization: Bearer $CF_API_TOKEN" \
  -H "Content-Type: application/json" \
  --data '{"purge_everything":true}'
```

（需要 `Zone.Cache Purge` 权限的 API Token。部署频繁的话值得配。）

---

## 五、验证

### 1. gunicorn 起来了

```bash
pgrep -af gunicorn
ss -lntp | grep 9000        # 应该只监听 127.0.0.1
curl -s http://127.0.0.1:9000/api/health
```

### 2. HTML 头变了

```bash
curl -sI https://mg.kfc-linlin.top/ | grep -iE "cache-control|^vary|cf-cache-status"
```

期望：

```
cache-control: public, max-age=30, must-revalidate, s-maxage=300, stale-while-revalidate=600
vary: Accept-Encoding
cf-cache-status: MISS      ← 第一次
```

再请求一次，应该变成 `HIT`。

如果还是 `DYNAMIC` / `vary` 里有 `Cookie`，说明要么 Cache Rule 没生效，
要么 Caddy 还没加载新配置。

### 3. CSRF 还能用

```bash
curl -sD- -o /dev/null https://mg.kfc-linlin.top/api/csrf | grep -iE "set-cookie|cache-control"
```

应该有 `set-cookie: csrftoken=...` 和 `cache-control: private, no-store`。

然后去浏览器里试一次登录、发一条碎碎念——这是唯一能证明 `csrf.js` 改动没问题的测试。

### 4. 源站真实性能（这才是有意义的压测）

```bash
sudo apt install -y apache2-utils
ab -n 500 -c 20 -k http://127.0.0.1:9000/
```

对比一下之前的 runserver 数字。重点看 `Requests per second` 和 `Time per request`。

---

## 六、回滚

只回滚缓存策略（不用改代码）：

```bash
echo 'HTML_EDGE_CACHE_SECONDS=0' >> .env
./redeploy.sh
```

`0` 会让 HTML 退回 `no-cache`，CF 立刻不再缓存新请求。

完整回滚：`git revert` 本次提交后 `./redeploy.sh`。

---

## 七、为什么 cache_size 是 16MB 而不是 64MB

你原本想要 64MB。这是个**每连接上限**，不是全局值：

- gunicorn 3 worker × 4 thread = 峰值 12 条连接
- 64MB × 12 = 最坏 768MB
- 这台机器只有 2G，上面还跑着显影、心映、小 K 三个后台 worker

而且库本身只有几十 MB，16MB 足够装下一次请求的工作集。
真要调：`SQLITE_CACHE_MB=32` 写进 `.env` 重启即可（上限 64）。

另外注意：`cache_size` 是「上限」不是「预分配」，SQLite 按命中页惰性占用，
所以设大了通常也不会真吃到那么多——但 2G 的机器不值得赌这个。

---

## 八、下一步（按收益排序）

1. **搬机房**（如果用户主要在中国）：香港 / 日本，跨国 RTT 从 500ms+ 降到 50ms 内。
   这一步的收益超过本次所有改动之和。
2. **静态资源直出**：解开 `deploy/Caddyfile` 里那段注释，19 个 CSS/JS 不再进 gunicorn。
3. **图片走 CF Images 或 R2**：`/uploads/` 现在是 Django 在发。
4. **Redis**：等 gunicorn 多进程稳定运行、确实需要跨进程共享会话/限流时再上。
   现在上的收益不到 2ms/请求。
