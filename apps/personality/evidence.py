"""Bounded source retrieval. Only the official search provider receives credentials.

Search summaries and model memories are never admitted as source quotations.
"""
import copy
import hashlib
import ipaddress
import json
import re
import unicodedata
from datetime import timedelta
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode, unquote

from django.utils import timezone

from .models import timestamp
from .provider import _request, AnalysisUnavailable
from .questions import DIMENSIONS
from .identity import aliases,hydrate_identity,identity_matches,contains_alias,alias_positions
from .character_rubric import RUBRIC
from .policy import MAX_SOURCES


ENCYCLOPEDIAS = ('wikipedia.org', 'baike.baidu.com', 'moegirl.org.cn', 'fandom.com')
SEARCH_TOPICS = {'sensitivity':'情绪反应', 'recovery':'受挫后恢复振作', 'empathy':'理解关心他人', 'boundary':'拒绝与关系冲突', 'divergence':'思考不同解决办法', 'execution':'长期坚持行动'}
RETRIEVAL_VERSION='evidence-search-4'


def query_plan(character,dimensions,round_number=0):
    names=aliases(character);targets=[key for key in dimensions if key in SEARCH_TOPICS] or list(SEARCH_TOPICS)
    if 'divergence' in targets:targets=['divergence',*[key for key in targets if key!='divergence']]
    plans=[]
    for index in range(2):
        key=targets[(round_number+index)%len(targets)]
        def pick(values):
            if index==1:
                foreign=next((value for value in values[1:] if value.isascii()),None)
                if foreign:return foreign
                if len(values)>1:return values[1]
            return values[0] if values else ''
        name,work=pick(names['character']),pick(names['work']);english=name.isascii() and work.isascii()
        if key=='divergence':
            positive=(round_number+index)%2==0
            topic=('alternative plans adapt strategy episodes' if positive else 'reject alternatives rigid approach failed plan') if english else ('比较方案 换办法 调整策略 具体剧情' if positive else '拒绝其他方案 固执重复失败办法 具体剧情')
            if round_number>=2:
                topic=('changes tactics after failure compares options' if positive else 'refuses to change despite advice repeats failed approach') if english else ('失败后改变办法 对比选择 角色剧情' if positive else '被劝说仍拒绝改变 反复尝试同一办法')
        else:
            topic=(key+(' specific scenes before after behavior' if round_number>=2 else ' character behavior episodes')) if english else SEARCH_TOPICS[key]+(' 具体事件 前后变化 角色分析' if round_number>=2 else ' 角色经历 人际互动' if round_number else ' 具体剧情 行为')
        name=name[:40];work=work[:max(12,125-len(name)-len(topic))]
        query=(name+' '+work+' '+topic)[:128]
        if query not in plans:plans.append(query)
    return plans


def focus_document(text,character,dimensions):
    """Select one contiguous literal window, rather than always discarding the end."""
    if len(text)<=10000:return text
    names=aliases(character)['character'];positions=alias_positions(text,names)
    starts={0,*[max(0,pos-1000) for pos in positions]}
    words=[word for key in dimensions if key in RUBRIC for word in RUBRIC[key]['keywords']]
    def score(start):
        block=text[start:start+10000]
        if not contains_alias(block,names):return -1
        return sum(word.casefold() in block.casefold() for word in words)+2*sum(word in block for word in ['角色经历','性格特点','人物经历'])
    start=max(sorted(starts),key=score)
    return text[start:start+10000]


def evidence_connection(settings):
    if not settings.evidence_enabled:
        return None
    key = settings.evidence_api_key_ciphertext
    if not key:
        try:
            link = urlsplit(settings.base_url)
            official = link.scheme == 'https' and link.hostname == 'api.deepseek.com' and link.port in (None, 443) and not link.username and not link.password
        except ValueError:
            official = False
        if not official:
            return None
        key = settings.api_key_ciphertext
    if not key:
        return None
    connection = copy.copy(settings)
    connection.base_url = 'https://api.deepseek.com/v1'
    connection.api_key_ciphertext = key
    connection.timeout_seconds = min(settings.timeout_seconds, 45)
    return connection


