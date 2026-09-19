# pyright: reportMissingImports=false
"""External rankings analysis: summaries, tags, design-analysis, trends, prediction.

双通道：
- LLM 通道：CPA（OpenAI-compatible）可用时用大模型做概括/标签/剖析，质量最高；
- 规则通道：无 LLM 配置或调用失败时，用关键词词典 + 描述抽取兜底，保证永远有内容。

趋势与预测基于 ExternalMetricLog 历史：速度（日增量）→ 状态（爆发/上升/平稳/降温）
→ 线性外推 7 天预测。
"""
from __future__ import annotations

import json
import os
import re
from datetime import timedelta
from urllib.request import Request, urlopen

from django.utils import timezone as dj_timezone

from apps.rankings.services import USER_AGENT, _open_with_tls_fallback

from .models import ExternalMetricLog, ExternalProject

REQUEST_TIMEOUT = 25
ANALYZE_PER_SOURCE = 10
ANALYZE_MAX_AGE_HOURS = 24

# 关键词 → 标签（规则通道）
TAG_KEYWORDS: list[tuple[str, list[str]]] = [
    ("AI", ["ai", "gpt", "llm", "claude", "gemini", "openai", "anthropic", "大模型"]),
    ("Agent", ["agent", "agentic", "autonomous"]),
    ("MCP", ["mcp", "model context protocol"]),
    ("RAG", ["rag", "retrieval", "embedding", "向量"]),
    ("CLI", ["cli", "terminal", "command line", "shell", "tui"]),
    ("Web 应用", ["web", "fullstack", "nextjs", "react", "vue", "frontend", "dashboard", "saas"]),
    ("浏览器插件", ["chrome", "extension", "browser extension", "plugin"]),
    ("游戏", ["game", "gaming", "游戏", "roguelike"]),
    ("机器人", ["bot", "discord", "telegram", "qq"]),
    ("数据", ["database", "sql", "postgres", "sqlite", "duckdb", "数据"]),
    ("自托管", ["self-hosted", "docker", "k8s", "kubernetes", "homelab"]),
    ("设计", ["design", "ui", "ux", "figma"]),
    ("开发效率", ["productivity", "workflow", "devtools", "效率", "开发"]),
    ("爬虫", ["scraper", "crawler", "spider"]),
]

SOURCE_LABEL = {"kaiyuanbang": "开源榜"}


def _primary_metric(metrics: dict) -> int:
    for key in ("stars", "upvotes", "replies"):
        if metrics.get(key) is not None:
            return int(metrics[key])
    return 0


def _rule_summary(project: ExternalProject, metrics: dict) -> str:
    desc = (project.description or "").strip()
    metric = _primary_metric(metrics)
    source = SOURCE_LABEL.get(project.source, project.source)
    if desc:
        cut = desc[:70].rstrip()
        head = cut if len(desc) <= 70 else cut + "…"
        return f"{source} 热门项目：{head}（当前热度值 {metric:,}）"
    return f"来自 {source} 的热门 vibecoding 项目（当前热度值 {metric:,}）。"


def _rule_tags(project: ExternalProject) -> list[str]:
    haystack = f"{project.title} {project.description} {project.language}".lower()
    tags: list[str] = []
    for tag, keywords in TAG_KEYWORDS:
        if any(k in haystack for k in keywords):
            tags.append(tag)
        if len(tags) >= 4:
            break
    if project.language and len(tags) < 4:
        tags.append(project.language)
    if not tags:
        tags.append("Vibecoding")
    return tags


def _rule_analysis(project: ExternalProject, tags: list[str], metrics: dict) -> dict:
    tag_set = set(tags)
    positioning = "面向开发者的效率工具，围绕 AI 辅助开发流程提供价值。"
    audience = "使用 AI 编程工具的开发者与技术爱好者。"
    mechanics = "以开源形式快速迭代，通过社区传播获得早期用户。"
    if "Agent" in tag_set or "AI" in tag_set:
        positioning = "把大模型能力封装为可自主执行任务的产品，减少人工重复操作。"
        audience = "希望用 Agent 自动化日常工作流的开发者与效率人群。"
        mechanics = "提示词编排 + 工具调用，以自动化完成度作为核心体验。"
    elif "CLI" in tag_set:
        positioning = "命令行优先的工具设计，把复杂能力压缩进终端工作流。"
        audience = "重度终端用户与追求脚本化、可组合工作流的工程师。"
        mechanics = "轻量安装、可管道组合、易接入 CI 与脚本。"
    elif "Web 应用" in tag_set:
        positioning = "开箱即用的 Web 应用，把某个具体场景做到极简。"
        audience = "非技术背景的个人用户与小型团队。"
        mechanics = "托管部署 + 免配置上手，用低门槛换取传播。"
    elif "游戏" in tag_set:
        positioning = "轻量趣味小游戏，验证一句话生成完整玩法的产品路径。"
        audience = "想快速体验 AI 生成成果的泛用户。"
        mechanics = "单文件/即开即玩，依赖社交传播带来裂变。"
    takeaway = (
        f"可借鉴其「{tags[0] if tags else 'Vibecoding'}」场景的切入方式："
        "从一个小而具体的痛点出发，用 AI 压低实现成本，先做出可体验的最小产品再迭代。"
    )
    metric = _primary_metric(metrics)
    if metric >= 10000:
        takeaway = f"热度已达 {metric:,}，验证了该方向的强需求；可研究其冷启动与传播路径。"
    return {
        "positioning": positioning,
        "audience": audience,
        "mechanics": mechanics,
        "takeaway": takeaway,
    }


