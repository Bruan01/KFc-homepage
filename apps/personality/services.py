import itertools
import uuid
from datetime import date, timedelta

from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from .catalog import import_characters, profile_draft, validate_profile
from .models import Assessment, Character, PersonalityJob, PersonalitySettings, timestamp
from .provider import complete_json
from .tracing import record_calls
from .questions import AXES, DIMENSIONS, discrimination_step, followup_step, index_questions, interview_step, quantified
from .workflow import run_profile_job, mark_profile_error

DIMENSION_COPY = {
    "sensitivity": ("你较少被细微的气氛变化牵动，往往能保持自己的节奏。", "你能察觉气氛变化，同时会根据情境决定关注多少。", "你容易察觉情绪和语气的细微变化，也可能需要时间消化这些感受。"),
    "recovery": ("情绪波动可能需要较长时间消化，给恢复留出空间会更有帮助。", "你的恢复节奏会随事情的重要性和当时的支持而变化。", "你通常知道如何逐渐平静，并在休息后重新面对问题。"),
    "empathy": ("你倾向先把注意力放在事情本身，可能需要主动询问才能理解对方的感受。", "你会在理解他人和处理事情之间寻找适合当下的平衡。", "你愿意理解他人的处境，也留意自己的表达会如何影响别人。"),
    "boundary": ("表达拒绝可能让你犹豫，尤其在关系重要时。可以先区分愿意做的事和勉强承担的事。", "你会根据关系与情境调整边界，明确说出需要可能让沟通更轻松。", "你较能区分理解与承担，也愿意在保持尊重的同时表达拒绝。"),
    "divergence": ("你更容易围绕已确定的方向持续思考，具体的问题和范例有助于展开理解。", "你会在探索新可能与选择可行方向之间调整思路。", "你容易联想到多个方向，也喜欢发现不同事物之间的联系。"),
    "execution": ("启动和持续行动可能较依赖情境支持，把任务缩小能帮助你找到起点。", "你的行动节奏会受到兴趣、任务清晰度和外部安排影响。", "即使兴趣减退或遇到阻碍，你也较能维持必要的行动。"),
}


def config():
    return PersonalitySettings.objects.filter(pk=1).first() or PersonalitySettings()


def eligible_characters():
    return Character.objects.filter(status="approved").filter(Q(classic=True) | Q(work_year__gte=date.today().year - config().recent_years))


def validate_answers(step, supplied, *, complete=False):
    if not isinstance(supplied, dict):
        raise ValueError("回答格式无效")
    questions = {q["id"]: q for q in step["questions"]}
    if set(supplied) - set(questions):
        raise ValueError("回答包含本轮以外的题目，请刷新后重试")
    if complete and set(supplied) != set(questions):
        raise ValueError("请完成本轮回答")
    clean = {}
    for qid, answer in supplied.items():
        if not isinstance(answer, dict):
            raise ValueError("回答格式无效")
        note, skipped = answer.get("note", ""), answer.get("skipped", False)
        if not isinstance(note, str) or len(note) > 3000 or type(skipped) is not bool:
            raise ValueError("每条说明最多 3000 字，跳过状态需为布尔值")
        value = answer.get("value")
        if complete and questions[qid]["kind"] == "scale" and skipped:
            raise ValueError("量表题请选择 1–7 分")
        if skipped:
            value = None
        elif questions[qid]["kind"] == "scale":
            if value is None and not complete:
                pass
            elif type(value) is not int or not 1 <= value <= 7:
                raise ValueError("量表题请选择 1–7 分")
        elif complete and not 8 <= len(note.strip()) <= 3000:
            raise ValueError("开放回答请至少写 8 个字，或选择跳过")
        else:
            value = None
        clean[qid] = {"value": value, "note": note, "skipped": skipped}
    return clean


