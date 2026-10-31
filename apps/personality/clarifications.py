"""Topic-bound fallback questions with visible, specific answer references."""
import re

CONTEXT_PROBES = {
    'IE': '那次经历里，什么最影响你想自己待着，还是找人交流？',
    'NS': '你刚才说的那件事，什么会让你想再多了解一点？',
    'FT': '你作出刚才那个选择时，最看重的是什么？',
    'PJ': '你刚才说的那件事，什么会让你愿意改变原来的安排？',
    'sensitivity': '那次经历里，什么最容易影响你的心情？',
    'recovery': '遇到类似的事时，做什么会让你好受一点？',
    'empathy': '在你刚才说的情况下，你会怎样确认对方真正想表达什么？',
    'boundary': '在你刚才说的情况下，你会怎样把自己的决定告诉对方？',
    'divergence': '你提到的这件事，什么会影响你要不要继续了解它？',
    'execution': '能举一件你愿意多花点时间认真做的小事吗？',
}
PAIR_PROBES = {
    'IE': '上面两种情况下，什么最影响你想自己待着还是和别人交流？',
    'NS': '上面两种情况下，你选择了解信息的方式，主要取决于什么？',
    'FT': '上面两种情况下，你作决定时最看重的是什么？',
    'PJ': '上面两种情况下，你想提前安排还是临时决定，主要取决于什么？',
    'sensitivity': '上面两种情况下，什么最影响你的心情？',
    'recovery': '上面两种情况下，什么最影响你恢复心情的快慢？',
    'empathy': '上面两种情况下，什么会影响你要不要进一步了解对方？',
    'boundary': '上面两种情况下，什么最影响你答应还是拒绝？',
    'divergence': '上面两种情况下，什么会让你想再试试别的办法？',
    'execution': '上面两种情况下，什么最影响你能不能继续做下去？',
}

FACET_PROBES = {
    'recharge': '那次相处结束后，什么最影响你想独处还是找人作伴？',
    'companionship': '你刚才说的那段空闲里，什么最影响你想不想有人作伴？',
    'information': '你了解刚才那件事时，是什么让你先关注那个部分？',
    'learning': '你刚才说的那次学习，是什么让你更想从那个部分开始？',
    'decisions': '你作出刚才那个选择时，最先考虑的是什么？',
    'planning': '你安排刚才那件事时，什么最影响你想提前定好还是临时决定？',
    'closure': '你刚才说的那个选择，什么会影响你想不想尽早定下来？',
    'reactivity': '那次经历里，什么会让你的心情改变？',
    'returning': '那件事告一段落后，什么最影响你重新做自己的事？',
    'regulation': '那次心情不太好时，什么最帮助你缓过来？',
    'perspective': '你刚才说的那件事里，什么会帮助你理解对方的感受？',
    'expression': '你决定怎样回复刚才那个请求时，最在意的是什么？',
    'responsibility': '在你刚才说的情况下，你会根据什么判断自己要承担多少？',
    'alternatives': '你刚才说的那件事，什么会影响你要不要再想一个办法？',
    'transfer': '你刚才说的那件事，什么会帮助你想到别处用过的办法？',
    'starting': '当时最影响你要不要开始动手的是什么？',
    'continuing': '那次做事的过程中，什么最影响你要不要接着做？',
}


def comparison_group(question):
    """Do not compare different facets merely because they share an MBTI axis."""
    if question.get('wording_version') == 'xinying-5' and question.get('facet'):
        return question['target']+':'+question['facet']
    parts = question['id'].split('-')
    key = question.get('target')
    if len(parts) != 3 or not parts[2].isdigit():
        return key
    prefix, _, index = parts; index = int(index)
    groups = {
        ('base', 'IE'): {'recharge': [0, 2, 5, 6, 9], 'thinking': [1, 4, 7, 10], 'initiative': [3, 8, 11]},
        ('verify', 'IE'): {'initiative': [0], 'recharge': [1], 'thinking': [2]},
        ('base', 'NS'): {'connections': [0, 2, 6, 7, 8], 'learning': [1, 4, 11], 'facts': [3, 5, 9, 10]},
        ('verify', 'NS'): {'connections': [0, 2], 'learning': [1]},
        ('base', 'FT'): {'care': [0, 4, 6, 8], 'logic': [1, 3, 5, 9, 10, 11], 'principles': [2, 7]},
        ('verify', 'FT'): {'care': [0], 'logic': [1], 'principles': [2]},
        ('dim', 'sensitivity'): {'noticing': [0, 2, 5], 'impact': [1, 3, 4, 6, 7]},
        ('dim', 'boundary'): {'refusal': [0, 2, 3, 4, 5, 6, 7], 'responsibility': [1]},
        ('dim', 'execution'): {'persistence': [0, 3, 4, 7], 'starting': [1, 2, 5, 6]},
    }.get((prefix, key))
    if groups:
        return next((key+':'+name for name, indexes in groups.items() if index in indexes), None)
    return key


