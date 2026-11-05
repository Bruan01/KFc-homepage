# 上线手册 · 照着敲就行

> 目标：把 gunicorn、HTML 边缘缓存、SQLite 调优一次性切上去，全程可回滚。
> 每一步都有「期望看到什么」，对不上就停在那一步，别往下走。
>
> 前置：已经 `git pull` 到包含本次改动的提交。

---

## 阶段 0 · 留退路（5 分钟）

```bash
cd ~/kfc-homepage          # 改成你的项目路径

# 记录当前状态，出问题时知道自己是从哪来的
git rev-parse --short HEAD
pgrep -af "manage.py runserver"
sudo cp /etc/caddy/Caddyfile /etc/caddy/Caddyfile.bak.$(date +%F-%H%M)

# 备份数据库
.venv/bin/python manage.py backup_database
```

**期望**：`pgrep` 打印出一行 runserver 进程；备份命令打印出 `.backup-django-*` 路径。

把这两个值记下来（出问题要用）：

```bash
echo "旧提交: $(git rev-parse --short HEAD)"
ls -t data/homepage.db.backup-django-* | head -1
```

---

## 阶段 1 · 装依赖（不碰线上流量）

```bash
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m gunicorn --version
```

**期望**：打印 `gunicorn (version 24.x)`。

如果报 `No matching distribution found for gunicorn`，说明你的 pip 源里没有它，
换官方源重装（我本机也是这样）：

```bash
.venv/bin/pip install -i https://pypi.org/simple gunicorn
```

**这一步失败就停。** 后面所有步骤都依赖它。

---

## 阶段 2 · 旁路验证（关键，不影响线上）

先确认新代码能在 gunicorn 下跑起来，**用另一个端口，不打断正在服务的 runserver**：

```bash
DEBUG=0 .venv/bin/python -m gunicorn -c deploy/gunicorn.conf.py \
  kflow.wsgi:application --bind 127.0.0.1:9001 --workers 1 --daemon \
  --pid /tmp/gunicorn-test.pid --error-logfile /tmp/gunicorn-test.log

sleep 3
curl -s -o /dev/null -w "健康检查: %{http_code}\n" http://127.0.0.1:9001/api/health
curl -s -o /dev/null -D - http://127.0.0.1:9001/ | grep -iE "cache-control|^vary|set-cookie"
```

**期望**：

```
健康检查: 200
cache-control: public, max-age=30, must-revalidate, s-maxage=300, stale-while-revalidate=600
vary: Accept-Encoding
```

并且**没有** `set-cookie` 那一行。

看完了就关掉：

```bash
kill $(cat /tmp/gunicorn-test.pid)
rm -f /tmp/gunicorn-test.pid
```

如果健康检查不是 200，先看 `/tmp/gunicorn-test.log`，别继续。

---

## 阶段 3 · 改 Caddy（增量改，不要整份覆盖）

**先看你现在的配置**：

```bash
sudo cat /etc/caddy/Caddyfile
```

如果里面除了 `mg.kfc-linlin.top` 还有别的站点（隧道、其他域名），**不要**直接用我的文件覆盖。
只需要做两处增量：

### 3.1 全局块里加 Cloudflare 回源信任

在文件最开头的 `{ ... }` 里加（没有全局块就新建一个放在最上面）：

```
servers {
    trusted_proxies static 173.245.48.0/20 103.21.244.0/22 103.22.200.0/22 103.31.4.0/22 141.101.64.0/18 108.162.192.0/18 190.93.240.0/20 188.114.96.0/20 197.234.240.0/22 198.41.128.0/17 162.158.0.0/15 104.16.0.0/13 104.24.0.0/14 172.64.0.0/13 131.0.72.0/22 2400:cb00::/32 2606:4700::/32 2803:f800::/32 2405:b500::/32 2405:8100::/32 2a06:98c0::/29 2c0f:f248::/32
    client_ip_headers CF-Connecting-IP X-Forwarded-For
}
```

> 这一步只是让日志和限流看到真实访客 IP。**不做也能上线**，做了才能看出真实流量。
> 如果现有配置里已经有 `trusted_proxies`，跳过，别重复写。

### 3.2 站点块确认两件事

```bash
sudo grep -nA 6 "mg.kfc-linlin.top" /etc/caddy/Caddyfile
```

确认 `reverse_proxy` 指向 `127.0.0.1:9000`（和 gunicorn 的默认监听一致）。

然后校验并热加载：

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

**期望**：`Valid configuration`，reload 无输出。

Caddy 这一步**不会**造成停机——它还在往 9000 转发，只是 9000 上还是旧的 runserver。

---

## 阶段 4 · 切主进程（唯一有停机的一步，约 20 秒）

```bash
./redeploy.sh
```

**期望**最后几行类似：

```
[...] Web 服务（旧 runserver）：停止旧进程 12345...
[...] Web 服务：没有旧进程。
[...] 后台启动 Web 服务（gunicorn）：http://127.0.0.1:9000 ...
```

然后确认：

```bash
pgrep -af "[g]unicorn"          # 应该有 4 个进程（1 master + 3 worker）
pgrep -af "manage.py runserver" || echo "runserver 已退出"
ss -lntp | grep 9000            # 应该只有 gunicorn 在监听
```