def advance(row):
    if row.step_index == 5 and len(row.steps) == 6:
        row.steps = row.steps[:6] + [discrimination_step(row.steps, row.answers), interview_step(row.steps, row.answers, seed=str(row.pk))]
    if row.step_index == 7 and len(row.steps) == 8:
        from .followups import enabled, pending_step
        extra = pending_step(1) if enabled(row, config()) else followup_step(row.steps, row.answers)
        row.steps = row.steps[:8] + ([extra] if extra else [])
    elif row.step_index < len(row.steps):
        step = row.steps[row.step_index]
        meta = step.get('ai_followup', {})
        if meta.get('state') == 'generated' and meta['round'] == 1 and row.step_index == len(row.steps)-1:
            if any(not row.answers.get(q['id'], {}).get('skipped') for q in step['questions']):
                from .followups import pending_step
                row.steps.append(pending_step(2))
    row.step_index += 1
    valid_ids = index_questions(row.steps)
    row.answers = {key: value for key, value in row.answers.items() if key in valid_ids}
    if row.step_index >= len(row.steps):
        row.status = "ready"


def evidence_for(scores, key):
    return [item["question_id"] for item in scores[key]["evidence"]]


def growth_for(scores):
    suggestions = {
        "sensitivity": ("给感受一点缓冲", "遇到让你在意的语气或细节时，先记下实际发生的事，再区分观察与猜测；等情绪平稳后再询问对方。", "留意不明显的感受", "下次重要对话结束后，回想自己和对方各自有哪些感受，试着询问对方的理解，补充仅靠事情本身不容易发现的信息。"),
        "recovery": ("保留有效的恢复方式", "记录一次让你逐渐平静的过程，留下当时有用的休息、活动或支持方式，遇到类似情境时再尝试。", "为恢复留出空间", "在让你反复回想的事情之后，安排短暂休息，再写下目前可以处理的部分；暂时无法处理的部分可以稍后再看。"),
        "empathy": ("理解之后再确认", "想帮助一个人时，先确认对方希望被倾听还是一起想办法，再决定自己愿意提供什么支持。", "主动询问对方的处境", "下次出现分歧时，在提出解决办法之前，先问对方最在意什么，看看是否有你还没有注意到的感受。"),
        "boundary": ("把边界说得更具体", "在表达拒绝时，也说明自己愿意提供的支持范围，让对方知道你的限制和可以商量的部分。", "从较小的拒绝开始", "面对超出余力的请求，先说明自己目前能做到什么，再提出可以接受的安排，观察表达需要之后关系实际如何变化。"),
        "divergence": ("给可能性一个落点", "有许多新想法时，先选出最在意的方向，写下一个可以亲自验证的小行动，再决定是否继续展开。", "为熟悉的方向补一个选项", "处理熟悉问题时，先保留通常的办法，再主动寻找一个不同的解释或方案，比较它们各自适合的情境。"),
        "execution": ("把持续行动留给重要的事", "检查正在坚持的安排是否仍然符合自己的需要，给不再重要的任务减少投入，为真正重视的事情留下精力。", "把启动条件变清楚", "选择一件容易推迟的事，把下一步写成具体动作，并提前准备所需材料；完成后再决定是否继续，观察什么最能帮助你开始。"),
    }
    available = [key for key in DIMENSIONS if scores[key]["value"] is not None]
    available.sort(key=lambda key: (scores[key]["value"] if key != "sensitivity" else 100 - scores[key]["value"], key))
    result = []
    for key in available[:3]:
        high = scores[key]["value"] >= 50
        title, body = suggestions[key][:2] if high else suggestions[key][2:]
        result.append({"title": title, "text": body, "evidence": evidence_for(scores, key)})
    return result