def public_url(value):
    if not isinstance(value, str) or len(value) > 1000:
        return ''
    try:
        link = urlsplit(value)
        host = (link.hostname or '').lower().rstrip('.')
        if link.scheme != 'https' or link.username or link.password or link.port not in (None, 443) or '.' not in host:
            return ''
        if host.endswith(('.localhost', '.local', '.internal', '.test', '.invalid')) or host in {'localhost', 'metadata.google.internal'}:
            return ''
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            return ''
        return urlunsplit(('https', host, link.path or '/', link.query, ''))
    except ValueError:
        return ''


def compact(text):
    return re.sub(r'[\W_]+', '', unicodedata.normalize('NFKC', text)).casefold()


def source_key(url):
    link = urlsplit(public_url(url))
    host = link.hostname or ''
    if host in {'baike.baidu.com', 'wapbaike.baidu.com'}:
        match = re.search(r'/item/(?:[^/]+/)?(\d+)', unquote(link.path))
        if match:
            return 'baike.baidu.com/item/'+match[1]
    query = [(key,value) for key,value in parse_qsl(link.query) if not key.lower().startswith(('utm_', 'from', 'lemma', 'star', 'structure')) and key.lower() not in {'bst', 'spm', 'source'}]
    return urlunsplit(('https', host, link.path, urlencode(sorted(query)), ''))


def source_family(url):
    host = urlsplit(public_url(url)).hostname or ''
    if host == 'wapbaike.baidu.com':
        return 'baike.baidu.com'
    return next((domain for domain in ENCYCLOPEDIAS if host == domain or host.endswith('.'+domain)),host)


def duplicate_text(text, sources):
    def shingles(value):
        value = compact(value)
        return {value[index:index+5] for index in range(max(0,len(value)-4))}
    current = shingles(text)
    for source in sources:
        prior = shingles(source['text'])
        if current and prior and len(current & prior) / max(len(current),len(prior)) >= .85:
            return True
    return False


def missing_dimensions(profile, character, check=None):
    result = []
    texts = [character.source_text, *[source['text'] for source in character.extra_sources]]
    dimensions = profile.get('dimensions', {}) if isinstance(profile, dict) else {}
    for key in DIMENSIONS:
        row = dimensions.get(key) if isinstance(dimensions, dict) else None
        if not isinstance(row, dict) or type(row.get('level')) is not int or not 1 <= row['level'] <= 7 or not isinstance(row.get('quote'), str) or len(row['quote']) < 6 or not any(row['quote'] in text for text in texts):
            result.append(key)
            continue
        additional=row.get('supporting_quotes',[])
        if not isinstance(row.get('reason'),str) or not 10<=len(row['reason'])<=1000 or not isinstance(additional,list) or len(additional)>3 or any(not isinstance(quote,str) or not 6<=len(quote)<=1500 or not any(quote in text for text in texts) for quote in additional):
            result.append(key)
    if check:
        for row in check.get('dimensions', []):
            if row.get('verdict') != 'supported' and row.get('key') in DIMENSIONS and row['key'] not in result:
                result.append(row['key'])
    return result or list(DIMENSIONS)


