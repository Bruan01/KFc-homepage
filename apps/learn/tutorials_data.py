# pyright: reportMissingImports=false
"""详细教程数据（seed 用）。字段：slug, title, summary, kind, difficulty, series, sort, tags, content_md"""

TUTORIALS = [
    {
        "slug": "first-web-game-in-10-minutes",
        "title": "10 分钟做出你的第一个网页小游戏",
        "summary": "从一条 prompt 开始，用 AI 生成一个可以直接玩的小游戏，掌握「描述→验收→迭代」的最小闭环。",
        "kind": "tutorial",
        "difficulty": "beginner",
        "series": "手把手入门",
        "sort_order": 1,
        "tags": "入门,游戏,一句话应用",
        "content_md": """# 10 分钟做出你的第一个网页小游戏

vibecoding 最好的入门方式，就是做出一个能玩的东西。这个教程不需要你会写代码，只需要会**描述**和**验收**。

## 开始前的三个概念

- [提示词](/glossary/prompt)：你发给 AI 的指令，质量决定产出
- [验收标准](/glossary/acceptance-criteria)：提前写清楚"做到什么程度算完成"
- [迭代循环](/glossary/iterative-loop)：描述 → 生成 → 验收 → 修正的基本节奏

## 第 1 步：说清楚你要什么（2 分钟）

打开任意 AI 编程工具（Cursor / Claude Code 都可以），输入：

> 帮我做一个网页版贪吃蛇小游戏：方向键控制、吃到食物变长、撞墙或撞到自己游戏结束、显示得分和最高分（存 localStorage）。全部代码放在一个 index.html 文件里，双击就能玩。

这个 prompt 有三个关键点：**玩法规则**、**失败条件**、**验收方式**（双击就能玩）。

## 第 2 步：跑起来，亲自验收（3 分钟）

把 `index.html` 保存到本地双击打开。逐条验收：

- 方向键能动吗？
- 吃到食物加不加分？
- 撞墙游戏结束吗？
- 刷新后最高分还在吗？

**发现哪条不满足，就只提哪条。** 不要一次性提一堆问题。

## 第 3 步：迭代修改（5 分钟）

用小步反馈修正：

> 蛇的速度会随分数逐渐加快，每吃 5 个食物加快一档。其他不要动。

注意"其他不要动"——限制 AI 的改动范围是小步迭代的关键技巧。

## 第 4 步：部署上线 + 来社区发帖

用 [Vercel / Cloudflare Pages](/glossary/deployment-vibe) 把作品发布到公网，然后带截图和上线地址来社区[发帖晒作品](/forum?compose=1)。

## 常见坑

- prompt 里不写验收标准，AI 自由发挥跑偏
- 一次提太多需求，出错后无法定位是哪句指令的问题
- 忘记让 AI 输出单文件，初学者被工程结构劝退

## 下一步

- 学会把 prompt 写得更结构化：[一句话应用](/tutorials/one-shot-app-start)
- 项目变大后：[计划先行范式](/tutorials/prd-first-paradigm)""",
    },
    {
        "slug": "one-shot-app-start",
        "title": "一句话应用：从想法到可用产品",
        "summary": "一句话应用的写法模板：角色 + 目标 + 约束 + 验收，把模糊想法变成 AI 能精确执行的指令。",
        "kind": "tutorial",
        "difficulty": "beginner",
        "series": "手把手入门",
        "sort_order": 2,
        "tags": "范式,prompt,入门",
        "content_md": """# 一句话应用：从想法到可用产品

"一句话应用"是 vibecoding 最经典的玩法：一条 prompt 生成一个完整的小工具。但"一句话"不等于"随便说"——**好 prompt 有固定结构**。

## 四段式 prompt 模板

1. **角色**：你是一名资深前端工程师
2. **目标**：做一个 [具体功能] 的网页应用（功能点逐条列出）
3. **约束**：单文件、无外部依赖、移动端可用、深色风格
4. **验收**：打开即可用；[列举 2~3 条具体可检查的行为]

## 完整示例

> 你是一名资深前端工程师。做一个 Markdown 待办清单：左侧输入区支持标准 Markdown 列表语法，右侧实时渲染成带勾选框的清单，勾选状态自动保存到 localStorage。约束：单个 HTML 文件、无构建工具、手机上也能用。验收：粘贴列表立刻渲染；刷新后勾选状态还在；无控制台报错。

## 为什么有效

- **角色**锚定代码质量的基准线
- **约束**收窄自由度，大幅减少[幻觉](/glossary/hallucination)
- **验收标准**让"做完了"可以被客观检查——这是人机协作的信任基础

## 进阶技巧

1. **给示例**：在 prompt 里贴一段你喜欢的 UI 风格代码（[少样本示例](/glossary/few-shot)），AI 会模仿
2. **反面清单**：「不要使用 alert」「不要引入外部 CDN」
3. **数据结构先行**：「用这个结构存储数据：[{id, text, done}]」能显著减少后续返工

## 常见坑与解法

| 坑 | 解法 |
| --- | --- |
| 功能太多一次说不清 | 拆成两轮：先核心功能，验收后再加 |
| AI 用了你不会的技术栈 | 约束里明确「只用 HTML/CSS/JS，不用框架」 |
| 生成后小问题不断 | 进入小步[迭代循环](/glossary/iterative-loop)，一次只修一个 |

## 下一步

- 工具还没选好？看[AI 编程工具选型指南](/tutorials/choose-ai-coding-tool)
- 做完记得[部署上线](/tutorials/deploy-and-share)，来社区发帖""",
    },
    {
        "slug": "choose-ai-coding-tool",
        "title": "2026 AI 编程工具选型指南",
        "summary": "Cursor、Claude Code、Copilot、Windsurf、Replit Agent、Cline 怎么选？按你的阶段与场景对号入座。",
        "kind": "tutorial",
        "difficulty": "beginner",
        "series": "工具与上下文",
        "sort_order": 3,
        "tags": "工具,Cursor,Claude Code,选型",
        "content_md": """# 2026 AI 编程工具选型指南

工具一年一个样，但**选型逻辑是稳定的**：按你的阶段和使用场景对号入座。

## 主流工具一览

| 工具 | 形态 | 强项 | 适合谁 |
| --- | --- | --- | --- |
| **Cursor** | AI 原生 IDE | 仓库感知、Tab 补全、Agent 模式 | 日常开发主力，写码体验最顺 |
| **Claude Code** | 终端智能体 | 自主多步执行、大型重构、MCP 生态 | 给目标就干活的重度用户 |
| **GitHub Copilot** | IDE 插件 | 补全成熟、企业普及、多 IDE 支持 | 已在 VS Code/JetBrains 工作的团队 |
| **Windsurf** | AI 原生 IDE | Agent 流程顺滑、上手快 | 喜欢 IDE 内全自动的人 |
| **Replit Agent / Lovable / Bolt** | 云端托管 | 从想法到部署一条龙，零环境 | 零基础快速出原型 |
| **Cline / Roo Code** | VS Code 开源插件 | 自选模型、可控成本 | 成本敏感、想用国产/本地模型 |

## 按阶段选

### 纯新手（还没写过代码）

从**云端托管型**开始（Replit Agent / Lovable）：浏览器里描述 → 直接得到可部署的应用，完全跳过环境搭建。目标是先建立"我能做出东西"的信心。

### 有一定基础（能看懂代码、会验收）

上 **Cursor** 或 **Windsurf**：IDE 形态让你既能 vibe 又能精确控制。配合 [规则文件](/glossary/rules-file)管理项目约定。

### 进阶玩家（要驾驭大项目）

**Cursor + Claude Code 组合**是 2026 年社区最常见的搭配：Cursor 日常写码，Claude Code 干重活（按 PRD 整模块实现、跨文件重构）。重度使用 [MCP](/glossary/mcp) 接数据库和 GitHub。

## 不变的选型原则

1. **工具会变，方法论不变**：[上下文工程](/glossary/context-engineering)、小步验收、[Git 与回滚](/glossary/git-workflow)是跨工具的通用能力
2. **先用透一款再横向对比**：同时开五个工具不如把一个用到深处
3. **关注社区实测**：本站"晒作品"和"求点评"分类常有同题多工具对比帖，比广告可信

## 下一步

选好工具后，第一件事是学会[上下文工程实战](/tutorials/context-engineering-practice)。""",
    },
    {
        "slug": "context-engineering-practice",
        "title": "上下文工程实战：让 AI 始终在线",
        "summary": "写、选、压缩、隔离四个抓手，系统性管理 AI 每次工作时的上下文——2026 年 vibecoding 的分水岭技能。",
        "kind": "paradigm",
        "difficulty": "intermediate",
        "series": "工具与上下文",
        "sort_order": 5,
        "tags": "范式,上下文工程,进阶",
        "content_md": """# 上下文工程实战：让 AI 始终在线

2026 年社区最重要的共识：**Prompt 是战术，[上下文](/glossary/context)是战略**。单条 prompt 决定这一次问得好不好；上下文工程决定你的项目里 AI 始终表现稳定。

## 四个抓手

### 1. 写入（Write）：把约定沉淀成静态上下文

项目里长期有效的东西，写一次就不要再口头重复：

- [规则文件](/glossary/rules-file)（CLAUDE.md / .cursorrules）：技术栈、命令、代码规范、禁止事项
- `PRD.md`：需求文档（见[需求先行](/glossary/spec-driven)）
- `NOTES.md`：关键决策记录（"我们为什么选 SQLite"）

### 2. 选取（Select）：按需喂料，宁少勿多

每次任务只喂**当前需要的**：

- 改哪个模块，就只给那个模块的文件
- 报错时给**完整报错 + 相关代码**，不是整个日志
- 相关性不强的文件不要给——[上下文窗口](/glossary/context-window)内注意力会被稀释

### 3. 压缩（Compress）：长会话定期总结

会话超过半小时，主动做一次：

> 「把目前的进展、已达成的约定、待办事项总结成 10 条，我确认后作为后续对话的基础。」

用摘要顶替冗长历史，既省 [Token](/glossary/token) 又防止 AI "忘事"。

### 4. 隔离（Isolate）：任务分开，互不污染

- 一个功能一个会话，做完就关
- 无关任务混在一个对话里，AI 会被之前的细节带偏

## 实战：新会话标准开场（预置流程）

```
1.「阅读 CLAUDE.md 和 PRD.md，用 5 条总结项目现状」
2.「阅读 src/api/auth.py，这是我们要改的模块」
3.「这是项目的错误处理风格示例：[粘贴代表代码]」
4.「复述你理解的任务目标」← 确认对齐后再布置任务
```

这个流程叫[上下文预置](/glossary/context-priming)，能显著降低幻觉。

## 自检清单

- [ ] 规则文件存在且最近更新过？
- [ ] 本次任务只喂了相关文件？
- [ ] 会话超过 30 分钟做过总结？
- [ ] 布置任务前让 AI 复述过理解？

## 相关词条

[上下文工程](/glossary/context-engineering) · [上下文预置](/glossary/context-priming) · [规则文件](/glossary/rules-file)""",
    },
    {
        "slug": "rules-file-guide",
        "title": "规则文件写作指南：CLAUDE.md 与 .cursorrules",
        "summary": "规则文件是项目的 AI 记忆。写什么、不写什么、怎么维护，一篇讲透。",
        "kind": "tutorial",
        "difficulty": "intermediate",
        "series": "工具与上下文",
        "sort_order": 6,
        "tags": "工具,规则文件,CLAUDE.md,进阶",
        "content_md": """# 规则文件写作指南

**规则文件**（Claude Code 的 `CLAUDE.md`、Cursor 的 `.cursorrules`、通用的 `AGENTS.md`）是放在项目里、每次对话自动注入 AI 的约定文档。它就是**项目的 AI 记忆**。

## 为什么需要

没有规则文件：每次新会话你都要重复「我们用 Django」「API 返回格式是 xxx」「不要引入新依赖」——说三次之后 AI 还是会忘（[上下文](/glossary/context)不跨会话）。有了规则文件：约定自动生效，永不忘。

## 写什么（按优先级）

### 1. 项目一句话 + 技术栈（必写）

```markdown
# KFlow 社区
Django 5.2 + SQLite，前端为静态 HTML + fetch API，无构建工具。
```

### 2. 常用命令（必写）

```markdown
- 测试：python manage.py test
- 本地启动：python manage.py runserver 9000
- 备份：python manage.py backup_database
```

### 3. 代码规范（重要）

```markdown
- API 统一返回 json_ok / json_error
- 写操作必须 transaction.atomic + 幂等键
- 时间戳字段用 ISO-8601 文本（legacy 兼容约定）
```

### 4. 禁止事项（重要）

```markdown
- 不要引入新的第三方依赖
- 不要修改 legacy 表名
- 不要使用 print 调试，用 logger
```

### 5. 当前状态（可选，勤更新）

```markdown
- 进行中：勋章系统（docs/specs/gamification.md）
- 已知问题：排名接口在无数据源时会 500（已修复待验证）
```

## 不写什么

- AI 能从代码里看出来的东西（重复浪费 [Token](/glossary/token)）
- 一次性任务描述（那是对话的事）
- 超过 300 行的长文——规则文件越精炼，遵守率越高

## 维护习惯

- **每次验收通过的新约定，当场补进规则文件**（这是[上下文工程](/glossary/context-engineering)的"写入"环节）
- 每两周审一次：删掉过时的，合并重复的
- 让 AI 帮忙：「对比当前代码库与 CLAUDE.md，指出文档过时的地方」

## 相关词条

[规则文件](/glossary/rules-file) · [上下文工程](/glossary/context-engineering) · [Claude Code](/glossary/claude-code)""",
    },
    {
        "slug": "mcp-getting-started",
        "title": "MCP 入门：给你的 AI 接上外部世界",
        "summary": "MCP 是 AI 工具生态的 USB 接口。30 分钟接入第一个 MCP Server，让 AI 直接读你的数据库、操作 GitHub。",
        "kind": "tutorial",
        "difficulty": "intermediate",
        "series": "工具与上下文",
        "sort_order": 7,
        "tags": "工具,MCP,Claude Code,进阶",
        "content_md": """# MCP 入门：给你的 AI 接上外部世界

**[MCP](/glossary/mcp)（Model Context Protocol）** 是 Anthropic 开放的协议，已成为 AI 工具生态的"USB 接口"：实现一次 MCP Server，所有支持的客户端（Claude Code、Cursor、Cline）都能用。

## 为什么值得学

没有 MCP：让 AI 看 GitHub issue 要手动复制粘贴。有了 MCP：

> 「看一下 kfc-homepage 仓库最新的 5 个 issue，按优先级整理成清单」

AI 自己调用 GitHub 工具完成。**从"你搬运信息给 AI"变成"AI 自己取信息"**。

## 30 分钟接入第一个 Server

### 第 1 步：确认客户端支持

Claude Code / Cursor / Cline 等主流工具都已支持。以 Claude Code 为例。

### 第 2 步：添加 filesystem Server

```bash
claude mcp add filesystem -- npx -y @modelcontextprotocol/server-filesystem ~/projects
```

这行命令把 `~/projects` 目录以受控方式开放给 AI。

### 第 3 步：验证

新开会话，输入：

> 列出你可以使用的工具

应该能看到 read_file、write_file 等工具已就位。

### 第 4 步：实战

> 「读取 myapp/README.md，总结项目结构，然后把安装命令更新为 pnpm」

AI 会读写真实文件——注意 **write 权限的边界**：只开放必要的目录。

## 常用 Server 推荐

| Server | 场景 | 命令示例 |
| --- | --- | --- |
| filesystem | 本地文件受控读写 | `npx @modelcontextprotocol/server-filesystem <目录>` |
| github | issue/PR/仓库操作 | `npx @modelcontextprotocol/server-github`（需 token） |
| postgres | 查询数据库结构 | `npx @modelcontextprotocol/server-postgres <连接串>` |
| playwright | 浏览器自动化、截图验证 UI | 见各客户端文档 |

## 安全须知

1. **最小授权**：filesystem 只开项目目录，不要开根目录
2. **只读优先**：数据库类 Server 优先用只读账号
3. **Token 管理**：GitHub token 用细权限（只读仓库内容即可起步）
4. 工具越多，[上下文](/glossary/context)越吵——只挂当前需要的

## 下一步

把常用 Server 配置写进团队文档，配合[规则文件](/glossary/rules-file)让整个团队的 AI 都有同样的"手"。""",
    },
    {
        "slug": "prd-first-paradigm",
        "title": "计划先行：用 PRD 驾驭复杂项目",
        "summary": "当一句话装不下你的想法时，先让 AI 帮你写 PRD，人工拍板砍范围，再按里程碑分步实现。",
        "kind": "paradigm",
        "difficulty": "intermediate",
        "series": "vibecoding 范式",
        "sort_order": 8,
        "tags": "范式,PRD,进阶",
        "content_md": """# 计划先行：用 PRD 驾驭复杂项目

项目一旦超过"一屏页面 + 一个功能"，一句话 prompt 就不够了。切换到**计划先行范式**（[需求先行](/glossary/spec-driven)）：先 PRD，再拆任务，后实现。

## 三步走

### 1. 让 AI 写 PRD，而不是代码

> 我想做一个[项目描述]。先不要写代码，帮我产出一份 PRD：目标用户、核心功能列表（分优先级）、数据模型、页面结构、开放问题。

### 2. 人工审 PRD，砍范围

PRD 里最值钱的是"开放问题"部分。逐条拍板，**砍掉第一版用不上的功能**——砍范围是 vibecoding 里最人类的工作。

### 3. 按里程碑拆任务执行

> 按 PRD 把第一版拆成 5 个以内的里程碑，每个里程碑产出可运行的结果。我们从 M1 开始，每完成一步停下来等我验收。

每个里程碑内部再用[任务拆解](/glossary/task-breakdown)拆成小任务，逐条驱动。

## 关键技巧

1. **每步可运行**：每个里程碑结束都要求"可运行、可验收"，避免长期看不到成品
2. **PRD 是唯一事实源**：存成项目里的 `PRD.md`，新会话先读它（[上下文预置](/glossary/context-priming)）
3. **变更先改 PRD**：需求变化时先更新文档再改代码，文档永不烂尾
4. **开放问题清单**：AI 列的开放问题是你拍板的抓手，逐条决策

## 一个真实的例子

本站的游戏化体系（等级、勋章、统计）就是用这个范式做的：PRD 先行 → 管理员砍范围 → 4 个里程碑分步交付。PRD 全文在本站仓库 `docs/superpowers/specs/` 目录。

## 什么时候该用这个范式

- 功能点 > 3 个
- 涉及数据模型设计
- 预计开发 > 1 天
- 多人协作

不满足以上任何一条？[一句话应用](/tutorials/one-shot-app-start)足够了。

## 下一步

- 学会拆任务：[任务拆解](/glossary/task-breakdown)词条
- 给任务装上保险绳：[调试与验收](/tutorials/debug-and-accept)""",
    },
    {
        "slug": "debug-and-accept",
        "title": "调试与验收：AI 写错了怎么办",
        "summary": "AI 写错代码是常态不是例外。读 diff、贴完整报错、测试兜底、及时回滚——四个动作让错误无处可藏。",
        "kind": "tutorial",
        "difficulty": "intermediate",
        "series": "vibecoding 范式",
        "sort_order": 9,
        "tags": "范式,调试,验收,测试",
        "content_md": """# 调试与验收：AI 写错了怎么办

AI 写错代码是**常态**，不是例外。做得好的人不是 AI 从不出错，而是有一套高效的纠错流程。

## 错误处理的四个动作

### 1. 读 diff，而不是只看结果

AI 交付时先看**改了什么**（diff 视图），再看效果。发现改动范围超出你的预期（比如让你改按钮它重构了整个组件），立刻停下追问。

### 2. 贴完整报错，给足上下文

报错时最忌说"不对，重写"。正确姿势：

> 测试 `test_duplicate_email` 失败：
> ```
> AssertionError: 409 != 200
> ```
> 期望重复邮箱返回 409，实际返回了 200。请检查 create_user 的查重逻辑。

**完整报错 + 相关代码 + 期望行为**，AI 一次就能修对。这比"重写"省 3 轮对话。

### 3. 测试兜底

最强的验收是[测试驱动](/glossary/test-driven-vibe)：让 AI 先写测试（你审测试），再写实现。之后每一轮迭代跑一遍测试，**改 A 坏 B 的回归问题无处可藏**。

没有测试的快速验收清单：

- [ ] 主流程手动走一遍
- [ ] 空数据 / 超长输入 / 断网试试
- [ ] 控制台无报错
- [ ] 手机尺寸看一眼

### 4. 及时回滚

改砸了不要恋战：验收通过的代码每步都 commit 过（[Git 与回滚](/glossary/git-workflow)），直接回到上一个好状态，重新描述任务。**回滚是零成本的，带着 bug 继续叠改动才是高成本的。**

## 一个真实的调试循环

```
你：实现登录接口（附验收标准）
AI：生成代码
你：跑测试 → 限流测试失败（期望 10 次/时，实际不限）
你：「限流测试失败。看 test_rate_limit 用例，检查 rate_limiter 装饰器是否生效」
AI：发现装饰器写在了错误的视图上 → 修复
你：测试全绿 → commit → 下一轮
```

## 让 AI 自查（进阶）

交付前让 AI 换个角色自审，经常能抓出问题：

> 「以安全工程师的视角审查你刚才写的代码，列出潜在风险。」

> 「逐条对照验收标准自查，输出每条的通过情况与证据。」

## 相关词条

[人工审查](/glossary/human-review) · [AI 幻觉](/glossary/hallucination) · [验收标准](/glossary/acceptance-criteria)""",
    },
    {
        "slug": "deploy-and-share",
        "title": "把作品部署上线，然后来发帖",
        "summary": "三个免费托管渠道的上线路径，以及发作品帖的三件套规范。",
        "kind": "tutorial",
        "difficulty": "beginner",
        "series": "手把手入门",
        "sort_order": 10,
        "tags": "部署,发帖,入门",
        "content_md": """# 把作品部署上线，然后来发帖

作品只有上线了才能被体验、被点赞。这里是最快的三个免费渠道。

## 纯静态页面（最常见）

**Vercel**：注册后 New Project → 导入 GitHub 仓库 → 自动构建，1 分钟拿到 `xxx.vercel.app`。

**Cloudflare Pages**：控制台 Create project → 连接仓库或直接上传文件夹 → 得到 `xxx.pages.dev`。

**GitHub Pages**：仓库 Settings → Pages → 选择分支 → 得到 `username.github.io/repo`。

## 带后端的应用

- **Serverless**：Vercel Functions / Cloudflare Workers 托管 API
- **数据库**：Supabase（Postgres）、Turbo 免费额度够个人项目
- **自有服务器**：Django/Node 上 VPS + systemd + Nginx

让 AI 帮你写部署配置：「为这个项目生成部署到 Cloudflare Pages 所需的配置文件」。

## 发作品帖的三件套

1. **一段话介绍**：做了什么、解决什么问题、怎么 vibe 出来的
2. **截图**：1~9 张，第一张自动作为封面
3. **链接**：GitHub / Gitee 仓库 + 上线地址

上线地址会让你的帖子可信度翻倍——围观的人点进去就能玩，点赞和评论自然就来了。

## 环境变量安全

- 密钥绝不进代码仓库：用平台的环境变量功能
- 让 AI 自查：「检查这个项目有没有硬编码的密钥或 token」

## 上线即发帖

部署完成后，带三件套来[发作品帖](/forum?compose=1)。社区的热榜、勋章系统都在等着你的作品。

## 相关词条

[部署](/glossary/deployment-vibe) · [验收标准](/glossary/acceptance-criteria)""",
    },
]