def build_report(row):
    scores = quantified(row.steps, row.answers)
    known = {key: value["value"] for key, value in scores.items()}
    candidates = []
    if all(known[key] is not None for key in AXES):
        for bits in itertools.product((0, 1), repeat=4):
            name = "".join(AXES[key][bit] for key, bit in zip(AXES, bits))
            distance = sum(abs(known[key] - (100 if bit == 0 else 0)) for key, bit in zip(AXES, bits))
            candidates.append((distance, name))
        candidates.sort()
    best = candidates[0][1] if candidates else "待补充"
    axes = [{"key": key, "left": AXES[key][0], "right": AXES[key][1], "left_name": AXES[key][2], "right_name": AXES[key][3],
             "value": round(known[key]) if known[key] is not None else None, "uncertain": known[key] is None or abs(known[key] - 50) <= 10} for key in AXES]
    dimensions = [{"key": key, "name": name, "value": round(known[key]) if known[key] is not None else None} for key, name in DIMENSIONS.items()]
    usable = [key for key in DIMENSIONS if known[key] is not None]
    strongest = sorted(usable, key=lambda key: known[key], reverse=True)[:2]
    title = "与自己的节奏相处" if not strongest else "与".join(DIMENSIONS[key] for key in strongest) + "的探索者"
    patterns = {key: DIMENSION_COPY[key][0 if known[key] < 35 else 2 if known[key] > 65 else 1] for key in usable}
    sections = []
    for heading, keys in [("情绪与恢复", ["sensitivity", "recovery"]), ("关系与边界", ["empathy", "boundary"]), ("学习与思考", ["divergence"]), ("决策与行动", ["execution"])]:
        available = [key for key in keys if key in patterns]
        sections.append({"title": heading, "text": "".join(patterns[key] for key in available) or "这一部分的回答还不足以形成解读。", "evidence": [qid for key in available for qid in evidence_for(scores, key)]})
    if known["IE"] is not None:
        sections.append({"title": "社交与独处", "text": "你更习惯留一段独处时间，整理想法并恢复精力。" if known["IE"] > 60 else "你容易在交流和共同活动中获得精力，也会在互动中整理想法。" if known["IE"] < 40 else "你在独处与交流之间呈现了较平衡的偏好，恢复方式可能随关系和情境变化。", "evidence": evidence_for(scores, "IE")})
    if known["FT"] is not None:
        sections.append({"title": "价值与判断", "text": "做决定时，具体人的处境和你珍视的价值较容易进入考虑。" if known["FT"] > 60 else "做决定时，你较习惯先比较一致的标准与逻辑权衡。" if known["FT"] < 40 else "你会同时考虑一致的标准和具体人的处境，在两者之间寻找合适的取舍。", "evidence": evidence_for(scores, "FT")})
    questions = index_questions(row.steps)
    original_quotes = [(qid, a["note"].strip()) for qid, a in row.answers.items() if questions[qid]["kind"] == "open" and not a["skipped"] and 8 <= len(a["note"].strip()) <= 220]
    quote = original_quotes[0] if original_quotes else ("", "")
    character = None
    if len(usable) == 6:
        pool = []
        for candidate in eligible_characters():
            try:
                profile = validate_profile(candidate.profile, candidate)
            except ValueError:
                continue
            values = {key: (profile["dimensions"][key]["level"] - 1) / 6 * 100 for key in DIMENSIONS}
            distance = sum(abs(known[key] - values[key]) for key in DIMENSIONS) / 6
            pool.append((distance, candidate.pk, candidate, profile, values))
        if pool:
            distance, _, candidate, profile, values = min(pool, key=lambda item: (item[0], item[1]))
            nearest = sorted(DIMENSIONS, key=lambda key: abs(known[key] - values[key]))
            character = {"id": candidate.pk, "name": candidate.name, "work": candidate.work_name, "theme": candidate.theme,
                         "image_url": candidate.image_url, "image_layout": candidate.image_layout, "summary": profile["summary"],
                         "mechanism": profile["mechanism"], "dimensions": {key: round(value) for key, value in values.items()},
                         "similarity": round(100 - distance), "nearest": [DIMENSIONS[k] for k in nearest[:2]], "different": [DIMENSIONS[k] for k in nearest[-2:]],
                         "source_url": candidate.source_url, "reviewed_at": candidate.reviewed_at,
                         "resonance": f"你们在{DIMENSIONS[nearest[0]]}与{DIMENSIONS[nearest[1]]}的轮廓上更接近。",
                         "difference": f"在{DIMENSIONS[nearest[-1]]}上，你的倾向指数为{round(known[nearest[-1]])}，角色档案为{round(values[nearest[-1]])}。共鸣也保留各自的不同。"}
    return {"version": row.version, "generated_at": timestamp(), "type": best, "candidates": [name for _, name in candidates[:3]], "axes": axes, "dimensions": dimensions,
            "title": title, "keywords": [DIMENSIONS[key] for key in strongest], "summary": patterns.get(strongest[0], "每一份具体回答，都让自我理解更清晰。") if strongest else "每一份具体回答，都让自我理解更清晰。",
            "quote": {"text": quote[1], "question_id": quote[0], "question": questions.get(quote[0], {}).get("text", "")}, "sections": sections,
            "growth": growth_for(scores),
            "character": character, "theme": character["theme"] if character else "nature", "audit": {"scores": scores, "method": "(mean(reverse_scored_answers)-1)/6*100", "character_method": "100-mean(abs(user-character))", "character_profile": profile if character else None}, "analysis_mode": "rules"}


