"""Versioned, independently written exploration items; not an official MBTI instrument."""
import random
from . import situated_bank, choice_answers

VERSION = situated_bank.VERSION
AXES = {"IE": ("I", "E", "内向", "外向"), "NS": ("N", "S", "直觉", "实感"), "FT": ("F", "T", "情感", "思考"), "PJ": ("P", "J", "灵活", "计划")}
DIMENSIONS = {"sensitivity": "情绪敏感", "recovery": "情绪恢复", "empathy": "共情关注", "boundary": "关系边界", "divergence": "发散思考", "execution": "执行稳定"}

BASE = {
    "IE": [("连续社交之后，我通常需要独处来恢复精力。", False), ("整理复杂想法时，我更习惯先自己思考，再与人交流。", False), ("认识新朋友的过程本身，通常让我更有精力。", True), ("有空闲时间时，我自然地想与别人一起度过。", True), ("遇到新鲜事，我经常在交流中才想清楚自己的感受。", True), ("即使与喜欢的人相处，之后我也需要一点安静时间。", False)],
    "NS": [("了解一件事时，我会先寻找它与其他事情的联系。", False), ("开始新任务时，我更想先看到具体范例和操作步骤。", True), ("比起已知的做法，我容易注意到还没有尝试过的可能。", False), ("讨论问题时，我通常先关注目前可以确认的事实。", True), ("学习新知识时，我想先弄清它背后的整体框架。", False), ("判断一个想法是否可行时，我更依赖亲身经验和具体细节。", True)],
    "FT": [("做影响他人的决定时，我自然地先考虑各自的处境。", False), ("面对分歧，我习惯先用一致的判断标准比较方案。", True), ("如果方案与我在意的价值冲突，我会重新考虑它。", False), ("解释一个决定时，我通常先说明逻辑和权衡过程。", True), ("即使效率会降低，我也倾向为个体的特殊情况调整安排。", False), ("两种选择难分高下时，我更愿意依靠可以比较的客观标准。", True)],
    "PJ": [("做计划时，我喜欢为之后的新信息留出调整空间。", False), ("尽早把安排确定下来，会让我更自在。", True), ("旅行时，我愿意根据当时的兴趣改变路线。", False), ("任务开始前，我通常希望把主要步骤和时间先排好。", True), ("在必须决定之前，我愿意继续保留几个选项。", False), ("一件事有了明确结论以后，我会感到轻松。", True)],
}
EXTENDED = {
    "sensitivity": [("周围气氛的细微变化容易被我察觉。", False), ("一句无意的话可能让我在意一段时间。", False), ("我很少注意到自己细微的情绪变化。", True), ("别人的语气变化容易影响我当下的感受。", False)],
    "recovery": [("情绪波动后，我通常能逐渐回到自己的节奏。", False), ("我知道哪些活动能够帮助自己平静。", False), ("一次不愉快常常会持续影响我之后很长一段时间。", True), ("经过适当休息，我能重新面对让我难过的问题。", False)],
    "empathy": [("我愿意了解他人感受背后的原因。", False), ("遇到不同看法时，我会尝试理解对方的处境。", False), ("事情与我无关时，我很少留意对方的感受。", True), ("沟通时，我会留意自己的表达对别人产生了什么影响。", False)],
    "boundary": [("即使在意对方，我也能表达自己不愿接受的事。", False), ("我能区分理解他人与替他承担责任。", False), ("为了避免关系紧张，我经常答应超出自己能力的请求。", True), ("我可以在保持尊重的同时拒绝别人。", False)],
    "divergence": [("面对一个问题，我容易想到多个解决方向。", False), ("我喜欢把原本不同领域的想法联系起来。", False), ("找到第一个可行答案后，我通常不再探索其他可能。", True), ("我会设想一件事情还可能怎样发展。", False)],
    "execution": [("即使兴趣减退，我也能维持必要的行动。", False), ("我通常能按照自己的安排推进事情。", False), ("如果没有外部提醒，我容易一直推迟开始。", True), ("任务遇到阻碍时，我能够继续完成一小步。", False)],
}
DISTINGUISH = {
    "IE": [("当没有工作或礼仪要求时，我更愿意把一天中的大部分自由时间留给自己。", False), ("为了恢复状态，我通常更想主动找人交流。", True), ("即使不担心被评价，我仍然更习惯先在心里整理想法。", False)],
    "NS": [("面对陌生事物，我会自然地联想到不同的含义和未来可能。", False), ("别人说明一个概念时，我通常希望先听到实际例子。", True), ("发现新的联系，比反复运用熟悉的方法更容易吸引我。", False)],
    "FT": [("规则与具体人的特殊处境发生冲突时，我倾向先考虑能否照顾后者。", False), ("即使会让关系一时紧张，我仍然倾向保持同一判断标准。", True), ("选择没有明显对错时，我更看重是否符合自己珍视的价值。", False)],
    "PJ": [("即使没有截止期限，我也喜欢尽早结束选择并确定安排。", True), ("已经做好的计划出现新机会时，我通常愿意重新调整。", False), ("比起保留变化空间，明确接下来的安排更让我放松。", True)],
}