**期望**：gunicorn 在，runserver 不在，9000 被 gunicorn 占着。

---

## 阶段 5 · 验证（3 条命令）

```bash
# 1. 站点整体
curl -s -o /dev/null -w "%{http_code}\n" https://mg.kfc-linlin.top/

# 2. HTML 头
curl -sI https://mg.kfc-linlin.top/ | grep -iE "cache-control|^vary|cf-cache-status"

# 3. CSRF 接口
curl -sD- -o /dev/null https://mg.kfc-linlin.top/api/csrf | grep -i "set-cookie"
```

**期望**：

- 200
- `cache-control` 里有 `s-maxage=300`，`vary: Accept-Encoding`，`cf-cache-status: DYNAMIC`（此时还没开 CF 缓存，正常）
- `set-cookie: csrftoken=...`

### 到这里必须做一次浏览器实测

打开 `https://mg.kfc-linlin.top/`，然后：

1. **登录**（这验证 `/api/csrf` 下发的 token 能被用上）
2. **发一条碎碎念**（这验证写操作的整个链路）
3. 刷新页面看有没有掉登录

这三步过了，CSRF 的改动就是安全的。**没过就别开 CDN 缓存**，先回滚。

---

## 阶段 6 · 开 Cloudflare 缓存

上面全绿之后再做这一步。

**Cloudflare 后台 → Caching → Cache Rules → Create rule**

表达式（粘进去）：

```
(http.request.method eq "GET"
 and not starts_with(http.request.uri.path, "/api/")
 and not starts_with(http.request.uri.path, "/admin")
 and not starts_with(http.request.uri.path, "/uploads/")
 and not starts_with(http.request.uri.path, "/static/"))
```

动作：

| 设置 | 值 |
|---|---|
| Cache eligibility | Eligible for cache |
| Edge TTL | Use cache-control header if present |
| Browser TTL | Respect origin TTL |

保存 → **Caching → Configuration → Purge Everything**。

验证：

```bash
curl -sI https://mg.kfc-linlin.top/ | grep -i "cf-cache-status"
```

第一次 `MISS`，再请求一次应该是 `HIT`。

---

## 阶段 7 · 收尾

```bash
# 源站压测，和之前的 runserver 数字对比
sudo apt install -y apache2-utils   # 没装过的话
ab -n 500 -c 20 -k http://127.0.0.1:9000/
```

重点看 `Requests per second` 和 `Time per request`。

顺手看一下内存，gunicorn 3 个进程加上后台 worker 别把 2G 吃满：

```bash
free -m
```

---

## 出问题怎么回滚

### 只回退缓存策略（不用改代码，最快）

```bash
echo 'HTML_EDGE_CACHE_SECONDS=0' >> .env
./redeploy.sh
```

HTML 立刻退回 `no-cache`，CF 不再缓存新请求。**先做这个**，再查别的。

### 回退到 runserver（30 秒）

```bash
git stash            # 或 git checkout -- redeploy.sh
git checkout <阶段0记下的旧提交> -- redeploy.sh deploy/
./redeploy.sh
```

### 回退 Caddy

```bash
sudo cp /etc/caddy/Caddyfile.bak.* /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

---

## 三个常见卡点

| 现象 | 原因 | 处理 |
|---|---|---|
| `gunicorn 未能启动` | 9000 被旧 runserver 占着 | `pkill -f "manage.py runserver"` 再跑一次 |
| `pip install` 找不到 gunicorn | pip 源缺包 | 加 `-i https://pypi.org/simple` |
| 部署后样式没更新 | CF 里还是旧 HTML | Purge Everything，浏览器强制刷新 |
| 后台能登录但发帖 403 | `/api/csrf` 没通 | `curl -sD- -o /dev/null https://域名/api/csrf` 看有没有 set-cookie |

## 微信 HTTP 入口与心映登录

生产启用 `SESSION_COOKIE_SECURE=true` 时，`HTTPS_REQUIRED` 默认同时启用。
渲染的网页会在 CSRF 脚本之前检查浏览器地址；HTTP 页面自动切换到同一地址的
HTTPS，保留路径、查询参数和锚点。默认本地配置不跳转；可通过 `HTTPS_REQUIRED`
显式控制。这是网页导航的 JavaScript 兜底，不是 HTTP API 的重定向规则。

Cloudflare 边缘仍应配置 HTTP 到 HTTPS 的跳转（只调整对应站点或确认整个区域都支持
HTTPS 后启用 Always Use HTTPS），这样可以在加载网页之前完成跳转。
发布后清除旧 HTML 的 CDN 缓存，确保微信入口拿到新脚本。
不要通过关闭安全 Cookie 或 CSRF 校验来兼容 HTTP 登录。

心映测评页的 `private, no-store` 不应被公共页面缓存规则覆盖；前端也会检查登录状态，
在会话失效时跳转到带原始路径和参数的登录地址。

同样对后台 HTML 和显影的个性化模板使用 `private, no-store`；显影模板也注入同一套
HTTPS 导航检查。心映报告与账号设置接口返回 401 时会跳转登录，保留当前返回地址。