def enrich_report(row, report, settings, checkpoint=None, save=None):
    from .analysis import enrich
    return enrich(row, report, settings, complete_json, eligible_characters(), checkpoint, save)


def add_missing_character(row, settings, ai=False):
    import copy
    from .analysis import MATCH_PROMPT, character_snapshot, shortlist, source_answers, validate_match
    report = copy.deepcopy(row.report)
    if report.get("character"):
        return report
    pool = shortlist(report, eligible_characters())
    if not pool:
        raise ValueError("暂时没有与完整六维数据对应的可用角色")
    review = None
    selected = min(pool, key=lambda c: (c["distance"], c["id"]))
    if ai and row.ai_consent and settings.ai_enabled:
        source, _ = source_answers(row)
        names = {name for c in pool for name in (c["name"], c["work"]) if len(name) >= 2}
        def anonymous(value):
            for name in sorted(names, key=len, reverse=True):
                value = value.replace(name, "该人物")
            return value
        candidates = [{"id": c["id"], "mechanism": anonymous(c["profile"]["mechanism"]), "dimensions": c["values"], "references": {key: anonymous(text) for key, text in c["references"].items()}} for c in pool]
        selected, review = validate_match(complete_json(settings, MATCH_PROMPT, {"purpose":"personality_character_match","answers": source, "mechanisms": report.get("mechanisms", []), "candidates": candidates}), pool, source)
    report["character"] = character_snapshot(selected, report, review)
    report["theme"] = selected["theme"]
    report["character_added_at"] = timestamp()
    report.setdefault("audit", {})["character_profile"] = selected["profile"]
    report["audit"]["character_selection"] = "anonymous_mechanism_review" if review else "dimension_distance"
    return report


