# pyright: reportMissingImports=false
from django.db import migrations


DEFAULT_CATEGORIES = [
    {"slug": "announcements", "name": "产品动态", "icon": "新", "color": "#d9232e", "sort_order": 1},
    {"slug": "tech", "name": "技术交流", "icon": "码", "color": "#2563a8", "sort_order": 2},
    {"slug": "help", "name": "使用帮助", "icon": "?", "color": "#a66713", "sort_order": 3},
    {"slug": "resources", "name": "资源分享", "icon": "享", "color": "#16805b", "sort_order": 4},
    {"slug": "showcase", "name": "项目展示", "icon": "作", "color": "#7254b8", "sort_order": 5},
    {"slug": "general", "name": "闲聊广场", "icon": "聊", "color": "#657080", "sort_order": 6},
]

DEFAULT_TOPICS = [
    {
        "category": "announcements",
        "title": "KFlow Community 正式开放：一起建立更好的产品交流空间",
        "content": "从产品动态到技术实践，我们希望每一次公开讨论都能沉淀为下一位创造者的起点。欢迎大家来到 KFlow Community。",
        "author_username": "KFlow 团队",
        "tags": "公告,社区",
        "views": 1286,
        "is_pinned": True,
        "is_featured": True,
    },
    {
        "category": "tech",
        "title": "显影功能的图像压缩与缓存策略，现在是怎样工作的？",
        "content": "整理一份从生成、压缩、缓存到下载的完整链路，也欢迎大家分享真实使用中的速度体验。",
        "author_username": "河川",
        "tags": "显影,缓存",
        "views": 864,
        "is_featured": True,
    },
    {
        "category": "help",
        "title": "新人指南：从注册账号到完成第一次产品下载",
        "content": "一份面向新用户的快速指南，包含积分、下载权限和常见问题的处理方式。",
        "author_username": "木棉",
        "tags": "入门,下载",
        "views": 742,
        "is_pinned": True,
    },
    {
        "category": "resources",
        "title": "分享一个适合 KFlow 发布流程的版本号规范",
        "content": "结合语义化版本与内部构建编号，避免测试包、候选包和正式版本之间出现歧义。",
        "author_username": "Lambda",
        "tags": "版本管理,规范",
        "views": 593,
        "is_featured": True,
    },
    {
        "category": "showcase",
        "title": "项目展示：CodexHub 多服务器管理控制台",
        "content": "用于 Codex App SSH 工作流的多服务器控制台，分享目前的架构、交互和下一阶段计划。",
        "author_username": "Jurio",
        "tags": "开源,CodexHub",
        "views": 1034,
        "is_featured": True,
    },
    {
        "category": "help",
        "title": "如何为一个产品配置多个系统和架构的安装包？",
        "content": "Windows、macOS 与 Linux 包同时发布时，后台排序和默认包选择有哪些推荐做法？",
        "author_username": "未央",
        "tags": "产品包,后台",
        "views": 356,
    },
    {
        "category": "tech",
        "title": "Django + SQLite WAL 模式在小型交付平台中的实践笔记",
        "content": "讨论备份一致性、在线迁移和并发写入边界，以及为什么小规模业务仍可以认真使用 SQLite。",
        "author_username": "北屿",
        "tags": "Django,SQLite",
        "views": 917,
        "is_featured": True,
    },
    {
        "category": "announcements",
        "title": "本周产品更新汇总：下载体验与移动端页面调整",
        "content": "集中记录本周上线的细节优化，并收集下一轮迭代最值得优先处理的问题。",
        "author_username": "KFlow 产品组",
        "tags": "周报,更新",
        "views": 511,
    },
    {
        "category": "general",
        "title": "你们会怎样保存一个项目从想法到上线的过程？",
        "content": "除了 Git 提交，还有哪些轻量方式可以保留设计决策、失败尝试和迭代依据？",
        "author_username": "一页",
        "tags": "工作流,记录",
        "views": 1205,
    },
    {
        "category": "resources",
        "title": "资源整理：产品发布前值得检查的 24 个细节",
        "content": "覆盖版本说明、安装包、权限、回滚、截图和通知，一份可直接复制使用的发布检查单。",
        "author_username": "柚子",
        "tags": "清单,发布",
        "views": 688,
        "is_featured": True,
    },
    {
        "category": "showcase",
        "title": "展示一个为硬件团队制作的内部交付看板",
        "content": "如何让研发、测试和业务同时看到当前版本、审核状态与客户可下载范围。",
        "author_username": "石墨",
        "tags": "看板,硬件",
        "views": 429,
    },
    {
        "category": "general",
        "title": "你最希望 KFlow 下一步增加什么能力？",
        "content": "欢迎分享真实工作流中的阻力：通知、协作、下载、审批或其他任何问题。",
        "author_username": "红杉",
        "tags": "建议,共创",
        "views": 1490,
    },
]


def seed_forum_data(apps, schema_editor):
    category_model = apps.get_model("forum", "ForumCategory")
    topic_model = apps.get_model("forum", "ForumTopic")

    categories = {}
    for data in DEFAULT_CATEGORIES:
        category, _ = category_model.objects.get_or_create(
            slug=data["slug"],
            defaults={key: value for key, value in data.items() if key != "slug"},
        )
        categories[data["slug"]] = category

    # Keep an existing forum intact when this migration is applied to a live DB.
    if topic_model.objects.exists():
        return
    for data in DEFAULT_TOPICS:
        topic_model.objects.create(
            category=categories[data["category"]],
            title=data["title"],
            content=data["content"],
            author_username=data["author_username"],
            tags=data["tags"],
            views=data["views"],
            is_pinned=data.get("is_pinned", False),
            is_featured=data.get("is_featured", False),
        )


def preserve_forum_data(apps, schema_editor):
    # Deliberately do not delete seeded content on migration rollback.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("forum", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_forum_data, preserve_forum_data),
    ]
