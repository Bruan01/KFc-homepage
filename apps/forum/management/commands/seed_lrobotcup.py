# pyright: reportMissingImports=false
# -*- coding: utf-8 -*-
"""LRobotcup 具身智能板块冷启动种子：1 个分类 + 8 条开山帖（幂等）。

注意：不要调用旧版 seed_forum_categories（其 DEFAULTS 重跑会停用现有分类），
本命令只按 slug 补建自己的板块。
判重用「同 author_username + 同 title + 同 category」：重复执行不新增、
不覆盖已有内容。作者取 official_user() 的用户名。
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Max

from apps.community_ai.services import official_user
from apps.forum.models import ForumCategory, ForumTopic

CATEGORY_SLUG = "embodied-ai"
CATEGORY_NAME = "具身智能"
CATEGORY_ICON = "🤖"

# 每条都带「具身智能」标签，正文为中文 Markdown，含具体讨论引导问题。
SEED_POSTS = [
    {
        "title": "【置顶】具身智能新人报到 & 总答疑：从哪开始、怎么提问、去哪找资料",
        "tags": "具身智能,新人报到,答疑",
        "is_pinned": True,
        "content": """## 欢迎来到具身智能板块

这个板块给所有想入行具身智能（Embodied AI / 机器人学习）的同学：无论你是做算法、做硬件、还是纯好奇，都先在这里报个到。建议回帖时带上三样信息——你现在的基础（专业/年级/工作）、手头能用的设备（有没有真机、显卡、仿真环境）、以及最想做成的一个小项目。

别怕问题太基础，VLA、模仿学习、Sim2Real 这些词我们都会用大白话拆开讲。发帖前可以先翻翻本板块的「学习路线打卡」和「行业周报」两贴，很多共性问题已经有人答过。

**讨论引导：**
1. 你是从哪个契机决定了解具身智能的？目前卡在哪一步（数学、代码、硬件还是方向选择）？
2. 如果只有一台笔记本、没有真机，你觉得第一个该跑通的项目是什么？
3. 你希望这个板块优先补齐哪类内容：论文精读、环境搭建，还是硬件选型？""",
    },
    {
        "title": "方向讨论｜VLA 与具身大模型：端到端是不是唯一解？",
        "tags": "具身智能,VLA,具身大模型",
        "content": """## VLA 到底解决了什么

VLA（Vision-Language-Action）把图像、语言指令和动作输出塞进一个模型，从 RT-2、OpenVLA 到近期的 π0、GR00T 一路演进。支持者认为端到端能复用互联网规模的视觉语言先验；质疑者则指出真机数据稀缺、动作离散化损失精度、推理频率跟不上控制回路。

一个务实的判断标准是：你要解决的是「开放场景的语义泛化」，还是「固定工位的高频稳定操作」？前者更适合 VLA，后者往往还是分层（大模型做规划 + 传统控制器执行）更稳、更便宜。

**讨论引导：**
1. 你更看好「一个大模型包打天下」，还是「大模型规划 + 专用策略/控制器」的分层路线？为什么？
2. VLA 落地最大的瓶颈是数据、算力，还是评测口径不统一？
3. 有没有你实测过、觉得被高估或低估的开源 VLA 工作？贴出复现结果聊聊。""",
    },
    {
        "title": "方向讨论｜模仿学习与强化学习：真机 RL 何时能落地？",
        "tags": "具身智能,模仿学习,强化学习",
        "content": """## 从「照着学」到「自己试」

模仿学习（ACT、Diffusion Policy）靠示教数据快速起步，但分布偏移一遇就崩；强化学习（PPO、SAC 及 offline-to-online）能自己探索，却受限于真机采样成本与安全。现在比较务实的组合是：仿真里大规模 RL 预训练 + 少量真机示教微调 + Sim2Real 迁移。

