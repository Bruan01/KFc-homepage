# pyright: reportMissingImports=false
"""Seed glossary terms (each with a detail page) and detailed tutorials (idempotent).

内容基于 2026 年 vibecoding 社区的主流实践整理：
- 氛围编程由 Andrej Karpathy 于 2025 年初提出；
- 2026 年共识从「随性 prompt」转向规范的上下文工程与小步验收；
- 工具生态以 Cursor / Claude Code / Copilot / Windsurf / Replit Agent / Cline 等为主。
"""
from django.core.management.base import BaseCommand

from apps.learn.models import GlossaryTerm, Tutorial

# ─────────────────────────────────────────────────────────────────────────────
# 术语（30 条，每条都有独立详情页正文）
# 字段：(slug, 术语, 英文, 分类, 一句话解释, 详情正文 Markdown, sort)
# ─────────────────────────────────────────────────────────────────────────────
GLOSSARY = [
    (
        "vibe-coding", "氛围编程", "Vibe Coding", "基础概念",
        "由 Andrej Karpathy 提出的开发方式：用自然语言向 AI 描述需求，由 AI 生成代码，人负责引导、验收和迭代。",
        """## 是什么

**氛围编程（Vibe Coding）** 由 OpenAI 联合创始人 Andrej Karpathy 在 2025 年初提出。他形容这是一种"全情投入氛围、拥抱指数级增长、甚至忘记代码本身存在"的开发方式——你用自然语言告诉 AI 你想要什么，AI 负责写代码，你负责描述、验收、再描述。

## 2026 年的演进

社区经过一年多的实践，共识已经从"随性 prompt"进化为**有纪律的 vibe coding**：

- 随性 prompt 只适合一次性小工具（原型、玩具）；
- 要做出**可维护的真实产品**，需要配合上下文工程、需求先行、小步验收等方法（详见本站[上下文工程](/glossary/context-engineering)、[需求先行](/glossary/spec-driven)词条）。

## 在 Vibecoding 中怎么用

1. 选一款 [AI 编程工具](/glossary/ai-coding-tools)（Cursor、Claude Code 等）；
2. 用[提示词](/glossary/prompt)描述需求，让 AI 生成第一版；
3. 亲自运行、验收，发现问题继续对话修正（[迭代循环](/glossary/iterative-loop)）；
4. 满意后部署上线，来社区发帖晒作品。

## 上手示例

> 「帮我做一个网页版番茄钟：25 分钟倒计时、结束提醒、每天专注统计存 localStorage，单文件双击就能玩。」

这一条 prompt 就是一个最小的 vibe coding 实践。

## 相关词条

- [提示词](/glossary/prompt) · [迭代循环](/glossary/iterative-loop) · [验收标准](/glossary/acceptance-criteria)""",
        1,
    ),
    (
        "prompt", "提示词", "Prompt", "基础概念",
        "喂给 AI 的指令文本，写得好坏直接决定产出质量。",
        """## 是什么

**提示词（Prompt）** 是你发给 AI 的所有指令文本。在 vibecoding 里，它取代了"写代码"成为最核心的工作产出——代码由 AI 写，但**让 AI 写什么的描述权在你手里**。

## 为什么重要

同一个需求，两种 prompt 的产出可能天差地别：

- ❌ 「帮我做个待办清单」→ AI 自由发挥，做出来什么看运气
- ✅ 「做一个待办清单 Web 应用：左侧输入支持 Markdown 列表，右侧实时渲染勾选框，状态存 localStorage；单 HTML 文件、移动端可用；验收：刷新后状态还在、无控制台报错」→ 产出可控可验收

## 在 Vibecoding 中怎么用

好 prompt 的四段式结构（详见[一句话应用](/glossary/one-shot-app)）：

1. **角色**：你是一名资深前端工程师
2. **目标**：做什么，具体到功能点
3. **约束**：技术栈、单文件、风格等边界
4. **验收**：列出可检查的完成标准

## 上手示例

把「做得好看点」换成可执行的具体描述：

> 「使用系统字体 + 中性灰配色，卡片圆角 16px，主色 #0071e3，深色背景 #f5f5f7，参考 Apple 官网气质。」

## 相关词条

- [验收标准](/glossary/acceptance-criteria) · [系统提示词](/glossary/system-prompt) · [上下文工程](/glossary/context-engineering)""",
        2,
    ),
    (
        "context", "上下文", "Context", "基础概念",
        "AI 当前能「看到」的全部信息（对话、文件、规则），组织得好坏决定输出上限。",
        """## 是什么

**上下文（Context）** 是 AI 在一次对话中能「看到」的全部信息：系统提示词、你们的完整对话历史、打开的文件、项目规则文件等。AI 的输出质量上限，基本由上下文质量决定——**垃圾进，垃圾出**。

## 为什么重要

vibecoding 里大部分"AI 变笨了"的问题，根源都是上下文问题：

- 对话太长，早期约定被稀释 → AI 忘了之前的要求
- 没有把相关文件喂给它 → AI 凭空编造接口
- 项目规则没写 → 每次都要重复交代团队规范

## 在 Vibecoding 中怎么用

1. **按需喂料**：让 AI 改某个文件前，确保该文件在上下文里（Cursor 自动带仓库感知，Claude Code 用 @文件 引用）；
2. **控制对话长度**：一个任务一个会话，做完就开新会话，避免上下文污染；
3. **沉淀到规则文件**：把长期有效的约定写进 [CLAUDE.md](/glossary/rules-file)，不要每次口头重复；
4. 系统性的方法叫[上下文工程](/glossary/context-engineering)。

## 相关词条

- [上下文窗口](/glossary/context-window) · [上下文工程](/glossary/context-engineering) · [规则文件](/glossary/rules-file)""",
        3,
    ),
    (
        "context-window", "上下文窗口", "Context Window", "基础概念",
        "AI 一次能处理的最大 token 量，超出的内容会「失忆」。",
        """## 是什么

**上下文窗口（Context Window）** 是模型单次能处理的最大 token 数量，常见的有 128K、200K 甚至 1M token。窗口内的内容 AI 都"看得见"，**窗口外的内容对它来说不存在**。

## 为什么重要

1. **遗忘**：对话超过窗口后，最早的内容被挤出，AI 会"忘记"你最初的要求；
2. **成本**：输入 token 也计费，把整个仓库塞进去又贵又慢；
3. **注意力稀释**：即使都在窗口内，内容越多，AI 对每一条的注意力越分散。

## 在 Vibecoding 中怎么用

- 长对话发现 AI 开始"忘事"：把关键约定重新粘贴一次，或开新会话并附上摘要；
- 大文件只喂相关部分（函数、类），不要整文件粘贴；
- 不同模型窗口大小不同：选工具时留意（如 Claude 系列通常 200K token）。

## 相关词条

- [上下文](/glossary/context) · [Token](/glossary/token) · [上下文工程](/glossary/context-engineering)""",
        4,
    ),
    (
        "token", "Token", "Token", "基础概念",
        "AI 处理与计费的最小文本单位，约等于 0.5~1.5 个汉字或 0.75 个英文单词。",
        """## 是什么

**Token** 是大模型处理文本的最小单位。模型不直接"看"字符，而是看 token 序列：一个英文单词通常是 1~2 个 token，一个汉字通常 1~2 个 token，一段代码按符号与标识符切分。

## 为什么重要

1. **计费单位**：API 按 token 计费（输入+输出），账单直接由 token 量决定；
2. **速度**：token 越多，响应越慢；
3. **窗口**：[上下文窗口](/glossary/context-window)的大小就是以 token 计。

## 在 Vibecoding 中怎么用

- **省钱**：精简 prompt、只喂相关文件、避免把超长日志整段贴进去；
- **估量**：中文 1 个字 ≈ 1~2 token；一篇 3000 字的 PRD ≈ 4000~6000 token；
- **订阅制工具**（Cursor Pro、Claude Pro 等）按额度而非 token 计费，但额度背后仍是 token，重用户会遇到限速。

## 相关词条

- [上下文窗口](/glossary/context-window) · [上下文工程](/glossary/context-engineering)""",
        5,
    ),
    (
        "hallucination", "AI 幻觉", "Hallucination", "基础概念",
        "AI 一本正经地编造不存在的 API、库或事实，需要人工验收兜底。",
        """## 是什么

**AI 幻觉（Hallucination）** 指模型以确定的语气输出错误内容：调用不存在的 API、引用过时的库版本、编造配置项，甚至虚构「事实」。

## 为什么危险

vibecoding 里幻觉最常出现在：

- **API 幻觉**：使用某个库的参数根本不存在（训练数据过旧或记混了版本）；
- **逻辑幻觉**：代码看起来合理但边界条件是错的；
- **事实幻觉**：回答里编造文档链接、版本号、命令行参数。

## 在 Vibecoding 中怎么用（防幻觉清单）

1. **让 AI 先读再写**：把相关文件、官方文档片段喂进上下文，减少凭记忆瞎写；
2. **运行验证**：代码必须跑起来，装不上的依赖、报错的方法立刻暴露幻觉；
3. **锁定版本**：prompt 里明确"使用 xxx 库 3.x 版本"；
4. **让 AI 自己检查**：「列出你刚才用到的所有 API，逐一确认在该库当前版本中存在」；
5. 永远保留[人工审查](/glossary/human-review)环节。

## 相关词条

- [人工审查](/glossary/human-review) · [验收标准](/glossary/acceptance-criteria) · [测试驱动](/glossary/test-driven-vibe)""",
        6,
    ),
    (
        "human-review", "人工审查", "Human Review", "基础概念",
        "人对 AI 产出的检查与修正；vibecoding 不等于不看不测，上线前必须审查。",
        """## 是什么

**人工审查（Human Review）** 是 vibecoding 里的质量兜底环节：AI 生成，人来把关。Karpathy 在提出 vibe coding 时也强调，这类方式"适合周末玩具项目"，**生产代码仍需严格审查**。

## 审查什么

| 审查项 | 检查方式 |
| --- | --- |
| 功能正确性 | 亲自操作，对照[验收标准](/glossary/acceptance-criteria)逐条验收 |
| 安全性 | 有没有硬编码密钥、SQL 注入、XSS（让 AI 自查：「以安全工程师视角审查这段代码」） |
| 依赖与版本 | 装依赖时锁定版本，警惕幻觉包名（供应链风险） |
| 代码质量 | 命名、结构、重复度——可以让 AI 重构自己 |
| 边界情况 | 空数据、超长输入、并发、断网 |

## 在 Vibecoding 中怎么用

- 小步提交：每验收通过一步就 commit，出问题能回滚；
- 让 AI 生成「自查清单」再逐项过；
- 重要项目请同伴或让另一个 AI 实例做 code review（"第二双眼睛"模式）。

## 相关词条

- [AI 幻觉](/glossary/hallucination) · [验收标准](/glossary/acceptance-criteria) · [迭代循环](/glossary/iterative-loop)""",
        7,
    ),
    (
        "one-shot-app", "一句话应用", "One-shot App", "基础概念",
        "一条 prompt 直接生成的完整小应用，是 vibecoding 最经典的玩法。",
        """## 是什么

**一句话应用（One-shot App）** 指用一条精心构造的 prompt，让 AI 一次性生成一个完整可运行的小应用——贪吃蛇、番茄钟、Markdown 编辑器、记账本……它是 vibecoding 的"Hello World"。

## 为什么是经典玩法

1. **即时正反馈**：几分钟看到能玩的东西，学习动力最强；
2. **验证 prompt 功力**：一句话应用的质量直接反映 prompt 结构化程度；
3. **社区文化**：本站"晒作品"分类里最常见的帖子类型。

## 四段式 prompt 模板

1. **角色**：你是一名资深前端工程师
2. **目标**：做一个[具体功能]的网页应用（列清功能点）
3. **约束**：单文件 / 无依赖 / 移动端可用 / 深色风格
4. **验收**：打开即用；列出 2~3 条可检查行为（如"刷新后数据还在""无控制台报错"）

## 上手示例

> 你是一名资深前端工程师。做一个 Markdown 待办清单：左侧输入区支持标准 Markdown 列表语法，右侧实时渲染成带勾选框的清单，勾选状态自动保存到 localStorage。约束：单个 HTML 文件、无构建工具、手机上也能用。验收：粘贴列表立刻渲染；刷新后勾选状态还在；无控制台报错。

做完发到社区[晒作品](/forum?compose=1)，拿到第一波反馈。

## 相关词条

- [提示词](/glossary/prompt) · [验收标准](/glossary/acceptance-criteria) · [部署](/glossary/deployment-vibe)""",
        8,
    ),
    (
        "ai-coding-tools", "AI 编程工具", "AI Coding Tools", "工具生态",
        "Cursor、Claude Code、Windsurf、Copilot、Replit Agent、Cline 等以 AI 为核心的开发环境。",
        """## 是什么

**AI 编程工具** 是 vibecoding 的"画笔"。2026 年主流工具分三类：

| 类型 | 代表 | 特点 |
| --- | --- | --- |
| AI 原生 IDE | **Cursor**、Windsurf | 编辑器形态，仓库级感知（repo-wide context），Tab 补全极强，适合日常开发主力 |
| 终端智能体 | **Claude Code** | 终端形态的 Agent，能自主执行多步任务（读写文件、跑命令、提 commit），适合大型重构与自动化工作流 |
| 云端/托管 Agent | **Replit Agent**、Google Antigravity、OpenAI Codex | 从需求到部署一条龙，适合零环境搭建的快速原型 |
| 开源插件 | **Cline / Roo Code**（VS Code 插件）、GitHub **Copilot** | 可自选模型、可控成本；Copilot 补全成熟，Agent 能力在追赶 |

## 怎么选（2026 共识）

- **日常写码主力**：Cursor（体验最顺）或 Copilot（企业普及度高）
- **大型任务 / 多文件重构 / 自动化**：Claude Code（agentic 能力最强）
- **零基础快速出原型**：Replit Agent / Lovable / Bolt（浏览器里从想法到上线）
- **成本敏感 / 想用国产或本地模型**：Cline + 自选 API

## 在 Vibecoding 中怎么用

工具会不停变，**方法论不变**：上下文管理、小步验收、版本回滚。先用一款上手，再横向对比（社区"晒作品"里常有同题多工具对比帖）。

## 相关词条

- [MCP](/glossary/mcp) · [规则文件](/glossary/rules-file) · [上下文工程](/glossary/context-engineering)""",
        10,
    ),
    (
        "cursor", "Cursor", "Cursor", "工具生态",
        "AI 原生 IDE 的代表：仓库级上下文感知 + 极强的 Tab 补全 + Agent 模式。",
        """## 是什么

**Cursor** 是基于 VS Code 分支的 AI 原生 IDE，2026 年仍是多数 vibecoder 的主力工具。核心能力：

1. **Tab 补全**：根据整个仓库的上下文预测你的下一次编辑（跨文件、多行）；
2. **Chat / Composer**：对话式开发，Composer/Agent 模式可自主跨文件修改；
3. **仓库感知**：自动索引代码库，提问时检索相关片段注入上下文；
4. **规则文件**：支持 `.cursorrules` / `.cursor/rules` 沉淀项目约定。

## 在 Vibecoding 中怎么用

- **@ 引用**：`@文件`、`@文件夹`、`@文档` 精准控制上下文；
- **Agent 模式**：复杂任务交给 Agent 自主执行，你负责验收每一步 diff；
- **Notepads**：把常用 prompt 模板存成便签随时插入。

## 小贴士

- 模型可选（GPT/Claude 系列），不同任务换模型：补全用快的，重构用强的；
- 配合[规则文件](/glossary/rules-file)让项目约定自动生效；
- 大改动前 commit，Agent 跑飞了随时回滚（[Git 与回滚](/glossary/git-workflow)）。

## 相关词条

- [AI 编程工具](/glossary/ai-coding-tools) · [规则文件](/glossary/rules-file) · [上下文](/glossary/context)""",
        11,
    ),
    (
        "claude-code", "Claude Code", "Claude Code", "工具生态",
        "终端形态的编程智能体：能自主读写文件、执行命令、多步完成大型任务。",
        """## 是什么

**Claude Code** 是 Anthropic 推出的终端（CLI）编程智能体。与 IDE 补全不同，它是 **Agent 形态**：给它一个目标，它会自己拆解步骤、读写文件、运行命令、根据报错自我修正，直到完成。

## 核心能力

1. **自主执行**：多步任务（"把这个模块从 JS 迁移到 TS 并跑通测试"）一条指令完成；
2. **工具调用**：读写文件、执行 shell、搜索代码、操作 Git；
3. **CLAUDE.md**：项目记忆文件，自动注入项目约定（见[规则文件](/glossary/rules-file)）；
4. **MCP 支持**：接入外部工具（数据库、浏览器、issue 系统）扩展能力（见 [MCP](/glossary/mcp)）。

## 在 Vibecoding 中怎么用

```bash
# 安装后进入项目目录
claude
> 阅读 PRD.md，实现用户认证模块，写好测试并跑通
```

- **先写 PRD 再执行**：Claude Code 特别适合[需求先行](/glossary/spec-driven)工作流；
- **权限控制**：文件编辑、命令执行可配置确认级别；
- **成本**：按 token 计费，大任务注意拆步（[任务拆解](/glossary/task-breakdown)）。

## 适用场景

多文件重构、批量迁移、按 PRD 从零搭项目、自动化脚本任务——是"计划先行"范式的最佳拍档。

## 相关词条

- [AI 编程工具](/glossary/ai-coding-tools) · [需求先行](/glossary/spec-driven) · [规则文件](/glossary/rules-file)""",
        12,
    ),
    (
        "mcp", "MCP", "Model Context Protocol", "工具生态",
        "Anthropic 推出的开放协议，让 AI 工具以统一方式接入外部数据源和服务。",
        """## 是什么

**MCP（Model Context Protocol）** 是 Anthropic 在 2024 年底开放的协议，2025-2026 年已成为 AI 工具生态的事实标准。它定义了 AI 应用（客户端）与外部能力（服务器）之间的通用接口——**一次开发，处处可用**。

## 解决什么问题

没有 MCP 时，每个 AI 工具要接每个数据源都得单独写集成（M×N 问题）。有了 MCP：工具方实现一次 MCP Server，所有支持 MCP 的客户端（Claude Code、Cursor、Cline……）都能用（M+N）。

## 常见 MCP Server

| Server | 能力 |
| --- | --- |
| filesystem | 受控读写本地文件 |
| github | 查 issue、建 PR、读仓库 |
| postgres / sqlite | 查询数据库结构（只读为主） |
| puppeteer / playwright | 操作浏览器、截图、自动化 |
| slack / 飞书 | 收发消息 |

## 在 Vibecoding 中怎么用

以 Claude Code 为例：

```bash
claude mcp add github -- npx -y @modelcontextprotocol/server-github
```

配置后，你可以直接对话：「看一下 kfc-homepage 仓库最新的 issue，总结成清单」。AI 会自动调用 MCP 工具完成。

## 上手建议

1. 从官方 filesystem / github server 起步；
2. 只挂当前任务需要的 server（工具越多，上下文越吵）；
3. 自己写 server 也很简单：遵循协议暴露"工具"即可。

## 相关词条

- [Claude Code](/glossary/claude-code) · [工具调用](/glossary/tool-use) · [AI 编程工具](/glossary/ai-coding-tools)""",
        13,
    ),
    (
        "tool-use", "工具调用", "Tool Use / Function Calling", "工具生态",
        "AI 在对话中调用搜索、读写文件、执行命令等外部能力。",
        """## 是什么

**工具调用（Tool Use / Function Calling）** 让 AI 不只"说"，还能"做"：你（或工具框架）预先定义一组工具（名称、参数、说明），AI 根据任务自主决定调用哪个、传什么参数，拿到结果后继续推理。

## 一个典型循环

```
用户：帮我把项目里的 TODO 整理成清单
AI：调用 read_file("src/") → 扫描 → 调用 grep("TODO") → 汇总 → 输出清单
```

## 为什么是 vibecoding 的地基

编程智能体（Claude Code、Cursor Agent、Cline）的全部"自主能力"都建立在工具调用之上：

- 读写文件 → 改代码
- 执行命令 → 跑测试、装依赖
- 搜索 → 理解仓库
- [MCP](/glossary/mcp) → 接入一切外部系统

## 在 Vibecoding 中怎么用

1. **理解权限**：Agent 调用工具有风险（删文件、执行任意命令），合理设置确认级别；
2. **给好工具描述**：工具的说明写得越清楚，AI 用得越准；
3. **观察调用过程**：工具调用日志是最好的调试窗口——AI 的"思考路径"一目了然。

## 相关词条

- [智能体](/glossary/agent) · [MCP](/glossary/mcp) · [Claude Code](/glossary/claude-code)""",
        14,
    ),
    (
        "agent", "智能体", "Agent", "工具生态",
        "能自主拆解任务、调用工具、多轮执行直到目标完成的 AI 程序。",
        """## 是什么

**智能体（Agent）** = 大模型 + 工具调用 + 自主循环。与"一问一答"的对话式 AI 不同，Agent 接到目标后会：**拆解任务 → 选择工具 → 执行 → 观察结果 → 修正 → 循环**，直到完成或需要人工介入。

## 与聊天机器人的区别

| | 聊天机器人 | Agent |
| --- | --- | --- |
| 交互 | 一问一答 | 给目标，自主多步执行 |
| 能力 | 只能输出文本 | 调用工具改变真实世界（写文件、跑命令） |
| 你的角色 | 提问者 | 目标设定者 + 验收者 |

## 在 Vibecoding 中怎么用

编程 Agent（Claude Code、Cursor Agent、Replit Agent）的正确使用姿势：

1. **目标写清楚**：Agent 靠你的目标理解任务，参考[需求先行](/glossary/spec-driven)；
2. **给验收标准**：「完成后运行 `npm test`，全部通过且覆盖率不低于 80%」；
3. **分段监督**：长任务拆成里程碑，每个里程碑人工验收一次；
4. **控制爆炸半径**：给 Agent 的权限最小化，重要目录先 commit。

## 风险提示

Agent 会犯错且可能连环放大（一步错步步错）。**频繁验收 + 及时回滚**（[Git 与回滚](/glossary/git-workflow)）是安全绳。

## 相关词条

- [工具调用](/glossary/tool-use) · [需求先行](/glossary/spec-driven) · [迭代循环](/glossary/iterative-loop)""",
        15,
    ),
    (
        "rules-file", "规则文件", "Rules / CLAUDE.md", "工具生态",
        "放在项目里告诉 AI「这个项目怎么干」的说明书（如 CLAUDE.md、.cursorrules、AGENTS.md）。",
        """## 是什么

**规则文件** 是放在项目根目录、每次对话自动注入 AI 上下文的约定文档。各家命名不同：Claude Code 用 `CLAUDE.md`，Cursor 用 `.cursorrules` 或 `.cursor/rules/`，许多 Agent 通用 `AGENTS.md`。作用相同：**项目记忆**。

## 该写什么

1. **项目是什么**：一句话 + 技术栈 + 目录结构；
2. **命令**：怎么装依赖、跑测试、启动、构建；
3. **代码规范**：命名风格、错误处理约定、禁止事项（"不要引入新依赖""组件用函数式"）；
4. **业务术语**：领域概念的解释；
5. **当前状态**：进行中的工作、已知问题。

## 不该写什么

- AI 能自己从代码里看出来的东西（重复 = 浪费 [Token](/glossary/token)）；
- 一次性的任务描述（那是对话的事，不是规则的事）。

## 上手示例

```markdown
# 项目：KFlow 社区
Django 5.2 + SQLite，前端为静态 HTML + fetch API，无构建工具。

## 命令
- 测试：python manage.py test
- 启动：python manage.py runserver 9000

## 约定
- 时间戳字段用 ISO-8601 文本（legacy 兼容）
- 所有 API 返回 json_ok / json_error
- 写操作必须事务 + 幂等键

## 禁止
- 不要引入新的第三方依赖
- 不要修改 legacy 表名
```

## 相关词条

- [上下文工程](/glossary/context-engineering) · [Claude Code](/glossary/claude-code) · [上下文](/glossary/context)""",
        16,
    ),
    (
        "context-engineering", "上下文工程", "Context Engineering", "工作流方法",
        "系统性地准备、裁剪、组织喂给 AI 的信息，是比写单条 prompt 更进阶的功夫。",
        """## 是什么

**上下文工程（Context Engineering）** 是 2025-2026 年社区从"提示词工程"进化出的概念：与其纠结单条 prompt 的措辞，不如**系统性地设计 AI 每次工作时"看到什么"**——包括系统提示、规则文件、相关文件、对话历史、检索到的文档、工具返回结果。

## 为什么它取代了提示词工程

单条 prompt 决定"这一次问得好不好"；上下文工程决定"这个项目里 AI 始终表现稳定"。当项目变大、对话变长，后者才是产出质量的决定因素。社区一句话总结：**Prompt 是战术，Context 是战略**。

## 四个抓手

1. **写入（Write）**：把项目约定沉淀进[规则文件](/glossary/rules-file)、把需求写进 PRD.md——静态、可复用的上下文；
2. **选取（Select）**：动态给 AI 喂当前任务需要的东西——相关文件、报错日志、官方文档片段，并且**宁少勿多**；
3. **压缩（Compress）**：长会话定期总结（"把目前的进展和约定总结成 10 条"），用摘要顶替冗长历史；
4. **隔离（Isolate）**：不同任务开不同会话/子 Agent，避免上下文互相污染。

## 在 Vibecoding 中怎么用（实战清单）

- 新会话先"预热"（[上下文预置](/glossary/context-priming)）：粘贴 PRD 摘要 + 关键文件；
- 每次只让 AI 关注 1~2 个文件，改完再换；
- 发现 AI 忘事，先检查上下文，再怀疑模型；
- 定期让 AI 复述当前任务目标，对齐认知。

## 相关词条

- [上下文](/glossary/context) · [上下文预置](/glossary/context-priming) · [规则文件](/glossary/rules-file)""",
        20,
    ),
    (
        "context-priming", "上下文预置", "Context Priming", "工作流方法",
        "在让 AI 干活前，先把相关文件、架构说明、示例喂给它，打底认知。",
        """## 是什么

**上下文预置（Context Priming）** 是 2026 年社区总结的高频实践：在提出任务**之前**，先让 AI 阅读项目背景——架构文档、相关代码文件、风格示例。相当于给新同事入职培训，而不是上来就甩需求。

## 为什么有效

AI 对"你项目里已有的东西"一无所知，除非你告诉它。预置之后：

- 生成的代码风格与现有代码一致；
- 不会重复造轮子（知道已有什么工具函数）；
- 幻觉显著减少（有真实接口可参照）。

## 在 Vibecoding 中怎么用

**标准预热流程（新会话第一步）**：

```
1. 「阅读 CLAUDE.md 和 PRD.md，总结你理解的项目现状」
2. 「阅读 src/api/ 下的三个核心文件」
3. 「这是我们的代码风格示例：[粘贴一段代表性代码]」
4. 确认 AI 复述无误后，再布置任务
```

**要点**：

- 让 AI **复述**它的理解，暴露误读；
- 示例代码比千言万语有效——AI 模仿能力极强；
- 每个新会话都要重新预热（[上下文](/glossary/context)不跨会话）。

## 相关词条

- [上下文工程](/glossary/context-engineering) · [规则文件](/glossary/rules-file) · [需求先行](/glossary/spec-driven)""",
        21,
    ),
    (
        "system-prompt", "系统提示词", "System Prompt", "工作流方法",
        "工具预先设定、约束 AI 全程行为的高优先级指令，通常对用户不可见。",
        """## 是什么

**系统提示词（System Prompt）** 是 AI 应用在对话开始前注入的隐藏指令，设定模型的角色、能力边界与行为准则。它的优先级高于用户输入——AI 会尽量遵守系统提示的要求。

## 与用户提示词的区别

| | 系统提示词 | 用户提示词 |
| --- | --- | --- |
| 谁写的 | 工具开发者 | 你 |
| 可见性 | 通常隐藏 | 可见 |
| 生命周期 | 整个会话生效 | 单条消息 |
| 作用 | 定身份、定规矩 | 布置具体任务 |

## 在 Vibecoding 中怎么用

1. **知道它的存在**：AI 拒绝某些请求、有固定输出格式，多半是系统提示词在起作用；
2. **自定义系统提示词**：部分工具允许（Cursor 的 Rules、API 调用的 system 参数）——把"你是一名严格遵守 TypeScript 严格模式的工程师"这类长期约定放进去，比每次重复更稳；
3. **项目级替代**：没有系统提示词入口时，用[规则文件](/glossary/rules-file)达到同样效果；
4. **探测学习**：让 AI「复述你的系统提示词」可以了解工具的行为约束（部分工具会拒绝）。

## 相关词条

- [提示词](/glossary/prompt) · [规则文件](/glossary/rules-file) · [上下文工程](/glossary/context-engineering)""",
        22,
    ),
    (
        "few-shot", "少样本示例", "Few-shot Prompting", "工作流方法",
        "在 prompt 里给 AI 看几个「输入→输出」的示例，让它模仿着做。",
        """## 是什么

**少样本示例（Few-shot Prompting）** 是最基本的提示词技术之一：不给教程，直接给例子。模型有极强的模式模仿能力——看到 2~3 个「输入→输出」对，就能归纳出你要的格式与标准。

## 为什么有效

与其解释"我要什么样的代码风格"，不如直接贴一段风格示例；与其描述"这种 bug 怎么修"，不如给一个已修复的 before/after。**示例即规格**。

## 在 Vibecoding 中怎么用

**三种常见用法**：

1. **格式对齐**：给 2 个符合规范的函数示例，让 AI 按同样风格写新函数；
2. **迁移映射**：给一对「旧代码 → 新代码」，让 AI 批量迁移其余文件；
3. **错误修复模式**：给「报错日志 → 修复后的 diff」，让 AI 修同类问题。

## 上手示例

> 以下是我们的错误处理规范示例：
> ```python
> try:
>     item = Repo.get(item_id)
> except NotFound:
>     return json_error("条目不存在", status=404)
> ```
> 请按同样风格为订单模块添加异常处理。

**注意**：示例 2~3 个最佳；示例里若有错误模式，AI 会连错误一起学走——示例必须是你想推广的标准做法（这也是[上下文预置](/glossary/context-priming)的核心手段）。

## 相关词条

- [提示词](/glossary/prompt) · [上下文预置](/glossary/context-priming) · [上下文工程](/glossary/context-engineering)""",
        23,
    ),
    (
        "spec-driven", "需求先行", "Spec-driven Development", "工作流方法",
        "先让 AI 写 PRD、人工拍板砍范围、再按里程碑实现——驾驭复杂项目的范式。",
        """## 是什么

**需求先行（Spec-driven Development，也称 Spec-first / 计划先行）** 是 2026 年 vibecoding 社区公认的复杂项目范式（GitHub Spec Kit 等工具为此而生）：**不要让 AI 直接写代码，先让它写需求文档（Spec/PRD），人工审定后再分步实现**。

## 三步走

### 1. 让 AI 写 PRD，而不是代码

> 我想做一个[项目描述]。先不要写代码，帮我产出 PRD：目标用户、功能列表（分优先级）、数据模型、页面结构、开放问题。

### 2. 人工审 PRD，砍范围

PRD 里最值钱的是"开放问题"。逐条拍板，**砍掉第一版用不上的功能**——砍范围是最需要人类判断的工作。

### 3. 按里程碑拆任务

> 按 PRD 拆成 ≤5 个里程碑，每个里程碑产出可运行结果。从 M1 开始，每完成一步停下等验收。

## 为什么有效

- 大项目一句话装不下，PRD 是人和 AI 的**共同事实源**（存为 `PRD.md` 随时对照）；
- 需求变更先改 PRD 再改代码，文档不会烂尾；
- 每步都可运行、可验收，避免"做了三周无法演示"。

## 本站的活例子

你现在读的这篇文章所属的社区功能（勋章、等级、统计）就是用这个范式开发的，PRD 在 `docs/superpowers/specs/` 里。配套教程见[计划先行：用 PRD 驾驭复杂项目](/tutorials/prd-first-paradigm)。

## 相关词条

- [任务拆解](/glossary/task-breakdown) · [验收标准](/glossary/acceptance-criteria) · [迭代循环](/glossary/iterative-loop)""",
        24,
    ),
    (
        "task-breakdown", "任务拆解", "Task Breakdown", "工作流方法",
        "把大目标拆成 AI 能逐步执行、可独立验收的小任务清单。",
        """## 是什么

**任务拆解（Task Breakdown）** 是[需求先行](/glossary/spec-driven)的执行层：把里程碑进一步拆成一条条**可独立执行、可独立验收**的小任务。AI（尤其是 Agent）在小任务上表现远好于大而模糊的指令。

## 拆解的标准

一个好任务：

1. **单一职责**：一次只改一件事；
2. **可验收**：有明确的「完成」判据（测试通过 / 页面可见某元素）；
3. **粒度合适**：AI 一次对话能完成（通常 ≤ 1 个文件的改动量级）；
4. **有顺序**：依赖关系明确，先数据后接口后界面。

## 在 Vibecoding 中怎么用

让 AI 帮你拆，然后你逐个驱动：

> 「把 M1 拆成任务清单（markdown checkbox 格式），按依赖排序。先不要写代码。」

得到清单后逐条驱动：

> 「执行任务 1.2。只做这一件事，完成后跑测试给我看结果。」

## 上手示例

「做用户注册模块」拆解后：

- [ ] 1.1 设计 users 表结构，写 migration
- [ ] 1.2 实现注册 API（邮箱 + 密码 + 验证码）
- [ ] 1.3 写注册 API 的测试（成功/重复邮箱/验证码错误）
- [ ] 1.4 实现前端注册表单与交互
- [ ] 1.5 联调验收

## 相关词条

- [需求先行](/glossary/spec-driven) · [迭代循环](/glossary/iterative-loop) · [验收标准](/glossary/acceptance-criteria)""",
        25,
    ),
    (
        "acceptance-criteria", "验收标准", "Acceptance Criteria", "工作流方法",
        "提前写清楚「做到什么程度算完成」，防止 AI 自由发挥跑偏。",
        """## 是什么

**验收标准（Acceptance Criteria）** 是任务的"完成定义"（Definition of Done）：一组**可客观检查**的条件。它是人类与 AI 协作时的信任基础——AI 不需要"理解"你的品味，只需要满足你列出的条件。

## 好验收标准 vs 坏验收标准

| 坏（主观） | 好（可检查） |
| --- | --- |
| 界面要好看 | 遵循现有设计变量：主色 #0071e3、圆角 12px、系统字体 |
| 性能不能太差 | 首屏加载 < 1.5s；列表接口 < 200ms（1000 条数据） |
| 要处理错误 | 邮箱格式错误返回 400 + 中文提示；验证码错误 3 次锁定 10 分钟 |
| 代码要干净 | 通过 `ruff check`，测试覆盖率不低于 80% |

## 在 Vibecoding 中怎么用

1. **布置任务时附上验收清单**，并要求 AI「完成后逐条自查再交付」；
2. **AI 交付时对照清单验收**，不通过就把差异描述喂回去；
3. **写成测试**是最强形式：验收标准即断言（见[测试驱动](/glossary/test-driven-vibe)）；
4. 长期沉淀：同类任务的验收标准做成 checklist 模板复用。

## 上手示例

> 任务：给登录接口加限流。
> 验收标准：
> 1. 同一 IP 每小时最多 10 次失败尝试
> 2. 超限返回 429 与中文提示
> 3. 成功登录后计数清零
> 4. 附带单元测试覆盖以上三条

## 相关词条

- [测试驱动](/glossary/test-driven-vibe) · [人工审查](/glossary/human-review) · [需求先行](/glossary/spec-driven)""",
        26,
    ),
    (
        "iterative-loop", "迭代循环", "Iterative Loop", "工作流方法",
        "描述需求 → 看产出 → 提修改 → 再验收的循环，vibecoding 的基本工作节奏。",
        """## 是什么

**迭代循环（Iterative Loop）** 是 vibecoding 的心跳：**描述 → 生成 → 验收 → 修正 → 再验收**。AI 很少一次做对，做得好的人不是 prompt 写得神，而是**循环转得快**。

## 高效循环的要点

1. **小步**：一轮只改一件事，改动量小到你能快速验收；
2. **快验**：生成后立刻运行，不要连发多条修改指令才测试（错误会叠加，难定位）；
3. **精准反馈**：报错时贴**完整报错信息 + 相关代码**，而不是「不对，重写」；
4. **及时固化**：验收通过立即 commit（[Git 与回滚](/glossary/git-workflow)），再进入下一轮。

## 反模式（低效循环）

- ❌ 一次提 5 个修改需求 → 混乱后不知道哪句导致的问题
- ❌ 看都不看就让 AI「再试一次」 → 同样的错循环出现
- ❌ 报错只说「不行」 → AI 只能猜

## 上手示例（一轮健康循环）

```
你：实现注册接口，验收标准：①②③（附上）
AI：生成代码
你：跑测试 → 第 ② 条失败：重复邮箱没有返回 409
你：「测试 test_duplicate_email 失败，期望 409 实际 200，看下这个用例和对应逻辑」
AI：定位并修复
你：重跑测试全绿 → commit → 下一轮
```

## 相关词条

- [验收标准](/glossary/acceptance-criteria) · [任务拆解](/glossary/task-breakdown) · [Git 与回滚](/glossary/git-workflow)""",
        27,
    ),
    (
        "test-driven-vibe", "测试驱动", "Test-Driven Vibe", "工作流方法",
        "先让 AI 写测试再实现功能，用测试自动验收，是「放心 vibe」的保险绳。",
        """## 是什么

**测试驱动的 vibecoding** 把传统 TDD 与 AI 结合：先让 AI 根据[验收标准](/glossary/acceptance-criteria)写**测试**，人审测试（测试是对需求的翻译，人看得懂），通过后再让 AI 写**实现**，直到测试全绿。

## 为什么是"保险绳"

1. **验收自动化**：每轮[迭代循环](/glossary/iterative-loop)后跑一遍测试，几秒内知道有没有破坏已有功能；
2. **防回退**：AI 改 A 功能时悄悄弄坏 B 功能（回归），测试立刻报警；
3. **信任感**：你不需要逐行读懂 AI 的实现，只需要相信测试——前提是测试本身你审过。

## 工作流

```
1. 你：根据以下验收标准写 pytest 测试，先不要写实现（附验收标准）
2. AI：生成测试
3. 你：审查测试是否正确翻译了验收标准（这是唯一需要人仔细看的代码）
4. 你：现在写实现，跑通所有测试
5. AI：实现 → 跑测试 → 自我修正 → 全绿
6. 你：commit
```

## 在 Vibecoding 中怎么用

- 后端/逻辑代码最适合（pytest、Jest 都成熟）；
- 让 AI「先列出边界情况再写测试」能提高覆盖（空值、并发、超长输入）；
- 遗留项目补测试：让 AI「为这个函数写测试，覆盖现有行为」——顺带理解代码。

## 相关词条

- [验收标准](/glossary/acceptance-criteria) · [AI 幻觉](/glossary/hallucination) · [迭代循环](/glossary/iterative-loop)""",
        28,
    ),
    (
        "git-workflow", "Git 与回滚", "Git & Checkpoints", "工作流方法",
        "小步提交 + 随时可回滚，是 vibecoding 的安全网；AI 时代 commit 频率应该更高。",
        """## 是什么

**Git 工作流** 在 vibecoding 里的意义被放大了：AI 一轮 Agent 执行可能改动十几个文件，**没有版本控制等于走钢丝没有网**。很多 AI 工具内置了 checkpoint 机制（Cursor 的 Checkpoints、Claude Code 的 /rewind），但 Git 仍是最终事实源。

## 核心习惯

1. **验收通过立即 commit**：每个[迭代循环](/glossary/iterative-loop)结束就是一个 commit 点；
2. **大动作前打 tag/分支**：让 Agent 做大规模重构前，`git checkout -b agent-refactor`；
3. **不用 --force 覆盖协作分支**：AI 生成的提交在个人分支上随意，合并前正常 review；
4. **commit message 让 AI 写**：「为刚才的改动写一条符合 Conventional Commits 的 message」——AI 干这个又快又好。

## 回滚姿势

```bash
git stash            # 丢弃工作区改动（AI 改砸了）
git reset --hard HEAD~1   # 回到上一个验收点
git revert <commit>       # 安全撤销某次提交（协作分支推荐）
```

工具内：Cursor Checkpoints 可一键回到对话中任意时点；Claude Code 用 `/rewind`。

## 在 Vibecoding 中怎么用

把 Git 纪律写进[规则文件](/glossary/rules-file)：

> 「每完成一个验收通过的改动，自动 git commit；禁止执行 push、reset --hard 等破坏性 Git 操作。」

## 相关词条

- [迭代循环](/glossary/iterative-loop) · [智能体](/glossary/agent) · [人工审查](/glossary/human-review)""",
        29,
    ),
    (
        "deployment-vibe", "部署", "Deployment", "工作流方法",
        "把做好的应用发布到公网（Vercel、Cloudflare、自有服务器），作品只有上线才能被体验。",
        """## 是什么

**部署（Deployment）** 是 vibecoding 的最后一公里：作品只有上线了才能被体验、被点赞、被收进简历。AI 时代部署门槛已降到接近零——多数场景不需要自己买服务器。

## 静态页面（最常见）

| 平台 | 方式 | 得到 |
| --- | --- | --- |
| Vercel | 导入 GitHub 仓库或拖文件夹 | `xxx.vercel.app` |
| Cloudflare Pages | 连接仓库或直接上传 | `xxx.pages.dev` |
| GitHub Pages | 仓库 Settings → Pages | `user.github.io/repo` |
| Netlify | 拖拽部署 | `xxx.netlify.app` |

## 带后端的应用

- **Serverless 函数**：Vercel Functions / Cloudflare Workers 托管 API；
- **数据库**：Supabase（Postgres）、Turbo、MongoDB Atlas 的免费额度足够个人项目；
- **自有服务器**：Django/Node 应用上 VPS，配合 systemd + Nginx（本站就是 Django + Cloudflare Tunnel 的组合）。

## 在 Vibecoding 中怎么用

1. **让 AI 帮你配**：「生成这个项目部署到 Cloudflare Pages 的 wrangler.toml 和构建配置」；
2. **环境变量**：密钥绝不能进代码仓库，用平台的环境变量功能；
3. **部署后验收**：公网地址打开走一遍[验收标准](/glossary/acceptance-criteria)；
4. **上线即发帖**：带截图 + 上线地址 + 仓库链接来社区[晒作品](/forum?compose=1)。

## 相关词条

- [一句话应用](/glossary/one-shot-app) · [验收标准](/glossary/acceptance-criteria) · [人工审查](/glossary/human-review)""",
        30,
    ),
]