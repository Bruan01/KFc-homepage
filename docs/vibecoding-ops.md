# Vibecoding 社区定时任务与外部数据源配置

## 定时任务（服务器部署时执行一次）

在服务器上、项目根目录执行安装脚本（幂等，可重复执行；只写入带 `>>> kflow-vibecoding <<<` 标记的 crontab 块，不影响服务器上其他定时任务）：

```bash
bash scripts/setup_cron.sh            # 安装：每日 04:30 抓取全网榜 + 每小时热度重算
bash scripts/setup_cron.sh --remove   # 移除
```

安装内容：

```cron
# 全网 vibecoding 排行榜每日凌晨抓取
30 4 * * * cd <项目目录> && <venv>/python manage.py crawl_external >> data/logs/cron.log 2>&1
# 站内帖子热度分每小时重算
0 * * * * cd <项目目录> && <venv>/python manage.py refresh_hot_scores >> data/logs/cron.log 2>&1
```

脚本自动检测 `.venv/bin/python`（无则退回系统 python3）；日志写入 `data/logs/cron.log`，部署后用 `tail -f data/logs/cron.log` 确认抓取正常。

也可以手动执行：

```bash
python manage.py refresh_hot_scores              # 全量重算热度
python manage.py crawl_external                  # 抓全部源
python manage.py crawl_external --source github  # 只抓一个源
```

> 注意：`.env` 里的数据源凭据不会随代码同步，部署时需把本机的 `.env` 复制到服务器（至少包含 `PRODUCTHUNT_API_KEY` / `PRODUCTHUNT_API_SECRET`，建议带 `GITHUB_TOKEN`）。

## 外部数据源环境变量（.env）

| 变量 | 必需 | 说明 |
| --- | --- | --- |
| `GITHUB_TOKEN` | 建议 | GitHub Search API 的 token（无 token 时 API 配额极低，抓取自动降级为解析 github.com/trending 页面） |
| `PRODUCTHUNT_API_KEY` + `PRODUCTHUNT_API_SECRET` | PH 榜需要 | Product Hunt 应用凭据（application 页面），爬虫自动走 OAuth client_credentials 换取访问令牌；也可直接配 `PRODUCTHUNT_TOKEN`（Developer Token）二选一 |
| `V2EX_HOT_URL` | 否 | 中文社区热榜 JSON 接口地址，默认已接 V2EX 官方热榜（`https://www.v2ex.com/api/topics/hot.json`），无需配置；服务器访问不了 v2ex 时可换成其他 JSON 源 |

抓取行为约定：

- 每个源独立记录 `crawl_runs` 运行日志（成功/失败/条数），单源失败不影响其他源。
- 抓取失败时保留上次成功数据继续展示；连续失败需检查 `.env` 与网络。
- 仅采集公开元数据（标题/链接/公开计数），请求频率受控，UA 为 `KFlowBot/0.1`。

## 积分与热度参数（后台可调）

- 论坛行为积分规则：管理后台「系统设置」或 `SystemSetting` 表，键前缀 `points.forum.*`（发帖 +10/日限 3、评论 +2/日限 10、被赞 +1/日限 50 等）。
- 加热档位：`forum.boost.<tier>.cost / score / hours`（默认 小火 100 分/+300/24h，中火 300/+1000/48h，大火 1000/+3600/72h）。
- 热度权重：`forum.hot.like_weight / reply_weight / view_weight / gravity`（默认 3 / 5 / 0.2 / 1.2）。