# ── LLM 通道 ────────────────────────────────────────────────────────────────


def _llm_available() -> bool:
    return bool(os.getenv("CPA_API_KEY", "").strip()) and bool(os.getenv("CPA_BASE_URL", "").strip())


def _llm_chat(system: str, user: str) -> str | None:
    base = os.getenv("CPA_BASE_URL", "").strip().rstrip("/")
    key = os.getenv("CPA_API_KEY", "").strip()
    model = os.getenv("CPA_CHAT_MODEL", "gpt-4o-mini").strip()
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.3,
        "max_tokens": 600,
    }).encode()
    request = Request(
        f"{base}/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with _open_with_tls_fallback(request, REQUEST_TIMEOUT) as response:
            data = json.loads(response.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]
    except Exception:
        return None


def _llm_analysis(project: ExternalProject, metrics: dict) -> dict | None:
    """Ask the LLM for summary/tags/design-analysis as strict JSON; None on failure."""
    metric = _primary_metric(metrics)
    system = (
        "你是 vibecoding 社区的分析师。只输出 JSON，不要 markdown 代码块。"
        '字段：summary（不超过60字的中文概括）、tags（3-4个中文标签，从{"AI","Agent","MCP","RAG","CLI",'
        '"Web 应用","浏览器插件","游戏","机器人","数据","自托管","设计","开发效率","开源"}中选）、'
        "positioning（产品定位，一句话）、audience（目标用户，一句话）、"
        "mechanics（核心机制，一句话）、takeaway（对社区用户的可借鉴点，一句话）。"
    )
    user = (
        f"项目：{project.title}\n来源：{SOURCE_LABEL.get(project.source, project.source)}\n"
        f"热度指标：{metric}\n语言：{project.language or '未知'}\n"
        f"描述：{(project.description or '无')[:400]}"
    )
    raw = _llm_chat(system, user)
    if not raw:
        return None
    match = re.search(r"\{.*\}", raw, re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
        tags = [str(t)[:12] for t in data.get("tags", [])][:4]
        if not data.get("summary") or not tags:
            return None
        return {
            "summary": str(data["summary"])[:120],
            "tags": tags,
            "analysis": {
                "positioning": str(data.get("positioning", ""))[:160],
                "audience": str(data.get("audience", ""))[:160],
                "mechanics": str(data.get("mechanics", ""))[:160],
                "takeaway": str(data.get("takeaway", ""))[:200],
            },
        }
    except (ValueError, TypeError, KeyError):
        return None


# ── 分析入口 ────────────────────────────────────────────────────────────────


def analyze_project(project: ExternalProject, *, force: bool = False) -> bool:
    try:
        metrics = json.loads(project.metrics) if project.metrics else {}
    except (ValueError, TypeError):
        metrics = {}
    if not force and project.analyzed_at:
        age = (dj_timezone.now() - project.analyzed_at).total_seconds() / 3600
        if age < ANALYZE_MAX_AGE_HOURS:
            return False

    result = None
    used_source = ""
    if _llm_available():
        result = _llm_analysis(project, metrics)
        used_source = "llm"
    if result is None:
        tags = _rule_tags(project)
        result = {
            "summary": _rule_summary(project, metrics),
            "tags": tags,
            "analysis": _rule_analysis(project, tags, metrics),
        }
        used_source = "rule"

    project.summary = result["summary"]
    project.tags = json.dumps(result["tags"], ensure_ascii=False)
    project.analysis = json.dumps(result["analysis"], ensure_ascii=False)
    project.analysis_source = used_source
    project.analyzed_at = dj_timezone.now()
    project.save(update_fields=["summary", "tags", "analysis", "analysis_source", "analyzed_at"])
    return True


def analyze_top_projects(*, force: bool = False, per_source: int = ANALYZE_PER_SOURCE) -> int:
    """Analyze the top-N hottest projects per source (default 10)."""
    analyzed = 0
    for source in (ExternalProject.SOURCE_GITHUB, ExternalProject.SOURCE_PRODUCTHUNT, ExternalProject.SOURCE_CN_COMMUNITY):
        top = (
            ExternalProject.objects.filter(is_active=True, source=source)
            .order_by("-heat_score")[:per_source]
        )
        for project in top:
            try:
                if analyze_project(project, force=force):
                    analyzed += 1
            except Exception:
                continue
    return analyzed


def snapshot_metrics() -> int:
    """Append one metric log per active project (called after each crawl)."""
    now = dj_timezone.now()
    count = 0
    for project in ExternalProject.objects.filter(is_active=True).iterator():
        try:
            metrics = json.loads(project.metrics) if project.metrics else {}
        except (ValueError, TypeError):
            metrics = {}
        ExternalMetricLog.objects.create(
            project=project,
            captured_at=now,
            heat=project.heat_score,
            stars=int(metrics.get("stars", 0) or 0),
            forks=int(metrics.get("forks", 0) or 0),
            upvotes=int(metrics.get("upvotes", 0) or 0),
            replies=int(metrics.get("replies", 0) or 0),
        )
        count += 1
    # 控制表体积：每项目只保留最近 60 条
    for project_id in ExternalMetricLog.objects.values_list("project_id", flat=True).distinct():
        logs = ExternalMetricLog.objects.filter(project_id=project_id).order_by("-captured_at")
        stale_ids = list(logs.values_list("id", flat=True)[60:])
        if stale_ids:
            ExternalMetricLog.objects.filter(id__in=stale_ids).delete()
    return count


# ── 趋势与预测 ──────────────────────────────────────────────────────────────


def _trend_state(velocity_per_day: float, base: float) -> str:
    if base <= 0:
        return "fresh"
    ratio = velocity_per_day / base
    if ratio >= 0.2:
        return "hot"      # 爆发
    if ratio >= 0.05:
        return "rising"   # 上升
    if ratio >= -0.02:
        return "steady"   # 平稳
    return "cooling"


TREND_LABEL = {"hot": "爆发", "rising": "上升", "steady": "平稳", "cooling": "降温", "fresh": "新上榜", "": ""}


def project_trend(project: ExternalProject) -> dict:
    """Velocity + 7-day prediction from metric logs (needs >= 2 snapshots)."""
    logs = list(project.metric_logs.order_by("captured_at"))
    if len(logs) < 2:
        return {"state": "fresh", "stateLabel": TREND_LABEL["fresh"], "velocityPerDay": 0, "predicted": None, "points": []}
    first, last = logs[0], logs[-1]
    days = max(0.5, (last.captured_at - first.captured_at).total_seconds() / 86400)
    key = lambda log: log.stars or log.upvotes or log.replies or 0  # noqa: E731
    base_value = key(first)
    last_value = key(last)
    velocity = (last_value - base_value) / days
    predicted = max(0, round(last_value + velocity * 7))
    state = _trend_state(velocity, max(1, last_value))
    points = [
        {"t": log.captured_at.isoformat(), "v": key(log)}
        for log in logs[-14:]
    ]
    return {
        "state": state,
        "stateLabel": TREND_LABEL.get(state, state),
        "velocityPerDay": round(velocity, 1),
        "predicted": predicted,
        "points": points,
    }


def tag_trends(days: int = 7, top: int = 8) -> dict:
    """Tag-level hot trends: 近 N 天热度增量排行 + 简单线性预测。"""
    since = dj_timezone.now() - timedelta(days=days)
    result = []
    projects = ExternalProject.objects.filter(is_active=True).exclude(tags="").only(
        "id", "tags", "heat_score"
    )
    for project in projects:
        try:
            tags = json.loads(project.tags)
        except (ValueError, TypeError):
            continue
        logs = list(ExternalMetricLog.objects.filter(project=project, captured_at__lte=timezone_ceiling()).order_by("captured_at"))
        if not logs:
            continue
        last = logs[-1]
        past = next((log for log in logs if log.captured_at >= since), logs[0])
        now_value = last.stars or last.upvotes or last.replies or 0
        past_value = past.stars or past.upvotes or past.replies or 0
        delta = now_value - past_value
        for tag in tags:
            result.append({"tag": tag, "delta": delta, "now": now_value, "project": project})
    aggregated: dict[str, dict] = {}
    for entry in result:
        agg = aggregated.setdefault(entry["tag"], {"tag": entry["tag"], "delta": 0, "now": 0, "projects": 0})
        agg["delta"] += entry["delta"]
        agg["now"] += entry["now"]
        agg["projects"] += 1
    ranked = sorted(aggregated.values(), key=lambda x: -x["delta"])[:top]
    prediction = ""
    if ranked:
        lead = ranked[0]
        prediction = (
            f"按近 {days} 天增速，「{lead['tag']}」是当前最强的热点方向"
            f"（热度增量 {lead['delta']:+,}，覆盖 {lead['projects']} 个项目），"
            "预计未来一周相关项目供给与关注度继续上升。"
        )
    return {"tags": ranked, "prediction": prediction, "windowDays": days}


def timezone_ceiling():
    """Helper so tag_trends can filter logs regardless of future timestamps."""
    return dj_timezone.now() + timedelta(days=1)
