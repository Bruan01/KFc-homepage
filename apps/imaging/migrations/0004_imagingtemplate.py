from django.db import migrations, models


def seed_templates(apps, schema_editor):
    ImagingTemplate = apps.get_model("imaging", "ImagingTemplate")
    # Reuse the source-controlled recipes so existing deployments retain their
    # exact labels and prompt behaviour, including legacy encoded text.
    from apps.imaging.prompt_templates import TEMPLATES
    for index, template in enumerate(TEMPLATES, start=1):
        ImagingTemplate.objects.create(
            key=template.key,
            name=template.name,
            category=template.category,
            description=template.description,
            accent=template.accent,
            cover_url=template.cover_url,
            fields=[field.payload() for field in template.fields],
            prompt_template=f"__builtin__:{template.key}",
            enabled=True,
            sort_order=index * 10,
            is_system=True,
            version=1,
        )
    return
    # Keep the initial catalog compatible with the four source-controlled recipes.
    seeds = [
        ("warm-dining", "暖光餐桌", "人物摄影", "把人物、食物和餐厅氛围换成你自己的，生成自然的生活方式美食照片。", "dining", "/static/imaging/templates/warm-dining.png", [
            {"key": "subject", "label": "人物描述", "kind": "text", "required": True, "placeholder": "例如：年轻亚洲女性，短发，自然微笑", "default": "", "options": [], "maxLength": 180},
            {"key": "food", "label": "食物", "kind": "text", "required": True, "placeholder": "例如：一碗热气腾腾的豚骨拉面和日式小菜", "default": "", "options": [], "maxLength": 180},
            {"key": "venue", "label": "用餐场景", "kind": "select", "required": False, "placeholder": "", "default": "日式居酒屋靠窗位置", "options": ["日式居酒屋靠窗位置", "温馨小餐厅", "现代咖啡厅", "露天街边餐桌"], "maxLength": 180},
            {"key": "mood", "label": "氛围", "kind": "select", "required": False, "placeholder": "", "default": "下班后的轻松感", "options": ["下班后的轻松感", "周末约会的温暖感", "朋友聚餐的快乐感", "安静独处的治愈感"], "maxLength": 180},
            {"key": "outfit", "label": "服装（可选）", "kind": "text", "required": False, "placeholder": "例如：米色针织衫", "default": "", "options": [], "maxLength": 180},
        ], "__builtin__:warm-dining"),
        ("product-hero", "产品主视觉", "商业设计", "为一件产品制作干净、高级、可用于营销物料的主视觉。", "product", "", [
            {"key": "product", "label": "产品名称与外观", "kind": "text", "required": True, "placeholder": "例如：磨砂白色无线耳机充电盒", "default": "", "options": [], "maxLength": 180},
            {"key": "benefit", "label": "核心卖点", "kind": "text", "required": True, "placeholder": "例如：轻巧、长续航、降噪", "default": "", "options": [], "maxLength": 180},
            {"key": "color", "label": "主色调", "kind": "select", "required": False, "placeholder": "", "default": "克制的蓝灰色", "options": ["克制的蓝灰色", "温暖的奶油色", "高级黑金", "清新的自然绿"], "maxLength": 180},
        ], "__builtin__:product-hero"),
        ("campaign-poster", "活动海报", "品牌传播", "用一个鲜明的视觉主题创建竖版活动海报底图，并为后续排版预留空间。", "poster", "", [
            {"key": "theme", "label": "活动主题", "kind": "text", "required": True, "placeholder": "例如：夏日音乐节", "default": "", "options": [], "maxLength": 180},
            {"key": "scene", "label": "核心场景", "kind": "text", "required": True, "placeholder": "例如：黄昏时海边的露天舞台", "default": "", "options": [], "maxLength": 180},
            {"key": "mood", "label": "画面情绪", "kind": "select", "required": False, "placeholder": "", "default": "热烈、自由、富有节奏感", "options": ["热烈、自由、富有节奏感", "温柔、浪漫、轻盈", "未来感、充满能量", "极简、克制、精致"], "maxLength": 180},
            {"key": "palette", "label": "色彩方向", "kind": "select", "required": False, "placeholder": "", "default": "日落橙、深海蓝与少量亮黄", "options": ["日落橙、深海蓝与少量亮黄", "高饱和粉紫与电光蓝", "奶油白与森林绿", "黑白与一点亮红"], "maxLength": 180},
        ], "__builtin__:campaign-poster"),
        ("story-illustration", "故事插画", "创意插画", "从一句故事出发，生成具有情绪和叙事感的完整插画场景。", "illustration", "", [
            {"key": "story", "label": "故事瞬间", "kind": "text", "required": True, "placeholder": "例如：雨后，一个人发现了漂浮在街道上的小鲸鱼", "default": "", "options": [], "maxLength": 180},
            {"key": "character", "label": "主角", "kind": "text", "required": True, "placeholder": "例如：穿黄色雨衣的小女孩", "default": "", "options": [], "maxLength": 180},
            {"key": "place", "label": "地点", "kind": "text", "required": True, "placeholder": "例如：雨后的老城区街道", "default": "", "options": [], "maxLength": 180},
            {"key": "mood", "label": "情绪", "kind": "select", "required": False, "placeholder": "", "default": "安静、奇幻、带一点治愈", "options": ["安静、奇幻、带一点治愈", "明亮、冒险、充满希望", "神秘、梦境般、轻微忧郁", "热闹、童趣、充满想象力"], "maxLength": 180},
        ], "__builtin__:story-illustration"),
    ]
    for index, (key, name, category, description, accent, cover_url, fields, prompt_template) in enumerate(seeds, start=1):
        ImagingTemplate.objects.create(
            key=key, name=name, category=category, description=description,
            accent=accent, cover_url=cover_url, fields=fields,
            prompt_template=prompt_template, enabled=True, sort_order=index * 10,
            is_system=True, version=1,
        )


class Migration(migrations.Migration):
    dependencies = [("imaging", "0003_imagegenerationjob_template_metadata")]

    operations = [
        migrations.CreateModel(
            name="ImagingTemplate",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("key", models.SlugField(max_length=80, unique=True)),
                ("name", models.CharField(max_length=120)),
                ("category", models.CharField(blank=True, default="", max_length=80)),
                ("description", models.CharField(blank=True, default="", max_length=500)),
                ("accent", models.CharField(blank=True, default="", max_length=40)),
                ("cover_url", models.CharField(blank=True, default="", max_length=500)),
                ("fields", models.JSONField(default=list)),
                ("prompt_template", models.TextField()),
                ("enabled", models.BooleanField(default=True)),
                ("sort_order", models.IntegerField(default=100)),
                ("is_system", models.BooleanField(default=False)),
                ("version", models.PositiveIntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["sort_order", "id"]},
        ),
        migrations.AddIndex(
            model_name="imagingtemplate",
            index=models.Index(fields=["enabled", "sort_order", "id"], name="imaging_template_order_idx"),
        ),
        migrations.RunPython(seed_templates, migrations.RunPython.noop),
    ]