争论点通常不在「哪个算法更强」，而在「你有多少条高质量示教、多少次试错机会」。没有真机、只有公开数据集时，模仿学习几乎是唯一能立刻出结果的选择；有稳定工位和复位机制时，才谈得上在线 RL。

**讨论引导：**
1. 你在 ACT / Diffusion Policy 上遇到过最典型的失败模式是什么？怎么缓解的？
2. 真机在线 RL 的安全边界（限位、急停、奖励塑形）你会怎么设计？
3. 仿真预训练 + 真机微调，你倾向冻结哪部分、微调哪部分？""",
    },
    {
        "title": "方向讨论｜仿真与数据：Sim2Real 的鸿沟到底怎么填？",
        "tags": "具身智能,仿真,Sim2Real",
        "content": """## 仿真便宜，真机诚实

Isaac Lab / Isaac Sim、MuJoCo、Genesis 让并行采样成本骤降，但「仿真里 99% 成功率、真机 30%」仍是常态。域随机化（光照、摩擦、质量、延迟）、系统辨识、以及用真实数据校准接触模型，是目前主流的三板斧。数据侧则绕不开 LeRobot 的数据集格式与遥操作采集链路。

值得单独拎出来的是「可复现性」：仿真器版本、随机种子、物理参数一旦不锁死，同一份代码换个环境结论就翻。建议每个实验都把配置快照和 seed 一起进版本库。

**讨论引导：**
1. 你做 Sim2Real 时，哪一类域随机化参数的收益最大？有没有反直觉的踩坑？
2. 遥操作采集 vs 仿真合成数据，你的配比是多少？质量怎么评？
3. 你如何锁定实验环境（版本/seed/参数），保证别人能复现你的曲线？""",
    },
    {
        "title": "硬件报价征集与拼单｜从 6 自由度机械臂到整机",
        "tags": "具身智能,硬件,拼单",
        "content": """## 把真实价格摆上台面

具身智能最劝退的往往不是算法，而是「不知道一套能跑起来的硬件到底要多少钱」。本贴长期征集大家拿到的真实报价与渠道，覆盖：桌面级 6 自由度机械臂、夹爪/灵巧手、深度相机（RealSense 等）、力/力矩传感器，以及整机人形或移动底盘。欢迎按「型号 / 含税价 / 采购时间 / 渠道 / 踩坑」的格式回帖。

也欢迎组队拼单：凑够数量谈教育/团体折扣，或共享一台设备做轮值实验。拼单前请务必确认售后、保修和备件供应，别只比裸机价。

**讨论引导：**
1. 你买过最值 / 最后悔的一件硬件是什么？实际到手价多少？
2. 预算 5000 元、2 万元、10 万元三档，你会分别怎么配一套入门平台？
3. 有没有愿意牵头拼单或共享设备的同城伙伴？报个城市和意向。""",
    },
    {
        "title": "学习路线打卡组队｜30 天从零跑通第一个策略",
        "tags": "具身智能,学习路线,打卡",
        "content": """## 用打卡代替「收藏了就等于学了」

路线建议按四段走：第 1 周补齐 Python / PyTorch 与机器人学基础（坐标变换、正逆运动学）；第 2 周在 MuJoCo 或 Isaac Lab 里跑通一个 Gym 环境；第 3 周用 LeRobot 加载公开数据集、复现一次 ACT 训练；第 4 周把策略导出、在仿真里评测并录一段视频交付。

组队规则很简单：每晚在本贴回一句「Day N + 今天做了什么 + 卡在哪」，连续打卡互相监督。卡住超过一天就贴报错日志，别自己死磕。完成者把仓库链接和录屏补在评论区，后来者可以直接照着抄作业。

**讨论引导：**
1. 你打算从哪一周加入？目前的基础大概在哪一段？
2. 四段里你觉得哪一周最容易被劝退，需要提前准备什么？
3. 愿意当小组长带一轮打卡、或帮忙 review 别人代码的，报个名。""",
    },
    {
        "title": "行业动态与周报汇总｜每周一 09:30 自动更新",
        "tags": "具身智能,行业动态,周报",
        "content": """## 这个板块的「信息总入口」

