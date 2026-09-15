"""Curated prompt recipes and the database-backed imaging template catalog."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Callable
from uuid import uuid4


class TemplateError(ValueError):
    """Raised when a template or its user-supplied values are invalid."""


@dataclass(frozen=True)
class TemplateField:
    key: str
    label: str
    required: bool = False
    placeholder: str = ""
    default: str = ""
    options: tuple[str, ...] = ()
    max_length: int = 180

    @property
    def kind(self) -> str:
        return "select" if self.options else "text"

    def payload(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "kind": self.kind,
            "required": self.required,
            "placeholder": self.placeholder,
            "default": self.default,
            "options": list(self.options),
            "maxLength": self.max_length,
        }


@dataclass(frozen=True)
class PromptTemplate:
    key: str
    name: str
    category: str
    description: str
    accent: str
    cover_url: str
    fields: tuple[TemplateField, ...]
    render_prompt: Callable[[dict[str, str]], str]
    template_type: str = "prompt"
    skill_key: str = ""
    reference_required: bool = False
    reference_max_count: int = 0

    def payload(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "category": self.category,
            "description": self.description,
            "accent": self.accent,
            "coverUrl": self.cover_url,
            "fields": [field.payload() for field in self.fields],
            "templateType": self.template_type,
            "skillKey": self.skill_key,
            "referenceRequired": self.reference_required,
            "referenceMaxCount": self.reference_max_count,
        }

    def validate_values(self, supplied: object) -> dict[str, str]:
        if supplied is None:
            supplied = {}
        if not isinstance(supplied, dict):
            raise TemplateError("模板参数格式不正确")
        values: dict[str, str] = {}
        for field in self.fields:
            value = str(supplied.get(field.key, field.default) or "").strip()
            if field.required and not value:
                raise TemplateError(f"请填写{field.label}")
            if len(value) > field.max_length:
                raise TemplateError(f"{field.label}不能超过{field.max_length}个字符")
            if field.options and value and value not in field.options:
                raise TemplateError(f"{field.label}不是可选项")
            values[field.key] = value
        return values

    def render(self, supplied: object) -> tuple[str, dict[str, str]]:
        values = self.validate_values(supplied)
        prompt = "\n".join(line.strip() for line in self.render_prompt(values).splitlines() if line.strip())
        if len(prompt) > 4000:
            raise TemplateError("模板生成的提示词过长")
        return prompt, values


def _dining_prompt(value: dict[str, str]) -> str:
    outfit = f"，穿着{value['outfit']}" if value["outfit"] else ""
    return f"""
Use case: photorealistic-natural
Asset type: lifestyle food photography
Primary request: create a natural dining photograph, not a copy of the template preview
Scene/backdrop: {value['venue']}，{value['mood']}
Subject: {value['subject']}{outfit}，正在自然地享用食物
Food: {value['food']}
Style/medium: premium editorial food and lifestyle photography
Composition/framing: medium close-up, a clear person-and-food relationship, natural candid moment
Lighting/mood: warm soft light, appetising food texture, relaxed everyday atmosphere
Constraints: one main person only; no readable text, logo, watermark, collage, or UI frame
"""


def _product_prompt(value: dict[str, str]) -> str:
    return f"""
Use case: ads-marketing
Asset type: commercial product key visual
Primary request: create a polished product campaign image for {value['product']}
Scene/backdrop: clean studio scene in {value['color']} tones
Subject: {value['product']}; visualise this key benefit: {value['benefit']}
Style/medium: premium commercial product photography, modern Chinese brand sensibility
Composition/framing: product hero centered with breathable negative space around it
Lighting/mood: controlled studio lighting, refined highlights, confident and clean
Constraints: no readable text, logo, watermark, extra products, hands, collage, or UI frame
"""


def _poster_prompt(value: dict[str, str]) -> str:
    return f"""
Use case: ads-marketing
Asset type: vertical campaign poster background
Primary request: make a memorable visual poster for {value['theme']}
Scene/backdrop: {value['scene']}
Subject: one clear visual metaphor for {value['theme']}
Style/medium: contemporary editorial poster art, rich visual hierarchy
Composition/framing: vertical composition with intentional empty area for later typography
Lighting/mood: {value['mood']}
Color palette: {value['palette']}
Constraints: no readable text, logo, watermark, busy collage, or UI frame
"""


def _illustration_prompt(value: dict[str, str]) -> str:
    return f"""