def supplement(character, settings, dimensions, *, heartbeat=lambda: None,round_number=0):
    connection = evidence_connection(settings)
    if connection is None:
        return {'sources': [], 'cache': character.evidence_cache, 'status': 'unavailable', 'queries': 0, 'fetched': 0, 'cached': 0,
                'note': '联网补证据未启用或未配置搜索密钥，可在 AI 模型服务的高级设置中检查。'}
    if len(character.extra_sources) >= MAX_SOURCES:
        return {'sources': [], 'cache': character.evidence_cache, 'status': 'full', 'queries': 0, 'fetched': 0, 'cached': 0, 'note': '补充来源已达 12 项，请先移除不适用的来源。'}
    hydrate_identity(character,heartbeat=heartbeat)
    cache = copy.deepcopy(character.evidence_cache) if isinstance(character.evidence_cache, dict) else {}
    result = {'sources': [], 'cache': cache, 'status': 'empty', 'queries': 0, 'fetched': 0, 'cached': 0, 'note': '', 'filters':{}}
    seen = {source_key(source['url']) for source in character.extra_sources}
    seen.add(source_key(character.source_url))
    max_sources = min(3, MAX_SOURCES-len(character.extra_sources))
    errors = []
    fetch_attempts = 0
    for query in query_plan(character,dimensions,round_number):
        heartbeat()
        key = hashlib.sha256(json.dumps([RETRIEVAL_VERSION,query,aliases(character),connection.api_key_ciphertext], ensure_ascii=False).encode()).hexdigest()
        record = cache.get(key, {})
        try:
            fresh = timezone.datetime.fromisoformat(record['at']) > timezone.now()-timedelta(days=1 if record.get('error') or not record.get('sources') else 30)
        except (KeyError, TypeError, ValueError):
            fresh = False
        if fresh:
            result['cached'] += 1
            if record.get('error'):
                errors.append(record['error'])
            candidates = record.get('sources', [])
        else:
            candidates = []
            record = {'at': timestamp(), 'sources': candidates,'filters':{}}
            cache[key] = record
            def reject(reason):
                record['filters'][reason]=record['filters'].get(reason,0)+1
            try:
                result['queries'] += 1
                response = _request(connection, '/tools/search', {'query': query, 'count': 5, 'need_content': True})
                if not isinstance(response, dict) or not isinstance(response.get('results'), list):
                    raise AnalysisUnavailable('搜索服务返回格式无效')
                def priority(item):
                    host = urlsplit(public_url(item.get('url'))).hostname or ''
                    authority = item.get('authority')
                    return 0 if type(authority) is int and authority >= 3 else 1 if any(host == domain or host.endswith('.'+domain) for domain in ENCYCLOPEDIAS) else 2
                families={source_family(source['url']) for source in [*character.extra_sources,*result['sources']]}
                for item in sorted([row for row in response['results'][:10] if isinstance(row, dict)], key=lambda row:(priority(row),source_family(row.get('url')) in families)):
                    heartbeat()
                    url = public_url(item.get('url'))
                    existing_sources = [*character.extra_sources,*result['sources'],*candidates]
                    if not url:
                        reject('unsafe_url');continue
                    if priority(item)>1:
                        reject('untrusted_source');continue
                    if source_key(url) in seen:
                        reject('duplicate_url')
                        continue
                    title = item.get('title') if isinstance(item.get('title'), str) else ''
                    if any(term in (url+' '+title).lower() for term in ('mbti', 'personality-database', '人格测试', '性格测试')):
                        reject('personality_label');continue
                    text = item.get('content')
                    if not isinstance(text, str) or len(text.strip()) < 80:
                        if fetch_attempts >= 3:
                            reject('fetch_limit');continue
                        fetch_attempts += 1; result['fetched'] += 1
                        try:page = _request(connection, '/tools/fetch', {'url': url})
                        except AnalysisUnavailable:
                            reject('fetch_error');continue
                        text = page.get('content') if isinstance(page, dict) else None
                    if not isinstance(text, str) or not 80 <= len(text.strip()) <= 200000:
                        reject('no_body');continue
                    text=text.strip()
                    if not identity_matches(character,text,title):
                        reject('identity_mismatch');continue
                    text=focus_document(text,character,dimensions)
                    if duplicate_text(text,existing_sources):
                        reject('duplicate_content');continue
                    source = {'url': url, 'text': text}
                    candidates.append(source)
                    seen.add(source_key(url))
                    if len(candidates)+len(result['sources']) >= max_sources:
                        break
            except AnalysisUnavailable as exc:
                record['error'] = '联网补证据未完成：'+str(exc)[:220]
                errors.append(record['error'])
        for source in candidates:
            # Cache contains previously retrieved source text, not model summaries.
            existing_sources = [*result['sources'],*character.extra_sources]
            if source_key(source['url']) not in {source_key(item['url']) for item in existing_sources} and not duplicate_text(source['text'],existing_sources) and identity_matches(character,source['text'],character.work_name):
                result['sources'].append(source)
                seen.add(source_key(source['url']))
                if len(result['sources']) >= max_sources:
                    break
        for reason,count in record.get('filters',{}).items():
            result['filters'][reason]=result['filters'].get(reason,0)+count
        if len(result['sources']) >= max_sources:
            break
    result['cache'] = dict(list(cache.items())[-8:])
    result['status'] = 'added' if result['sources'] else 'error' if errors else 'empty'
    result['note'] = f"已补充 {len(result['sources'])} 个网页原文来源。" if result['sources'] else errors[0] if errors else '未找到身份一致且包含可用正文的来源，未补写人格数据。'
    return result