def process_job(job_id):
    token = uuid.uuid4().hex
    if not PersonalityJob.objects.filter(pk=job_id, status="queued").update(status="processing", claim_token=token, attempts=F("attempts") + 1, started_at=timestamp(), updated_at=timestamp()):
        return
    job = PersonalityJob.objects.select_related("assessment", "character").filter(pk=job_id).first()
    if job is None:  # The owner may delete the assessment immediately after claim.
        return
    owned = PersonalityJob.objects.filter(pk=job_id, status="processing", claim_token=token)
    try:
        settings = config()
        PersonalitySettings.objects.filter(pk=1).update(worker_last_seen_at=timestamp())
        if job.kind == "import":
            def progress(counts):
                owned.update(result=counts, updated_at=timestamp())
                PersonalitySettings.objects.filter(pk=1).update(worker_last_seen_at=timestamp())
            result = import_characters({**job.parameters, "source_job_id": str(job.pk)}, progress=progress)
        elif job.kind == 'followup':
            from .followups import run_job
            run_job(job, settings, complete_json, owned)
            return
        elif job.kind == "profile":
            run_profile_job(job, settings, complete=complete_json, draft=profile_draft, owned=owned)
            return
        elif job.parameters.get('heartline_only'):
            import hashlib,json
            from .heartline import refine_existing
            row = job.assessment
            if row.status != 'completed':
                raise ValueError('请先完成人格报告')
            before = hashlib.sha256(json.dumps(row.report,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
            owned.update(phase='heartline_refinement',updated_at=timestamp())
            with record_calls(row.pk,job.pk):
                result = refine_existing(row,settings,complete_json,force=job.parameters.get('force_heartline') is True)
            with transaction.atomic():
                if not owned.update(updated_at=timestamp()):return
                current = Assessment.objects.filter(pk=row.pk,status='completed').first()
                if current is None or hashlib.sha256(json.dumps(current.report,sort_keys=True,ensure_ascii=False).encode()).hexdigest() != before:
                    owned.update(status='cancelled',updated_at=timestamp());return
                Assessment.objects.filter(pk=row.pk,status='completed').update(report=result,updated_at=timestamp())
                owned.update(status='completed',phase='finalized',result={'report_id':str(row.pk),'heartline_ready':bool(result.get('heartline'))},error='',updated_at=timestamp())
            return
        elif job.parameters.get("character_only"):
            with record_calls(job.assessment_id,job.pk):
                result = add_missing_character(job.assessment, settings, job.parameters.get("ai", False))
            with transaction.atomic():
                if owned.update(status="completed", phase="finalized", result={"report_id": str(job.assessment_id)}, error="", updated_at=timestamp()):
                    Assessment.objects.filter(pk=job.assessment_id, status="completed").update(report=result, updated_at=timestamp())
            return
        else:
            row = job.assessment
            Assessment.objects.filter(pk=row.pk, status="queued").update(status="processing", updated_at=timestamp())
            result = build_report(row)
            if job.parameters.get("ai"):
                if not settings.ai_enabled:
                    raise ValueError("AI 分析已暂停，回答已保存，请稍后重试")
                def checkpoint(phase, payload):
                    if not owned.update(phase=phase, checkpoint=payload, updated_at=timestamp()):
                        raise ValueError("任务已中断，已保存的分析可稍后继续")
                    PersonalitySettings.objects.filter(pk=1).update(worker_last_seen_at=timestamp())
                owned.update(phase="person_analysis", updated_at=timestamp())
                with record_calls(row.pk,job.pk):
                    result = enrich_report(row, result, settings, job.checkpoint, checkpoint)
            with transaction.atomic():
                if owned.update(status="completed", phase="finalized", checkpoint={}, result={"report_id": str(row.pk)}, error="", updated_at=timestamp()):
                    Assessment.objects.filter(pk=row.pk, status="processing").update(report=result, status="completed", updated_at=timestamp())
            return
        owned.update(status="completed", result=result, error="", updated_at=timestamp())
    except Exception as exc:
        # Only known user-facing validation errors are persisted; upstream bodies never are.
        error = str(exc)[:300] if isinstance(exc, ValueError) else "处理未完成，请检查服务配置后重试"
        with transaction.atomic():
            if owned.update(status="failed", error=error, updated_at=timestamp()):
                if job.character_id and job.kind == "profile":
                    mark_profile_error(job, error)
                if job.assessment_id:
                    Assessment.objects.filter(pk=job.assessment_id, status__in=["processing", "queued"]).update(status="failed", updated_at=timestamp())


def recover_jobs():
    cutoff = (timezone.now() - timedelta(minutes=15)).isoformat()
    for job in PersonalityJob.objects.filter(status="processing", updated_at__lt=cutoff):
        if job.kind == 'followup':
            from .followups import finish_job
            finish_job(job, PersonalityJob.objects.filter(pk=job.pk, status='processing', claim_token=job.claim_token),
                       use_fallback=True, reason='追问中断，使用情境题继续')
            continue
        with transaction.atomic():
            changed = PersonalityJob.objects.filter(pk=job.pk, status="processing", updated_at__lt=cutoff).update(status="failed", error="任务中断，进度已保存，可以重试", claim_token="", updated_at=timestamp())
            if changed and job.assessment_id:
                Assessment.objects.filter(pk=job.assessment_id, status__in=["processing", "queued"]).update(status="failed", updated_at=timestamp())
            elif changed and job.kind == "profile" and job.character_id:
                mark_profile_error(job, "任务中断，可继续生成或复核")