def scale_item(prefix, target, index, pair):
    return {"id": f"{prefix}-{target}-{index}", "kind": "scale", "target": target, "text": pair[0], "reverse": pair[1]}


def initial_steps(seed=None, previous_ids=()):
    rng = random.Random(seed) if seed is not None else random.SystemRandom()
    previous = set(previous_ids)
    def select(items, count):
        # Prefer unseen items while retaining a mix across repeat assessments.
        fresh = [q for q in items if q["id"] not in previous]
        seen = [q for q in items if q["id"] in previous]
        rng.shuffle(fresh); rng.shuffle(seen)
        chosen = fresh[:count]
        return chosen + seen[:count-len(chosen)]
    steps = []
    for prefix, groups, count, title in [("base", situated_bank.BASE, 6, "日常偏好"), ("dim", situated_bank.EXTENDED, 4, "内在模式")]:
        buckets = {}
        for key in groups:
            pool = [{**scale_item(prefix, key, i, (entry['text'], entry['reverse'])), 'wording_version': VERSION, 'facet': entry['facet']}
                    for i, entry in enumerate(groups[key])]
            reverse_count = 3 if prefix == "base" else rng.choice([1, 2])
            buckets[key] = select([q for q in pool if q["reverse"]], reverse_count) + select([q for q in pool if not q["reverse"]], count-reverse_count)
            # Keep more than one relevant facet when available, without
            # changing the direction balance or treating facets as new scores.
            for facet in dict.fromkeys(q['facet'] for q in pool):
                if any(q['facet'] == facet for q in buckets[key]):
                    continue
                for reverse in (False, True):
                    replacements = [q for q in pool if q['facet'] == facet and q['reverse'] == reverse]
                    outgoing = [q for q in buckets[key] if q['reverse'] == reverse
                                and sum(item['facet'] == q['facet'] for item in buckets[key]) > 1]
                    if replacements and outgoing:
                        buckets[key][buckets[key].index(outgoing[0])] = select(replacements, 1)[0]
                        break
            rng.shuffle(buckets[key])
        items = []
        for i in range(count):
            keys = list(groups); rng.shuffle(keys)
            items.extend(buckets[key][i] for key in keys)
        for offset in range(0, len(items), 8):
            steps.append({"title": title, "questions": items[offset:offset + 8]})
    steps[0]['response_policy'] = choice_answers.POLICY
    steps[0]['analysis_policy'] = 'single-report-v1'
    # Qualitative answers can be selected; optional notes remain separate.
    for index, topic in [(0, "energy"), (3, "values")]:
        prompt = rng.choice(situated_bank.EARLY[topic])
        question = {"id": "early-"+topic, "kind": "open", "focus": 'IE' if topic == 'energy' else 'FT', "text": prompt,
            'facet': situated_bank.EARLY_FACETS[topic][situated_bank.EARLY[topic].index(prompt)],
            "wording_version": VERSION}
        steps[index]["questions"].append(choice_answers.early(question, topic, situated_bank.EARLY[topic].index(prompt)))
    return steps


