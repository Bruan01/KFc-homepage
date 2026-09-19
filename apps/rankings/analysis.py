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


# 规则通道:按 topic / metric 衍生多段落分析。
# 字段对齐 kaiyuanbang 详情页的「项目定位 / 适合谁 / 典型场景 / 核心功能 /
# 架构与工作机制 / 主要优势 / 限制与注意点 / 部署难度 / 风险限制 / 可借鉴点」。
# 至少有一个键;LLM 通道会用同一 schema,LLM 失败时回落到这里。
TOPIC_PROFILES: dict[str, dict] = {
    "ai": {
        "positioning": "把大模型能力封装成可独立交付的产品,围绕 AI 辅助开发流形成闭环。",
        "audience": "使用 Claude Code / Cursor / Codex 等 AI 编码工具的开发者,以及对 AI 工作流感兴趣的产品团队。",
        "use_cases": [
            "把大模型接入 IDE 或终端,辅助代码生成、阅读与重构",
            "提供 agent 化的任务规划与多步骤工具调用",
            "在本地或私有部署环境使用 OpenAI 兼容 API",
        ],
        "core_features": [
            "兼容主流 LLM 与 OpenAI 协议,支持模型热切换",
            "提供 prompt / 上下文工程封装,降低使用门槛",
            "可与 Git、CLI、IDE 等开发工具链集成",
        ],
        "architecture": "通常以客户端 + LLM API 为核心,客户端负责上下文编排与工具调用,服务端(若有)负责知识库或权限策略;本地部署依赖模型兼容层。",
        "advantages": [
            "减少重复编码工作,把精力集中在业务逻辑",
            "比纯 Web 聊天更适合代码场景,支持多文件与长上下文",
            "本地化部署可避免企业数据外传",
        ],
        "limitations": [
            "依赖底层模型能力,模型升级可能改变行为",
            "长上下文成本高,大型项目需自建索引或分片",
        ],
        "deployment": "通常 Node.js / Python 包或 CLI;Python 项目一般 `pip install` 即可,Node 项目 `npm i -g` 全局安装或 npx 一次性运行。",
        "risks": "对模型输出无强校验,关键操作(写文件、执行命令)需要二次确认;生产环境需考虑 prompt 注入与越权风险。",
        "takeaway": "可借鉴:从「AI + 单一开发动作」的最小闭环切入(比如只做代码解释或只做 commit 信息生成),再扩展到多步 agent。",
    },
    "agent": {
        "positioning": "把多步骤任务交给自主 agent 执行,让人类只参与关键决策与审批。",
        "audience": "需要批量处理文档、代码、表格等结构化任务的工程师与运营人员。",
        "use_cases": [
            "自动拉取并总结 GitHub Issue / 邮件 / 工单",
            "在沙箱里执行多步 shell 命令完成部署/迁移",
            "替代或辅助 RPA 流程,串联多个 SaaS API",
        ],
        "core_features": [
            "任务规划:把目标拆解为可执行的子步骤",
            "工具调用:浏览器 / Shell / HTTP / 文件系统",
            "可观测:trace 与回放每一步决策",
        ],
        "architecture": "通常 LLM-as-orchestrator + 工具注册中心 + 持久化记忆 + 沙箱执行环境;高级 agent 引入多 agent 协作或反思机制。",
        "advantages": [
            "把人类从重复操作里解放出来,7×24 自动化",
            "出错时可逐步回放,定位问题更直接",
            "可与人类协作,在关键节点请求确认",
        ],
        "limitations": [
            "复杂任务 token 消耗高,长链路易跑偏",
            "工具描述质量直接影响 agent 行为",
        ],
        "deployment": "多为 Python 框架或 SaaS 服务;自部署需准备 LLM 端点与可执行沙箱(容器/VM),SaaS 形态开箱即用但有数据合规顾虑。",
        "risks": "agent 写操作缺少审计会带来误操作风险,生产环境务必开启 step-level 审批与回滚机制。",
        "takeaway": "可借鉴:先用 agent 处理确定性高、流程清晰的任务(批量文件改名、定时报告),再扩展到需要判断的复杂场景。",
    },
    "cli": {
        "positioning": "命令行优先的工具设计,把复杂能力压进终端工作流。",
        "audience": "重度终端用户、运维工程师,以及追求脚本化、可组合工作流的开发者。",
        "use_cases": [
            "在终端里跑生成/转换/部署命令,代替 Web 操作",
            "接入 CI 与 shell 脚本,做自动化流水线",
            "通过管道与其他工具组合(`... | your-cli | ...`)",
        ],
        "core_features": [
            "零配置/低依赖安装(`brew install` / `npm i -g`)",
            "完整的 man 风格帮助文档与 shell 补全",
            "可管道化、可作为子命令被其他工具调用",
        ],
        "architecture": "通常本地运行;Rust / Go 编译为单二进制,Node / Python 走解释执行;状态文件存 `~/.config` 或 `XDG_CONFIG_HOME`。",
        "advantages": [
            "启动快、资源占用低,服务器/容器里也能跑",
            "天然适合脚本化与 CI 集成",
            "无 GUI 依赖,SSH/远程机器上一样可用",
        ],
        "limitations": [
            "学习曲线比 GUI 工具陡",
            "复杂交互(预览、图表)在终端里表现受限",
        ],
        "deployment": "优先用包管理器(`brew`、`apt`、scoop)或语言自带安装(`pipx`、`npm i -g`);CI 里用容器镜像或预装脚本。",
        "risks": "命令直接操作文件系统,缺乏撤销机制,生产部署务必配合 `--dry-run` 与变更审计。",
        "takeaway": "可借鉴:把高频操作(发布、生成、转换)固化成 CLI 子命令,用 `--help` 和管道支持让脚本化成为默认路径。",
    },
    "developer-tools": {
        "positioning": "提升工程师日常开发效率的工具,聚焦在编辑、调试、构建、发布的某个具体痛点。",
        "audience": "全职软件工程师、DevOps、SRE,以及追求效率的独立开发者。",
        "use_cases": [
            "在编辑器/IDE 里跑生成、跳转、重构命令",
            "在 CI 里执行静态检查、依赖升级、版本发布",
            "把团队规范(命名、提交信息、文档)自动化",
        ],
        "core_features": [
            "与主流编辑器/IDE/CI 的开箱集成",
            "零配置启动,默认值符合社区最佳实践",
            "可被规则文件扩展,适配团队自定义",
        ],
        "architecture": "以本地 CLI / Language Server / 编辑器插件形态为主;少数提供 SaaS 协作层,核心逻辑仍在本地保证响应速度。",
        "advantages": [
            "直接消灭重复劳动(找 bug、写样板代码、检查规范)",
            "不引入新依赖,几分钟内接入现有工作流",
            "团队统一工具链后协作摩擦更少",
        ],
        "limitations": [
            "工具碎片化,需要时间评估哪款真正合适",
            "团队规范变化时,工具规则文件要同步更新",
        ],
        "deployment": "多为编辑器插件市场或 `npm i -D`/`cargo install`;团队级部署通常以 dotfiles 或内部 npm registry 统一分发。",
        "risks": "工具版本升级可能引入行为变化,CI/编辑器里要锁定版本或做兼容性测试。",
        "takeaway": "可借鉴:从「每天重复 5 次以上」的动作切入,做一个最小可用 CLI/LSP,再用配置文件暴露高级选项。",
    },
    "data": {
        "positioning": "围绕数据的采集、清洗、存储、查询与可视化,降低工程团队的数据处理门槛。",
        "audience": "数据工程师、分析师,以及需要自助查询数据的业务团队。",
        "use_cases": [
            "把多源异构数据同步到统一仓库/数仓",
            "在终端/SQL/笔记本里做交互式分析",
            "一键生成报表、看板与定时任务",
        ],
        "core_features": [
            "支持主流数据源(SQL、NoSQL、API、文件)",
            "本地或嵌入式部署,避免数据外传",
            "可观测:作业状态、行级血缘与错误定位",
        ],
        "architecture": "通常是 connector + transform/计算引擎 + 元数据存储三层;轻量工具用 DuckDB/Polars 单机引擎,大数据用 Spark/Flink 集群。",
        "advantages": [
            "本地化部署满足合规要求",
            "SQL/脚本化的交互体验比 BI 工具灵活",
            "配合 LLM 可实现自然语言查询",
        ],
        "limitations": [
            "嵌入式引擎单机性能上限受限",
            "可视化能力通常弱于专业 BI 工具",
        ],
        "deployment": "嵌入式工具 pip/cargo 安装即用;集群方案需准备对象存储与调度器,门槛较高。",
        "risks": "SQL 注入与敏感数据导出是常见风险,生产环境必须配置权限与脱敏。",
        "takeaway": "可借鉴:从「本地 + SQL/笔记本」作为入口,提供清晰的 connector 与 schema 推断,再逐步加入云端能力。",
    },
    "rag": {
        "positioning": "把检索增强生成(RAG)落地为可用产品,让大模型引用私有知识回答问题。",
        "audience": "需要把内部文档/代码/工单接入 LLM 的企业研发与产品团队。",
        "use_cases": [
            "把企业 wiki、Confluence、Notion 文档接入 LLM",
            "代码库级别的问答,支持跨文件理解",
            "工单/客服系统的自动答复与知识检索",
        ],
        "core_features": [
            "多格式文档解析(PDF/Markdown/HTML/代码)",
            "向量化 + 混合检索(关键词 + 语义)",
            "引用溯源,答案可点击跳转原文",
        ],
        "architecture": "文档解析 → 分块 → embedding → 向量库;检索时混合召回 → 重排 → 拼接到 LLM 上下文;生产系统还会加权限、缓存与监控层。",
        "advantages": [
            "让 LLM 回答基于真实文档,降低幻觉",
            "可对接企业现有数据源,无需迁移",
            "可解释:答案能追溯到具体段落",
        ],
        "limitations": [
            "长文档/表格/图片仍依赖高质量 OCR 与解析",
            "向量检索精度受 embedding 模型影响",
        ],
        "deployment": "本地栈可走 Ollama + Postgres/pgvector;云上常见 Pinecone/Weaviate + 任意 LLM API。",
        "risks": "敏感数据进入向量库前需做权限隔离;跨租户检索要严格按 namespace 隔离,避免越权召回。",
        "takeaway": "可借鉴:从「文档解析 + 引用溯源」入手,把可解释性作为产品差异点,再扩展到多源融合与权限。",
    },
    "self-hosted": {
        "positioning": "面向私有部署的工具,满足数据合规、定制化与成本可控的需求。",
        "audience": "企业 IT、个人开发者、对数据敏感的研究团队。",
        "use_cases": [
            "在公司内网或私有云里部署替代 SaaS",
            "在 NAS、家庭服务器里跑轻量服务",
            "作为内部平台底座,定制化扩展",
        ],
        "core_features": [
            "一键 Docker / Compose 部署",
            "支持外部数据库与对象存储",
            "备份/恢复/升级流程完善",
        ],
        "architecture": "通常提供 Docker 镜像 + Helm chart + 配置文件三件套;数据存 PostgreSQL/SQLite + S3 兼容对象存储;少数支持 ARM/x86 双架构。",
        "advantages": [
            "数据不出本地,满足合规",
            "无按月计费,长期成本可控",
            "可深度定制,集成内部系统",
        ],
        "limitations": [
            "运维需要自己兜底(备份、升级、监控)",
            "部分功能依赖外部 SaaS(LLM、邮件)",
        ],
        "deployment": "最小 1 台 VPS + Docker compose;生产环境通常用 Kubernetes 或托管容器平台。",
        "risks": "升级前必须读 changelog,部分项目数据库 schema 变更无向下兼容;备份策略要按 RPO/RTO 目标设计。",
        "takeaway": "可借鉴:把「5 分钟跑起来」作为第一个 milestone,默认配置覆盖 90% 场景,再用环境变量/挂载点暴露高级选项。",
    },
    "open-source": {
        "positioning": "围绕开源生态的工具与最佳实践,降低个人/团队的开源协作成本。",
        "audience": "独立开发者、开源项目维护者、开源治理团队。",
        "use_cases": [
            "自动生成 changelog、版本号、Release Note",
            "管理 issue/PR 模板、标签、贡献者协议",
            "镜像/同步开源仓库到内网",
        ],
        "core_features": [
            "与 GitHub/GitLab 等平台深度集成",
            "可被 GitHub Actions 等 CI 平台触发",
            "配置文件可版本化,纳入代码仓库",
        ],
        "architecture": "以 CLI + GitHub App / GitLab CI 集成为常见形态;部分以 SaaS 提供额外可视化层。",
        "advantages": [
            "释放维护者的时间,把精力放在代码本身",
            "统一团队的开源治理规范",
            "社区贡献者体验更一致",
        ],
        "limitations": [
            "强依赖上游平台 API,大版本变更需适配",
            "部分高级功能需要付费 SaaS",
        ],
        "deployment": "几乎都是 `npm i -g` 或 pip 安装;CI 集成只需在 `.github/workflows` 加一步。",
        "risks": "上游 API 限流或废弃会导致工具失效,关键流程要有兜底方案。",
        "takeaway": "可借鉴:从一个能「5 分钟解决一个真实痛点」的工具切入,在 README 里给出可复制的 GitHub Action 片段。",
    },
}

