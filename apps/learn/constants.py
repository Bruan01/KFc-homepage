# pyright: reportMissingImports=false
"""Constants shared by the Vibecoding electronic book APIs and seed data."""

BOOK_TITLE = "Vibecoding 开发者手册"
BOOK_SUBTITLE = "从灵感原型到可维护产品"
BOOK_EDITION = "2026.09"
BOOK_DESCRIPTION = "一套覆盖需求、智能体协作、全栈实现、质量交付与持续演进的实战方法。"
BOOK_PAGE_SEPARATOR = "\n<!-- page -->\n"

BOOK_PARTS = (
    {
        "number": 1,
        "title": "第一卷 · 思维与需求",
        "summary": "先判断问题、写清结果，再让 AI 动手。",
    },
    {
        "number": 2,
        "title": "第二卷 · 工具与上下文",
        "summary": "把模型、规则、工具与反馈环境组织成可靠工作台。",
    },
    {
        "number": 3,
        "title": "第三卷 · 工程实现",
        "summary": "用智能体完成前端、后端与可演进架构。",
    },
    {
        "number": 4,
        "title": "第四卷 · 质量与交付",
        "summary": "以测试、审查、安全和发布闭环守住质量。",
    },
    {
        "number": 5,
        "title": "第五卷 · 持续演进",
        "summary": "管理成本、可观测性、技术债和长期维护。",
    },
)