def wording_bank(steps):
    """Future rounds use the bank the assessment started with, not today's bank."""
    from . import plain_bank, scenario_bank
    version = next((q.get('wording_version') for step in (steps or []) for q in step['questions'] if q.get('wording_version')), '')
    return {'xinying-3': scenario_bank, 'xinying-4': plain_bank, VERSION: situated_bank}.get(version), version


def interview_step(steps=None, answers=None, seed=None):
    from .question_bank import INTERVIEWS
    bank, version = wording_bank(steps)
    if bank:
        INTERVIEWS = bank.INTERVIEWS
    rng = random.Random(seed) if seed is not None else random.SystemRandom()
    scores = quantified(steps or [], answers or {})
    selected = []
    for topic, target in [("conflict", "boundary"), ("action", "execution"), ("learning", "divergence")]:
        value = scores[target]["value"]
        band = "low" if value is not None and value < 40 else "high" if value is not None and value > 65 else "middle"
        prompt = rng.choice(INTERVIEWS[topic][band])
        question = {"id": "open-" + topic, "kind": "open", "text": prompt,
            "hint": "可以讲真实经历，也可以设想自己的反应；说一个主要原因即可。", "focus": target, "branch": band,
            **({'wording_version': version} if bank else {}),
            **({'facet': bank.INTERVIEW_FACETS[topic][band][INTERVIEWS[topic][band].index(prompt)]} if bank is situated_bank else {})}
        selected.append(choice_answers.interview(question, topic, band, INTERVIEWS[topic][band].index(prompt))
                        if bank is situated_bank and choice_answers.active(steps) else question)
    return {"title": "真实情境", "questions": selected}


def index_questions(steps):
    return {q["id"]: q for step in steps for q in step["questions"]}


def quantified(steps, answers):
    all_questions = index_questions(steps)
    result = {}
    for target in [*AXES, *DIMENSIONS]:
        entries = []
        for qid, q in all_questions.items():
            answer = answers.get(qid, {})
            if q.get("target") != target or answer.get("skipped") or answer.get("value") is None:
                continue
            raw = answer["value"]
            entries.append({"question_id": qid, "raw": raw, "scored": 8 - raw if q["reverse"] else raw, "reverse": q["reverse"]})
        minimum = 4 if target in AXES else 3
        mean = sum(e["scored"] for e in entries) / len(entries) if entries else None
        result[target] = {"value": round((mean - 1) / 6 * 100, 6) if len(entries) >= minimum else None, "count": len(entries), "minimum": minimum, "evidence": entries}
    return result


def discrimination_step(steps, answers):
    scores = quantified(steps, answers)
    weakest = sorted(AXES, key=lambda key: abs((scores[key]["value"] if scores[key]["value"] is not None else 50) - 50))[:2]
    bank, version = wording_bank(steps)
    if bank is situated_bank:
        rng = random.Random('verify|'+'|'.join(q['id'] for step in steps for q in step['questions']))
        items = []
        for key in weakest:
            # Four candidates per axis, three asked: every sample retains both
            # directions. The existing six-question round stays the same size.
            indexes = rng.sample(range(len(bank.DISTINGUISH[key])), 3)
            items.extend({**scale_item('verify', key, i, (bank.DISTINGUISH[key][i]['text'], bank.DISTINGUISH[key][i]['reverse'])),
                          'wording_version': version, 'facet': bank.DISTINGUISH[key][i]['facet']} for i in indexes)
        return {'title': '偏好辨别', 'questions': items}
    return {"title": "偏好辨别", "questions": [scale_item("verify", key, i, (bank.DISTINGUISH[key][i], pair[1]) if bank else pair)
            for key in weakest for i, pair in enumerate(DISTINGUISH[key])]}


def followup_step(steps, answers):
    from .clarifications import followup_step as clarify
    return choice_answers.probe(clarify(steps, answers), steps)