DEFAULT_PROFILE: dict = {
    "positioning": "围绕 vibecoding 场景的开源项目,把 AI 能力嵌入具体工作流。",
    "audience": "使用 AI 编程工具的开发者、对自动化感兴趣的工程师与产品团队。",
    "use_cases": [
        "在日常开发/创作流程里嵌入 AI 能力",
        "把重复任务自动化,提升交付效率",
        "通过开源社区获取早期反馈与协作者",
    ],
    "core_features": [
        "围绕一个明确痛点设计,功能边界清晰",
        "提供 CLI/包/API 至少一种接入方式",
        "开源协议清晰,易二次开发",
    ],
    "architecture": "通常是 CLI + 库 + 配置文件三层;本地或自托管部署为主,云端服务作为可选增强。",
    "advantages": [
        "聚焦单一痛点,实现质量通常高于通用工具",
        "社区驱动迭代,新需求响应快",
        "代码可读,便于二次定制",
    ],
    "limitations": [
        "小众项目维护节奏不稳定",
        "文档与示例可能滞后于版本",
    ],
    "deployment": "优先 pip/pipx、npm/cargo/brew;复杂项目用 docker compose 一键启动。",
    "risks": "开源项目作者精力变化可能导致项目进入维护期,选型时要关注最近提交活跃度。",
    "takeaway": "可借鉴:从「自身体验过的具体痛点」切入,先做最小可用版本,再根据社区反馈迭代。",
}