def question_focus(question):
    key = question.get('focus') or question.get('target')
    if key in CONTEXT_PROBES:
        return key
    return {'early-energy': 'IE', 'early-values': 'FT', 'open-conflict': 'boundary',
            'open-action': 'execution', 'open-learning': 'divergence'}.get(question['id'])


def context_candidates(steps, answers):
    questions = {q['id']: q for step in steps for q in step['questions']}
    entries = [(key, value) for key, value in answers.items() if key in questions and not value.get('skipped')
               and (len(value.get('note', '').strip()) >= 8 or value.get('selection')) and question_focus(questions[key])]
    # Prefer a fresh followup reply, then a contextual, detailed open answer.
    # The topic always comes from the original question, never isolated words.
    entries.sort(key=lambda pair: (pair[0].startswith('ai-follow-'),
        questions[pair[0]]['kind'] == 'open', bool(re.search('但是|不过|以前|现在|看情况', pair[1]['note'])),
        len(pair[1]['note']), pair[0].startswith('open-')), reverse=True)
    return entries


def followup_step(steps, answers):
    from .questions import index_questions, quantified
    questions = index_questions(steps)
    candidates = context_candidates(steps, answers)
    items = []
    if candidates:
        key, answer = candidates[0]
        focus = question_focus(questions[key])
        facet = questions[key].get('facet') if questions[key].get('wording_version') == 'xinying-5' else None
        items.append({'id': 'follow-context', 'kind': 'open', 'focus': focus,
            'text': FACET_PROBES.get(facet, CONTEXT_PROBES[focus]), 'source_quote': answer['note'].strip()[:160],
            'source_question': questions[key]['text'], 'evidence': [key],
            **({'facet': facet, 'wording_version': 'xinying-5'} if facet else {}),
            'hint': '可以只说一个具体原因；没有合适的例子也可以跳过。'})
        if answer.get('selection') and not items[-1]['source_quote']:
            items[-1].pop('source_quote')
            items[-1]['source_selection'] = answer['selection']['text']
    # Different responses are context to explore, not proof of a contradiction.
    scores = quantified(steps, answers)
    pairs = []
    for key, score in scores.items():
        if len(score['evidence']) < 2:
            continue
        entries = score['evidence']
        for high in entries:
            for low in entries:
                group = comparison_group(questions[high['question_id']])
                gap = high['scored'] - low['scored']
                if gap >= 5 and abs(high['raw']-low['raw']) >= 5 and group and group == comparison_group(questions[low['question_id']]):
                    pairs.append((gap, key, high, low, group))
    if pairs:
        _, key, high, low, group = max(pairs, key=lambda pair: pair[0])
        refs = [high['question_id'], low['question_id']]
        probe = {'IE:thinking': '上面两种情况下，什么最影响你想先自己理清思路，还是边聊边想？',
                 'IE:initiative': '上面两种情况下，什么会影响你要不要主动找人交流？'}.get(group, PAIR_PROBES[key])
        items.append({'id': 'follow-pattern', 'kind': 'open', 'focus': key, 'text': probe,
            'context_items': [{'question_id': item['question_id'], 'text': questions[item['question_id']]['text'],
                               'value': item['raw']} for item in (high, low)], 'evidence': refs,
            'hint': '不同场合有不同选择很正常。可以结合上面两道题，简单说说原因。'})
    # Do not manufacture a second question merely to fill a round.
    return {'title': '补充理解', 'questions': items} if items else None
