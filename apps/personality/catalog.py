"""Bangumi acquisition is separate from approval and personality inference."""
import json
import time
import urllib.error
import urllib.request
from datetime import date
from urllib.parse import urlsplit

from .models import Character, PersonalitySettings
from .provider import complete_json
from .questions import DIMENSIONS
from .traits import TAGS
from .character_rubric import RUBRIC, GUIDANCE, evidence_inventory, evidence_registry, resolve_profile_references
from .evidence_context import analysis_context

THEME_IDS = {"nature", "sunshine", "rational", "romantic"}
MBTI_TYPES = {"INTJ", "INTP", "ENTJ", "ENTP", "INFJ", "INFP", "ENFJ", "ENFP", "ISTJ", "ISFJ", "ESTJ", "ESFJ", "ISTP", "ISFP", "ESTP", "ESFP"}
IMAGE_HOSTS = {"lain.bgm.tv"}


def safe_image(url):
    if not isinstance(url, str):
        return False
    try:
        parsed = urlsplit(url or "")
        return bool(parsed.scheme == "https" and parsed.hostname in IMAGE_HOSTS and not parsed.username and not parsed.password and parsed.port in (None, 443))
    except ValueError:
        return False


def bangumi(path, data=None):
    request = urllib.request.Request("https://api.bgm.tv/v0/" + path, data=json.dumps(data).encode() if data is not None else None,
                                     headers={"User-Agent": "KFlow-Xinying/1.0 (character discovery)", "Content-Type": "application/json", "Accept": "application/json"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                raw = response.read(2 * 1024 * 1024 + 1)
                if len(raw) > 2 * 1024 * 1024:
                    raise ValueError("Bangumi 返回内容过大")
                return json.loads(raw)
        except urllib.error.HTTPError as exc:
            retryable = exc.code == 429 or exc.code >= 500
            exc.close()
            if not retryable or attempt == 2:
                raise ValueError("Bangumi 暂时无法连接，请稍后重试导入") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            if attempt == 2:
                raise ValueError("Bangumi 暂时无法连接，请稍后重试导入") from None
        except json.JSONDecodeError:
            raise ValueError("Bangumi 返回数据格式有误，请稍后重试") from None
        time.sleep(1 + attempt * 2)


def validate_dimension(row,character,label,registry=None):
    if registry is None:registry=evidence_registry(character)
    if not isinstance(row, dict) or (row.get("level") is not None and (type(row["level"]) is not int or not 1 <= row["level"] <= 7)):
        raise ValueError(f"{label}需要 1–7 级标注或保留为未知")
    evidence_type = row.get("evidence_type", "verified")
    if evidence_type not in {"verified", "inferred", "manual"}:
        raise ValueError(f"{label}的依据类型无效")
    quote, reason = row.get("quote", ""), row.get("reason", "")
    if not isinstance(reason, str) or (row["level"] is not None and not 10 <= len(reason.strip()) <= 1000) or len(reason) > 1000:
        raise ValueError(f"请说明{label}的标注理由")
    if row["level"] is None:
        return {"level": None, "reason": reason.strip(), **({"evidence_type": evidence_type} if evidence_type != "verified" else {})}
    if evidence_type == "inferred":
        return {"level": row["level"], "reason": reason.strip(), "evidence_type": "inferred"}
    sources = [{"url": character.source_url, "text": character.source_text}, *character.extra_sources]
    supporting = next((source for source in sources if isinstance(quote, str) and quote and quote in source["text"]), None)
    if not isinstance(quote, str) or not 6 <= len(quote) <= 1500 or not supporting:
        raise ValueError(f"{label}的依据必须逐字引用已导入资料（至少 6 字）")
    clean = {"level": row["level"], "quote": quote, "reason": reason.strip(), "source_url": supporting["url"]}
    if evidence_type == "manual":
        clean["evidence_type"] = "manual"
    reference=row.get('evidence_id')
    if reference is not None:
        if not isinstance(reference,str) or reference not in registry or registry[reference]['quote']!=quote:
            raise ValueError(f'{label}的引文与证据编号不一致')
        clean.update(evidence_id=reference,source_url=registry[reference]['source_url'])
    additional=row.get('supporting_quotes',[])
    if not isinstance(additional,list) or len(additional)>3 or any(not isinstance(item,str) or not 6<=len(item)<=1500 or not any(item in source['text'] for source in sources) for item in additional):
        raise ValueError(f"{label}的补充引文必须逐字存在于来源中，最多三段")
    if additional:
        clean['supporting_quotes']=list(dict.fromkeys(additional))
    references=row.get('supporting_evidence_ids')
    if references is not None:
        if not isinstance(references,list) or len(references)>3 or any(not isinstance(ref,str) or ref not in registry for ref in references) or [registry[ref]['quote'] for ref in references]!=additional:
            raise ValueError(f'{label}的补充引文与证据编号不一致')
        if references:clean['supporting_evidence_ids']=references
    return clean


def evidence_summary(profile):
    dimensions = profile.get("dimensions", {}) if isinstance(profile, dict) else {}
    verified = [key for key, row in dimensions.items() if isinstance(row, dict) and type(row.get("level")) is int and row.get("evidence_type", "verified") != "inferred"]
    inferred = [key for key, row in dimensions.items() if isinstance(row, dict) and type(row.get("level")) is int and row.get("evidence_type") == "inferred"]
    return {"verified": verified, "inferred": inferred, "weights": {key: 0.5 if key in inferred else 1 for key in [*verified, *inferred]}}


def validate_profile(profile, character):
    if not isinstance(profile, dict):
        raise ValueError("人格档案必须是 JSON 对象")
    clean = {"dimensions": {}, "summary": "", "mechanism": ""}
    for field in ("summary", "mechanism"):
        value = profile.get(field, "")
        if not isinstance(value, str) or not 10 <= len(value.strip()) <= 1200:
            raise ValueError("请填写角色简介与心理机制（10–1200 字）")
        clean[field] = value.strip()
    if any(text and text in clean["summary"] for text in (character.name, character.work_name)):
        raise ValueError("人格摘要不能复述角色姓名或作品名，请改写为情绪、关系、决策和行动倾向")
    motto = profile.get("motto")
    if motto is not None:
        if not isinstance(motto, str) or not 2 <= len(motto.strip()) <= 80:
            raise ValueError("角色座右铭需为 2–80 字")
        clean["motto"] = motto.strip()
    dimensions = profile.get("dimensions")
    registry=evidence_registry(character)
    if not isinstance(dimensions, dict) or set(dimensions) != set(DIMENSIONS):
        raise ValueError("请补齐六个维度及其来源依据")
    for key,label in DIMENSIONS.items():
        clean["dimensions"][key]=validate_dimension(dimensions[key],character,label,registry)
    sources=[{"url":character.source_url,"text":character.source_text},*character.extra_sources]
    signature = profile.get('signature_quote')
    if signature is not None:
        if not isinstance(signature, dict) or not isinstance(signature.get('text'), str) or not 2 <= len(signature['text'].strip()) <= 300:
            raise ValueError('角色台词需要 2–300 字原文')
        text = signature['text'].strip()
        supporting = next((source for source in sources if text in source['text'] and (not signature.get('source_url') or source['url'] == signature['source_url'])), None)
        if not supporting:
            raise ValueError('角色台词必须逐字存在于对应来源中')
        clean['signature_quote'] = {'text': text, 'source_url': supporting['url']}
    tags = profile.get("tags", [])
    if not isinstance(tags, list) or len(tags) > 12:
        raise ValueError("机制标签最多 12 项")
    clean["tags"] = []
    for item in tags:
        if not isinstance(item, dict) or item.get("key") not in TAGS:
            raise ValueError("角色机制标签无效")
        quote = item.get("quote")
        supporting = next((s for s in sources if isinstance(quote, str) and 6 <= len(quote) <= 1500 and quote in s["text"]), None)
        if not supporting:
            raise ValueError("机制标签需要逐字引用资料原文")
        tag={"key":item["key"],"quote":quote,"source_url":supporting["url"]}
        reference=item.get('evidence_id')
        if reference is not None:
            if not isinstance(reference,str) or reference not in registry or registry[reference]['quote']!=quote:raise ValueError('机制标签的证据编号无效')
            tag.update(evidence_id=reference,source_url=registry[reference]['source_url'])
        clean['tags'].append(tag)
    return clean


def profile_draft(character, config, feedback=""):
    targets=getattr(character,'_revision_targets',list(DIMENSIONS))
    inference_targets=getattr(character,'_inference_targets',[])
    needs_mbti=not character.mbti_type
    inference_rule=(
        "本次仅补全 inference_targets 中缺少直接资料的维度。可根据已有资料作保守的编辑推断，每项必须返回 evidence_type='inferred'、1–7 的 level 和说明不确定性及推理范围的 reason；不要提供 evidence_id、quote 或 supporting_evidence_ids，不得把推断冒充原文事实，也不得固定取中点。"
        if inference_targets else
        "资料不能支持时 level=null，quote 为空，说明缺失内容。4 也需要明确的适中或正反行为证据，禁止以取中点代表不知道。无依据时level=null、evidence_id=null，不得虚构编号。"
    )
    mbti_rule=(
        "current_mbti 为空，请同时输出 mbti_type，从16种标准MBTI代码中选择与角色资料最吻合的唯一类型。分别考虑精力恢复与关系投入、信息关注点、决策依据、计划与应变方式；依据具体行为作最佳拟合，不由六维分数机械换算，不按职业、性别、外貌或刻板印象判断。"
        if needs_mbti else
        "current_mbti 已由管理员或先前档案确定，必须保留，不要返回或修改 mbti_type。"
    )
    result=complete_json(config,
        "根据角色资料拟一份待人工审核的人格档案，不得猜测缺失剧情。输出 summary（人格摘要，不是人物介绍）、mechanism（核心价值、关系、压力、行动机制）、theme（nature/sunshine/rational/romantic）、dimensions。"
        "summary 只描述情绪反应、关系需要、决策方式与行动倾向，禁止复述角色姓名、作品名、学校、身份、职业、能力、外貌或经历履历，不以‘某某是……’开头。"
        "同时输出 motto：根据人格提炼一句 2–80 字、适合展示的座右铭，简洁有力量，不写分析过程。它是 AI 提炼而非角色原话，不得包装成台词或虚构名言。"
        "summary 和 mechanism 必须各为 10–1200 字的中文字符串，绝不能返回对象或数组。theme 必须是四个主题 ID 之一。严格遵守输入 output_schema 的类型，不能返回 schema 本身。"+mbti_rule+
        "首次生成的 dimensions 包含 sensitivity/recovery/empathy/boundary/divergence/execution，每项为 {level,evidence_id,reason}。evidence_id从证据候选表选择，不要重抄quote，程序自动带出原文。定向修正时只返回 revision_targets 中的维度，不要重复 locked_dimensions；其余内容由程序保留。level 为 1–7 的编辑标注；"
        "分别表示情绪易受影响、情绪恢复、关心他人处境、表达拒绝及区分责任、多方向联想、持续落实行动。高低不是优劣。"
        "每项 quote 必须逐字引用输入资料，reason 说明该行为如何支持该级别。"+inference_rule+
        "明确区分兴趣、技能、战力与心理机制；单次关怀不能推断稳定高共情，不把独处或沉默自动视作边界清楚。剧情阶段或情境矛盾应保留限定和不确定性。"
        "忽略性别、外貌、热度。禁止为了雷达图补全数字，禁止按 MBTI 套模板。"
        "可添加 tags 数组，每项 {key,evidence_id}，key 选自机制字典，evidence_id选自支撑该机制的原文片段，无依据不要添加。"
        "输出保持紧凑：summary建议50–100字，mechanism建议120–260字，每维reason建议60–160字，quote只摘最相关的连续原文，通常不超过200字。"
        "每维可附 supporting_evidence_ids 数组（最多三项，优先只选必要的一两段），程序带出补充原文。reason要说明事实、推理和情境限定。"
        "若输入给出 revision_targets，仅修复这些维度；locked_dimensions为已获复核支持的内容，必须逐字保留。修复时先使用已有证据，不能为了与审核意见一致编造事实。"+GUIDANCE+("\n上述‘未知必须为空’仅适用于原文验证；本次 inference_targets 必须按 inferred 要求给出保守级别。" if inference_targets else ""),
        {"purpose":"character_profile","name": character.name, "work": character.work_name, "source_url": character.source_url, "mechanism_dictionary": TAGS,
         "output_schema": {"summary": "人格摘要，50–100字，不写姓名、作品、身份或经历履历", "mechanism": "中文字符串，10–1200字", "motto":"2–80字的 AI 提炼座右铭", "theme": "nature/sunshine/rational/romantic", **({"mbti_type":"16种标准MBTI代码之一"} if needs_mbti else {}), "dimensions": {key: {"level": "1–7整数或null", "evidence_id": "从候选表选择的id或null", "reason": "至少10字的字符串","supporting_evidence_ids":"可选，至多三项id",**({"evidence_type":"inferred"} if key in inference_targets else {})} for key in targets if key in DIMENSIONS}},
         **analysis_context(character,targets), "rubric":RUBRIC,
         "revision_targets":targets,"inference_targets":inference_targets,"current_mbti":character.mbti_type,
         "locked_dimensions":{key:{'level':row['level'],'status':'已认可，保留原标注'} for key,row in getattr(character,'_locked_dimensions',{}).items()},
         "dimension_review":getattr(character,'_dimension_review',{}),
         "review_feedback": feedback, "feedback_rule": "管理员意见只能帮助定位需核对之处，不得据此编造证据或迎合修改分数。"})
    if isinstance(result,dict) and not result.get('motto') and not character.profile.get('motto') and not character.profile.get('signature_quote'):
        raise ValueError('AI 未返回角色座右铭，请重试')
    return resolve_profile_references(result,character)


def mbti_draft(character, config, complete=complete_json):
    result=complete(config,
        "根据角色资料选择最佳拟合的 MBTI 类型，只返回 JSON 对象 {'mbti_type':'16种标准MBTI代码之一'}。"
        "分别考虑精力恢复与关系投入、信息关注点、决策依据、计划与应变方式；依据具体行为，不按六维分数、职业、性别、外貌或刻板印象机械判断。资料有限时也给出相对最符合的唯一类型。",
        {"purpose":"character_mbti","name":character.name,"work":character.work_name,"source_url":character.source_url,
         "output_schema":{"mbti_type":"16种标准MBTI代码之一"},**analysis_context(character,list(DIMENSIONS))})
    value=result.get('mbti_type') if isinstance(result,dict) else None
    if value not in MBTI_TYPES:
        raise ValueError('AI 未返回有效的角色 MBTI 类型，请重试')
    return value


def motto_draft(character, config, complete=complete_json):
    result=complete(config,
        "根据角色的人格资料提炼一句适合展示的座右铭，只返回 JSON 对象 {'motto':'2–80字'}。"
        "语言简洁、有力量，符合角色的情绪、关系和选择，不写分析过程。这是 AI 提炼，不是角色原话，不得包装成台词或虚构名言。",
        {"purpose":"character_motto","name":character.name,"work":character.work_name,"source_url":character.source_url,
         "output_schema":{"motto":"2–80字的 AI 提炼座右铭"},**analysis_context(character,list(DIMENSIONS))})
    value=result.get('motto') if isinstance(result,dict) else None
    if not isinstance(value,str) or not 2<=len(value.strip())<=80:
        raise ValueError('AI 未返回有效的角色座右铭，请重试')
    return value.strip()


def normalize_draft(profile):
    """Preserve existing text from older structured responses; never fill evidence or levels."""
    if not isinstance(profile, dict):
        return profile
    result = dict(profile)
    def text_parts(value, depth=0):
        if depth > 3:
            return []
        if isinstance(value, str):
            return [value.strip()] if value.strip() else []
        if isinstance(value, list):
            return [part for item in value[:20] for part in text_parts(item, depth+1)]
        if isinstance(value, dict):
            return [str(key)+"："+"；".join(parts) for key, item in list(value.items())[:20] if (parts := text_parts(item, depth+1))]
        return []
    if isinstance(result.get("mechanism"), (dict, list)):
        result["mechanism"] = "\n".join(text_parts(result["mechanism"]))[:1200]
    return result


def import_characters(parameters, progress=None):
    from .discovery import collect
    return collect(parameters, fetch=bangumi, delay=time.sleep, progress=progress)