def _maturity(metric: int, growth: int) -> str:
    """根据 stars / 30 日增长判断项目阶段。"""
    if metric >= 50000:
        return "成熟"
    if metric >= 10000:
        return "成长期"
    if growth >= 3000:
        return "快速增长"
    if metric >= 1000:
        return "早期但活跃"
    return "新晋"


def _rule_analysis(project: ExternalProject, tags: list[str], metrics: dict) -> dict:
    """按 topic 选 profile,再用 metric 修饰具体数字段。无 LLM 时的兜底。"""
    topic = (metrics.get("topic") or "").strip().lower()
    lang = (project.language or metrics.get("language") or "").strip()
    license_text = (metrics.get("license") or "").strip()
    stars = int(metrics.get("stars") or 0)
    forks = int(metrics.get("forks") or 0)
    growth = int(metrics.get("growth_30d") or 0)

    profile = TOPIC_PROFILES.get(topic) or DEFAULT_PROFILE

    # 成熟度 + 增长修饰 advantages / use_cases / takeaway
    maturity = _maturity(stars, growth)
    growth_line = ""
    if growth:
        growth_line = f"近 30 天增长 +{growth:,},势头不错。"

    # 部署段加入语言信息
    deployment = profile["deployment"]
    if lang and "{lang}" not in deployment:
        deployment = f"语言为 {lang}。" + deployment

    # 限制段根据成熟度补一句
    limitations = list(profile["limitations"])
    if maturity == "新晋":
        limitations.append("项目尚在早期,生态与文档尚待完善。")
    elif maturity == "成熟":
        limitations.append("代码规模较大,二次定制需熟悉架构。")

    # 优势段加入社区规模数据
    advantages = list(profile["advantages"])
    if stars >= 10000:
        advantages.append(
            f"社区规模较大(Stars {stars:,}),插件/集成/教程生态丰富。"
        )
    if forks >= 1000:
        advantages.append(
            f"被广泛 fork/二次开发(Forks {forks:,}),表明模块化设计被认可。"
        )

    # take-away 数字版
    takeaway = profile["takeaway"]
    if stars >= 50000:
        takeaway += f" 累计 {stars:,} Stars,可见需求已被验证,可重点研究它的传播路径。"

    # 风险段补充协议/维护信息
    risks = profile["risks"]
    if license_text and license_text.lower() not in {"mit", "apache-2.0"}:
        risks += f" 许可证为 {license_text},商用前请评估条款。"

    return {
        "positioning": profile["positioning"],
        "audience": profile["audience"],
        "use_cases": profile["use_cases"],
        "core_features": profile["core_features"],
        "architecture": profile["architecture"],
        "advantages": advantages,
        "limitations": limitations,
        "deployment": deployment,
        "risks": risks,
        "takeaway": takeaway + ((" " + growth_line) if growth_line else ""),
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
    """Ask the LLM for comprehensive summary/tags/analysis as strict JSON.

    字段对照 kaiyuanbang 详情页:positioning / audience / use_cases /
    core_features / architecture / advantages / limitations / deployment /
    risks / takeaway + summary + tags。
    """
    metric = _primary_metric(metrics)
    system = (
        "你是 vibecoding 社区的产品 + 技术分析师。只输出 JSON,不要 markdown 代码块,不要解释。"
        "字段(全部中文):"
        "summary(不超过 60 字的一句话概括);"
        "tags(3-4 个,严格从 {\"AI\",\"Agent\",\"MCP\",\"RAG\",\"CLI\",\"Web 应用\","
        "\"浏览器插件\",\"游戏\",\"机器人\",\"数据\",\"自托管\",\"设计\",\"开发效率\",\"开源\"} 中选);"
        "positioning(产品定位,一句话);"
        "audience(目标用户与场景,一句话);"
        "use_cases(典型使用场景,3-5 条短句数组);"
        "core_features(核心功能/能力,3-5 条短句数组);"
        "architecture(架构与工作机制,2-3 句);"
        "advantages(主要优势,3-5 条短句数组);"
        "limitations(限制与注意点,2-3 条短句数组);"
        "deployment(部署难度 + 部署建议,1-2 句);"
        "risks(风险与边界,1-2 句);"
        "takeaway(对 vibecoding 社区用户的可借鉴点 + 选型建议,1-2 句)。"
    )
    user = (
        f"项目：{project.title}\n"
        f"来源：{SOURCE_LABEL.get(project.source, project.source)}\n"
        f"热度指标(stars/增长)：{metric} / 30 日增长 {metrics.get('growth_30d', 0)}\n"
        f"语言：{project.language or '未知'}    "
        f"许可证：{metrics.get('license') or '未知'}\n"
        f"仓库：{project.language}\n"
        f"项目官网：{metrics.get('homepage') or '无'}\n"
        f"创建时间：{metrics.get('created_at') or '未知'}\n"
        f"描述：{(project.description or '无')[:600]}"
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
            "analysis": _normalized_analysis(data),
        }
    except (ValueError, TypeError, KeyError):
        return None


def _normalized_analysis(data: dict) -> dict:
    """Normalize LLM/rule output to a stable schema the frontend can rely on."""
    return {
        "positioning": str(data.get("positioning", ""))[:200],
        "audience": str(data.get("audience", ""))[:200],
        "use_cases": [str(s)[:140] for s in (data.get("use_cases") or []) if s][:6],
        "core_features": [str(s)[:140] for s in (data.get("core_features") or []) if s][:6],
        "architecture": str(data.get("architecture", ""))[:400],
        "advantages": [str(s)[:140] for s in (data.get("advantages") or []) if s][:6],
        "limitations": [str(s)[:140] for s in (data.get("limitations") or []) if s][:4],
        "deployment": str(data.get("deployment", ""))[:300],
        "risks": str(data.get("risks", ""))[:300],
        "takeaway": str(data.get("takeaway", ""))[:300],
    }


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
    """Analyze the top-N hottest projects per active source (default 10)."""
    analyzed = 0
    sources = list(
        ExternalProject.objects.filter(is_active=True)
        .values_list("source", flat=True).order_by().distinct()
    )
    for source in sources:
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
