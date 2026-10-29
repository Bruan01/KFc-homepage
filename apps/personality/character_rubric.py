"""One editorial rubric and a literal evidence inventory shared by writer and reviewer."""
import re
import copy
import hashlib

from .questions import DIMENSIONS
from .identity import aliases,contains_alias

VERSION = 'six-evidence-2'
RUBRIC = {
    'sensitivity': {'meaning':'情绪受关系、评价、环境事件影响的程度，不等于能察言观色。', 'low':'较少受影响或反应平稳', 'high':'在相关情境中反应明显、容易被触动', 'keywords':['情绪','害怕','敏感','伤心','生气','在意','羞','自卑','愤怒','平静','迟钝','评价']},
    'recovery': {'meaning':'受挫后怎样恢复、适应或重新投入；可限定在关系支持或特定剧情阶段，不要求独自快速恢复。', 'low':'长期压抑、反复停滞或难以走出', 'high':'能调整、接纳支持并重新投入', 'keywords':['恢复','振作','适应','重新','挫折','失望','接受','失去','坚韧','乐观','压抑','走出','释怀']},
    'empathy': {'meaning':'关注、理解他人处境及回应的方式；能关心具体的人，不代表对所有人都高度共情。', 'low':'较少顾及他人的处境或负担', 'high':'注意他人需要并采取回应', 'keywords':['关心','理解','帮助','安慰','处境','难处','体谅','照顾','担心','负担','支持','热心','同伴']},
    'boundary': {'meaning':'表达意愿、拒绝、责任划分及维护立场；坚持原则可支持立场边界，沉默或不求助不能自动等同健康边界。', 'low':'难以拒绝、容易勉强承担', 'high':'能表达需要并维护明确立场', 'keywords':['拒绝','原则','立场','意愿','边界','需要','退出','责任','承诺','诉说','忍耐','要求','请求']},
    'divergence': {'meaning':'遇到问题时考虑替代路径、调整策略或尝试不同表达，可限定在具体领域。明确反复拒绝替代方案可支持偏低；只坚持一个目标、成绩差或没有相关描写不能据此判低。', 'low':'有明确事实显示拒绝替代方案、在办法失败后仍僵化重复', 'high':'有明确事实显示比较方案、换办法或调整表达', 'keywords':['办法','方案','策略','变通','执着','固执','调整','拒绝','不同','尝试','探索','组合','替代','即兴','想法','思考','表达','路线','灵活']},
    'execution': {'meaning':'持续落实目标与日常行动，可呈现兴趣领域和生活安排的差异；不等同战力、技能等级或成功结局。', 'low':'经常中断、回避或难以落实', 'high':'能持续练习、行动和承担', 'keywords':['持续','坚持','练习','训练','安排','努力','行动','工作','计划','逃避','懒散','反复']},
}
ENGLISH_KEYWORDS={
    'sensitivity':['emotion','sensitive','afraid','angry','hurt','calm','shy'],
    'recovery':['recover','adapt','resilient','grief','setback','again','accept'],
    'empathy':['care','help','understand','comfort','support','friend'],
    'boundary':['refuse','reject','principle','responsibility','request','choice'],
    'divergence':['alternative','strategy','approach','creative','adapt','rigid','stubborn','plan','solution'],
    'execution':['persist','practice','train','effort','work','commit','action'],
}
for _key,_words in ENGLISH_KEYWORDS.items():RUBRIC[_key]['keywords'].extend(_words)
GUIDANCE = (
    '这是有来源的角色编辑标注，不是医学量表或实测能力。允许三类依据：明确性格描写、具体剧情行为、有可解释推理的多段事实综合。'
    '依次写清事实→心理机制→当前维度的倾向和适用范围。无需原文出现心理学术语或1–7数字，也不要求文学资料达到心理学实验标准。'
    '单个明确事件可以支持限定情境的倾向；反复行为可支持更广范围，不能把局部推断夸大为所有情境的稳定能力。'
    '1–2为明显偏低，3为略低，4为有依据的适中或混合，5为略高，6–7为明显偏高；更极端的标注需更强或更反复的事实。'
    '不要因合理的相邻编辑等级差异否决整项，应指出方向颠倒、明显夸大、引文无关或来源矛盾。'
    '未知必须为空，4不能代表未知。高低不代表优劣。区分不同作品版本、世界线、成长阶段；矛盾可被具体情境解释时写明限定，无法解释则保留不足。'
    '引文须逐字存在，证据表只提供检索候选，不保证每段都真正支持对应维度。禁止用性别、外貌、热度、MBTI标签或模型记忆替代原文。'
)