Use case: illustration-story
Asset type: narrative illustration
Primary request: illustrate {value['story']}
Scene/backdrop: {value['place']}
Subject: {value['character']}
Style/medium: detailed digital illustration with expressive environmental storytelling
Composition/framing: cinematic wide scene with a clear focal subject
Lighting/mood: {value['mood']}
Color palette: harmonious, intentional, and suitable for the requested mood
Constraints: no readable text, logo, watermark, collage, or UI frame
"""


TEMPLATES: tuple[PromptTemplate, ...] = (
    PromptTemplate(
        key="warm-dining",
        name="暖光餐桌",
        category="人物摄影",
        description="把人物、食物和餐厅氛围换成你自己的，生成自然的生活方式美食照片。",
        accent="dining",
        cover_url="/static/imaging/templates/warm-dining.png",
        fields=(
            TemplateField("subject", "人物描述", True, "例如：年轻亚洲男性，短发，神情放松", "年轻亚洲女性，短发，自然微笑"),
            TemplateField("food", "食物", True, "例如：一碗热气腾腾的豚骨拉面和日式小菜", "一碗热气腾腾的豚骨拉面和日式小菜"),
            TemplateField("venue", "用餐场景", False, default="日式居酒屋靠窗位置", options=("日式居酒屋靠窗位置", "温馨小餐馆", "现代咖啡馆", "露天街边餐桌")),
            TemplateField("mood", "氛围", False, default="下班后的轻松感", options=("下班后的轻松感", "周末约会的温暖感", "朋友聚餐的快乐感", "安静独处的治愈感")),
            TemplateField("outfit", "服装（可选）", False, "例如：米色针织衫"),
        ),
        render_prompt=_dining_prompt,
    ),
    PromptTemplate(
        key="product-hero",
        name="产品主视觉",
        category="商业设计",
        description="为一件产品制作干净、高级、可用于营销物料的主视觉。",
        accent="product",
        cover_url="",
        fields=(
            TemplateField("product", "产品名称与外观", True, "例如：磨砂白色无线耳机充电盒", "磨砂白色无线耳机充电盒"),
            TemplateField("benefit", "核心卖点", True, "例如：轻巧、长续航、降噪", "轻巧、长续航、降噪"),
            TemplateField("color", "主色调", False, default="克制的蓝灰色", options=("克制的蓝灰色", "温暖的奶油色", "高级黑金", "清新的自然绿")),
        ),
        render_prompt=_product_prompt,
    ),
    PromptTemplate(
        key="campaign-poster",
        name="活动海报",
        category="品牌传播",
        description="用一个鲜明的视觉主题创建竖版活动海报底图，并为后续排版预留空间。",
        accent="poster",
        cover_url="",
        fields=(
            TemplateField("theme", "活动主题", True, "例如：夏日音乐节", "夏日音乐节"),
            TemplateField("scene", "核心场景", True, "例如：黄昏时海边的露天舞台", "黄昏时海边的露天舞台"),
            TemplateField("mood", "画面情绪", False, default="热烈、自由、富有节奏感", options=("热烈、自由、富有节奏感", "温柔、浪漫、轻盈", "未来感、充满能量", "极简、克制、精致")),
            TemplateField("palette", "色彩方向", False, default="日落橙、深海蓝与少量亮黄", options=("日落橙、深海蓝与少量亮黄", "高饱和粉紫与电光蓝", "奶油白与森林绿", "黑白与一点亮红")),
        ),
        render_prompt=_poster_prompt,
    ),
    PromptTemplate(
        key="story-illustration",
        name="故事插画",
        category="创意插画",
        description="从一句故事出发，生成具有情绪和叙事感的完整插画场景。",
        accent="illustration",
        cover_url="",
        fields=(
            TemplateField("story", "故事瞬间", True, "例如：雨后，一个人发现了漂浮在街道上的小鲸鱼", "雨后，一个人发现了漂浮在街道上的小鲸鱼"),
            TemplateField("character", "主角", True, "例如：穿黄色雨衣的小女孩", "穿黄色雨衣的小女孩"),
            TemplateField("place", "地点", True, "例如：雨后的老城区街道", "雨后的老城区街道"),
            TemplateField("mood", "情绪", False, default="安静、奇幻、带一点治愈", options=("安静、奇幻、带一点治愈", "明亮、冒险、充满希望", "神秘、梦境般、轻微忧郁", "热闹、童趣、充满想象力")),
        ),
        render_prompt=_illustration_prompt,
    ),
)

_TEMPLATES_BY_KEY = {template.key: template for template in TEMPLATES}


def _field_from_payload(raw: object) -> TemplateField:
    if not isinstance(raw, dict):
        raise TemplateError("模板字段格式不正确")
    key = str(raw.get("key") or "").strip()
    label = str(raw.get("label") or "").strip()
    if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_-]{0,39}", key) or not label:
        raise TemplateError("模板字段需要合法的 key 和标签")
    options = raw.get("options") or []
    if not isinstance(options, list) or any(not str(item).strip() for item in options):
        raise TemplateError("模板下拉选项格式不正确")
    try:
        max_length = int(raw.get("maxLength", raw.get("max_length", 180)))
    except (TypeError, ValueError) as exc:
        raise TemplateError("模板字段长度不正确") from exc
    if not 1 <= max_length <= 1000:
        raise TemplateError("模板字段长度必须在 1-1000 之间")
    return TemplateField(
        key=key,
        label=label[:120],
        required=bool(raw.get("required")),
        placeholder=str(raw.get("placeholder") or "")[:300],
        default=str(raw.get("default") or "")[:1000],
        options=tuple(str(item).strip()[:180] for item in options[:30]),
        max_length=max_length,
    )


def _template_from_row(row) -> PromptTemplate:
    fields = tuple(_field_from_payload(item) for item in (row.fields or []))
    static = _TEMPLATES_BY_KEY.get(row.key)
    source = str(row.prompt_template or "").strip()
    if source.startswith("__builtin__:") and static:
        def renderer(values: dict[str, str], builtin=static) -> str:
            builtin_values = {field.key: values.get(field.key, "") for field in builtin.fields}
            return builtin.render_prompt(builtin_values)
    else:
        def renderer(values: dict[str, str], template_text=source) -> str:
            return re.sub(
                r"\{\{\s*([a-zA-Z][a-zA-Z0-9_-]{0,39})\s*\}\}",
                lambda match: values.get(match.group(1), ""),
                template_text,
            )
    return PromptTemplate(
        key=row.key,
        name=row.name,
        category=row.category,
        description=row.description,
        accent=row.accent,
        cover_url=row.cover_url,
        fields=fields,
        render_prompt=renderer,
        template_type=getattr(row, "template_type", "prompt") or "prompt",
        skill_key=getattr(row, "skill_key", "") or "",
        reference_required=bool(getattr(row, "reference_required", False)),
        reference_max_count=int(getattr(row, "reference_max_count", 0) or 0),
    )


def _db_rows(*, enabled_only: bool = True):
    from .models import ImagingTemplate

    query = ImagingTemplate.objects.all()
    if enabled_only:
        query = query.filter(enabled=True)
    return list(query.order_by("sort_order", "id"))


def ensure_default_templates() -> None:
    from .models import ImagingTemplate

    if ImagingTemplate.objects.exists():
        return
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


def list_template_payloads() -> list[dict[str, Any]]:
    ensure_default_templates()
    rows = _db_rows()
    return [_template_from_row(row).payload() for row in rows] if rows else [template.payload() for template in TEMPLATES]


def get_template(key: object) -> PromptTemplate:
    normalized = str(key or "").strip()
    ensure_default_templates()
    from .models import ImagingTemplate

    row = ImagingTemplate.objects.filter(key=normalized, enabled=True).first()
    if row:
        return _template_from_row(row)
    template = _TEMPLATES_BY_KEY.get(normalized)
    if not template:
        raise TemplateError("未找到该显影模板")
    return template


def render_template(key: object, values: object) -> tuple[PromptTemplate, str, dict[str, str]]:
    template = get_template(key)
    prompt, clean_values = template.render(values)
    return template, prompt, clean_values


def admin_template_payload(row, *, include_prompt: bool = True) -> dict[str, Any]:
    payload = {
        "id": row.pk,
        "key": row.key,
        "name": row.name,
        "templateType": getattr(row, "template_type", "prompt"),
        "skillKey": getattr(row, "skill_key", ""),
        "category": row.category,
        "description": row.description,
        "accent": row.accent,
        "coverUrl": row.cover_url,
        "fields": row.fields or [],
        "referenceRequired": bool(getattr(row, "reference_required", False)),
        "referenceMaxCount": int(getattr(row, "reference_max_count", 0) or 0),
        "enabled": row.enabled,
        "sortOrder": row.sort_order,
        "isSystem": row.is_system,
        "version": row.version,
        "createdAt": row.created_at.isoformat(),
        "updatedAt": row.updated_at.isoformat(),
    }
    if include_prompt:
        payload["promptTemplate"] = row.prompt_template
    return payload


def list_admin_template_payloads() -> list[dict[str, Any]]:
    ensure_default_templates()
    return [admin_template_payload(row) for row in _db_rows(enabled_only=False)]


def _template_values(payload: dict[str, Any], *, current=None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise TemplateError("模板参数格式不正确")
    key = str(payload.get("key", current.key if current else "") or "").strip()
    if not key and current is None:
        key = f"template-{uuid4().hex[:10]}"
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", key) or len(key) > 80:
        raise TemplateError("模板 key 只能包含小写字母、数字和连字符")
    name = str(payload.get("name", current.name if current else "") or "").strip()
    if not name or len(name) > 120:
        raise TemplateError("模板名称不能为空")
    template_type = str(payload.get("templateType", getattr(current, "template_type", "prompt")) or "prompt").strip()
    if template_type not in {"prompt", "skill"}:
        raise TemplateError("模板类型不正确")
    skill_key = str(payload.get("skillKey", getattr(current, "skill_key", "")) or "").strip()[:120]
    if template_type == "skill" and not skill_key:
        raise TemplateError("Skill 模板需要填写 Skill 标识")
    fields_raw = payload.get("fields", current.fields if current else []) or []
    if not isinstance(fields_raw, list) or len(fields_raw) > 30:
        raise TemplateError("模板字段数量不正确")
    fields = [_field_from_payload(item).payload() for item in fields_raw]
    if len({item["key"] for item in fields}) != len(fields):
        raise TemplateError("模板字段 key 不能重复")
    prompt = str(payload.get("promptTemplate", current.prompt_template if current else "") or "").strip()
    if template_type == "prompt" and not prompt:
        raise TemplateError("提示词模板不能为空")
    if len(prompt) > 12000:
        raise TemplateError("提示词模板不能超过 12000 个字符")
    try:
        sort_order = int(payload.get("sortOrder", current.sort_order if current else 100))
        reference_max_count = int(payload.get("referenceMaxCount", getattr(current, "reference_max_count", 0)) or 0)
    except (TypeError, ValueError) as exc:
        raise TemplateError("排序和参考图片数量必须是整数") from exc
    return {
        "key": key,
        "name": name,
        "template_type": template_type,
        "skill_key": skill_key,
        "category": str(payload.get("category", current.category if current else "") or "")[:80],
        "description": str(payload.get("description", current.description if current else "") or "")[:500],
        "accent": str(payload.get("accent", current.accent if current else "") or "")[:40],
        "cover_url": str(payload.get("coverUrl", current.cover_url if current else "") or "")[:500],
        "fields": fields,
        "prompt_template": prompt,
        "reference_required": bool(payload.get("referenceRequired", getattr(current, "reference_required", False))),
        "reference_max_count": max(0, min(10, reference_max_count)),
        "enabled": bool(payload.get("enabled", current.enabled if current else True)),
        "sort_order": sort_order,
    }


def create_template(payload: dict[str, Any]):
    from .models import ImagingTemplate

    values = _template_values(payload)
    if ImagingTemplate.objects.filter(key=values["key"]).exists():
        raise TemplateError("模板 key 已存在")
    return ImagingTemplate.objects.create(**values)


def update_template(row, payload: dict[str, Any]):
    from .models import ImagingTemplate

    values = _template_values(payload, current=row)
    if ImagingTemplate.objects.exclude(pk=row.pk).filter(key=values["key"]).exists():
        raise TemplateError("模板 key 已存在")
    changed = any(getattr(row, field) != value for field, value in values.items())
    for field, value in values.items():
        setattr(row, field, value)
    if changed:
        row.version += 1
    row.save()
    return row