服务端定时任务每周一 09:30 会把过去 7 天从具身智能信源（LeRobot / IsaacLab / MuJoCo 的 release、arXiv cs.RO、DeepMind / NVIDIA 博客、量子位、IEEE Spectrum 等）抓取到的条目，汇总成一篇中文周报发到本板块，并打上「行业动态、周报」标签。周报只搬运标题、来源、时间与原文链接，点击即跳转原站，不做全文转载。

本贴作为索引与讨论区：想回看历史周报、或对某条新闻有判断，直接在本贴跟帖；也欢迎把你看到的、尚未被信源覆盖的重要动态贴进来，下一轮会考虑补进订阅列表。

**讨论引导：**
1. 最近哪条行业新闻最被低估？它对入行者意味着什么机会？
2. 你希望周报增加哪类信源（中文自媒体、论文、招聘、融资）？
3. 周报目前只做汇总，要不要再加一段「本周一句点评」？谁愿意轮值？""",
    },
    {
        "title": "方向讨论｜运动控制与部署工程：从 demo 到量产",
        "tags": "具身智能,运动控制,部署",
        "content": """## 能跑一次不等于能跑一天

很多具身智能项目死在「demo 很惊艳、连续运行就掉链子」：控制频率不稳、关节发热限位、传感器丢帧、模型推理抖动、异常没有兜底策略。这部分恰恰是论文最少、工程最重的地带，涉及 MPC / WBC、实时性（ROS 2 / 实时内核）、状态机与安全降级，以及 OTA 与日志回溯。

一个很实际的分工问题：算法同学训练出的策略，谁来负责把它封装成 200Hz 稳定输出的服务，并在撞到奇异位形时安全停车？这往往决定项目能不能走出实验室。

**讨论引导：**
1. 你遇到过最棘手的「真机不稳定」问题是什么？最后定位到哪一层？
2. 策略推理与控制回路的频率不匹配，你怎么桥接（插值、异步、分层）？
3. 量产/长期运行需要哪些日志、监控和降级机制？有模板可分享吗？""",
    },
]


class Command(BaseCommand):
    help = "幂等创建具身智能板块与 8 条开山帖（作者取官方号）"

    def handle(self, *args, **options):
        official = official_user()
        if not official:
            self.stdout.write(self.style.WARNING("未配置小K 官方账号，跳过具身智能冷启动种子"))
            return
        author = official.username
        created_cat = created_post = skipped = 0
        with transaction.atomic():
            max_sort = ForumCategory.objects.aggregate(Max("sort_order"))["sort_order__max"] or 0
            category, cat_created = ForumCategory.objects.get_or_create(
                slug=CATEGORY_SLUG,
                defaults={
                    "name": CATEGORY_NAME,
                    "icon": CATEGORY_ICON,
                    "sort_order": max_sort + 1,
                    "is_active": True,
                },
            )
            if cat_created:
                created_cat = 1
            for post in SEED_POSTS:
                # 幂等判重：同 author_username + 同 title + 同 category，
                # 命中则跳过，绝不覆盖已有内容。
                if ForumTopic.objects.filter(
                    author_username=author, title=post["title"], category=category,
                ).exists():
                    skipped += 1
                    continue
                ForumTopic.objects.create(
                    category=category,
                    title=post["title"],
                    content=post["content"],
                    author_username=author,
                    tags=post["tags"],
                    status=ForumTopic.STATUS_OPEN,
                    is_pinned=post.get("is_pinned", False),
                )
                created_post += 1
        self.stdout.write(self.style.SUCCESS(
            f"具身智能冷启动：分类 {created_cat} 新建，开山帖 {created_post} 新建，"
            f"{skipped} 已存在跳过（板块 {category.name}）"
        ))