def evidence_registry(character):
    sources=[{'url':character.source_url,'text':character.source_text},*character.extra_sources]
    registry={}
    names=aliases(character)['character']
    for source in sources:
        text=source['text']
        blocks=[block.strip() for block in re.split(r'\n\s*\n|(?<=[。！？])',text) if len(block.strip())>=8]
        windows=set()
        for index,block in enumerate(blocks):
            if contains_alias(block,names):
                windows.update(range(max(0,index-2),min(len(blocks),index+7)))
        role_list=any(term in text[:500] for term in ['角色列表','人物列表','List of characters','list of characters'])
        for index,block in enumerate(blocks):
            if role_list and index not in windows:continue
            excerpt=block[:900]
            key='ev_'+hashlib.sha256((source['url']+'\0'+excerpt).encode()).hexdigest()[:16]
            registry[key]={'id':key,'quote':excerpt,'source_url':source['url']}
    return registry


def evidence_inventory(character):
    table={key:{'label':label,'candidates':[]} for key,label in DIMENSIONS.items()}
    registry=evidence_registry(character)
    for key,definition in RUBRIC.items():
        ranked=[(sum(word.casefold() in item['quote'].casefold() for word in definition['keywords']),index,item) for index,item in enumerate(registry.values())]
        per_source={}
        for score,index,item in sorted(ranked,key=lambda row:(-row[0],row[1])):
            if not score or len(table[key]['candidates'])>=4:break
            if per_source.get(item['source_url'],0)>=2:continue
            if any(old['quote']==item['quote'] for old in table[key]['candidates']):continue
            table[key]['candidates'].append(item);per_source[item['source_url']]=per_source.get(item['source_url'],0)+1
    return {'version':VERSION,'scope':{'character':character.name,'work':character.work_name,'year':character.work_year,'aliases':aliases(character)},'dimensions':table}


def resolve_profile_references(profile,character):
    """IDs select stored literal excerpts. Model-supplied quotation text is ignored for an ID."""
    if not isinstance(profile,dict):return profile
    result=copy.deepcopy(profile);registry=evidence_registry(character)
    def lookup(value):
        if not isinstance(value,str) or value not in registry:raise ValueError('证据编号无效或已过期，请重新生成对应维度')
        return registry[value]
    dimensions=result.get('dimensions')
    if isinstance(dimensions,dict):
        for row in dimensions.values():
            if not isinstance(row,dict):continue
            if row.get('evidence_id') is not None:
                item=lookup(row['evidence_id']);row['quote']=item['quote'];row['source_url']=item['source_url']
            if 'supporting_evidence_ids' in row:
                values=row['supporting_evidence_ids']
                if not isinstance(values,list) or len(values)>3:raise ValueError('补充证据编号最多三项')
                kept=[];quotes=[]
                for value in values:
                    item=lookup(value)
                    if item['quote'] not in quotes and item['quote']!=row.get('quote'):
                        kept.append(value);quotes.append(item['quote'])
                row['supporting_evidence_ids']=kept;row['supporting_quotes']=quotes
    tags=result.get('tags')
    if isinstance(tags,list):
        for row in tags:
            if isinstance(row,dict) and row.get('evidence_id') is not None:
                row['quote']=lookup(row['evidence_id'])['quote']
    return result


def empty_dimensions(table):
    return [key for key,row in table['dimensions'].items() if not row['candidates']]
