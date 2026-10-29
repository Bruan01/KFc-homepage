"""Reuse dimension decisions only while identity, scores and their source material still match."""
import copy
import hashlib
import json

from .catalog import validate_dimension
from .character_rubric import VERSION,evidence_registry
from .questions import DIMENSIONS


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def identity_key(character):
    return digest({key:getattr(character,key) for key in ['source_id','name','work_id','work_name','work_year']})


def make_record(character,key,dimension,review,registry=None):
    registry=registry if registry is not None else evidence_registry(character)
    clean=validate_dimension(dimension,character,DIMENSIONS[key],registry)
    if not isinstance(review,dict) or review.get('key')!=key or review.get('verdict')!='supported':raise ValueError('维度未获认可')
    quote=review.get('source_quote')
    if not isinstance(quote,str) or not 6<=len(quote)<=1500:raise ValueError('复核缺少有效依据')
    reference=review.get('source_evidence_id')
    if reference is not None and (not isinstance(reference,str) or reference not in registry or registry[reference]['quote']!=quote):raise ValueError('复核引用失效')
    sources=[{'url':character.source_url,'text':character.source_text},*character.extra_sources]
    bindings={}
    for text,preferred in [(clean['quote'],clean['source_url']),*[(q,'') for q in clean.get('supporting_quotes',[])],(quote,registry[reference]['source_url'] if reference else '')]:
        source=next((source for source in sources if (not preferred or source['url']==preferred) and text in source['text']),None)
        if not source:raise ValueError('维度来源已改变')
        bindings[source['url']]=digest(source['text'])
    record={'identity':identity_key(character),'rubric_version':VERSION,'dimension':clean,'review':copy.deepcopy(review),'sources':bindings}
    record['fingerprint']=digest(record)
    return record


def validate_records(character,records,profile=None):
    if not isinstance(records,dict):return {}
    profile=profile if isinstance(profile,dict) else character.profile
    dimensions=profile.get('dimensions',{}) if isinstance(profile,dict) else {}
    if not isinstance(dimensions,dict):return {}
    registry=evidence_registry(character);result={}
    for key,record in records.items():
        if key not in DIMENSIONS or not isinstance(record,dict):continue
        try:
            fresh=make_record(character,key,dimensions.get(key),record.get('review'),registry)
            if fresh==record:result[key]=copy.deepcopy(record)
        except (ValueError,TypeError,KeyError):continue
    return result


def retained_approvals(character):
    check=character.profile_check if isinstance(character.profile_check,dict) else {}
    result=validate_records(character,check.get('dimension_approvals',{}))
    # Upgrade earlier successful per-dimension reviews without changing any scores.
    from .review import profile_fingerprint
    if check.get('rubric_version')==VERSION and check.get('fingerprint')==profile_fingerprint(character) and check.get('identity',{}).get('verdict')=='supported':
        for row in check.get('dimensions',[]):
            if not isinstance(row,dict) or row.get('key') not in DIMENSIONS or row.get('verdict')!='supported':continue
            try:result[row['key']]=make_record(character,row['key'],character.profile['dimensions'][row['key']],row)
            except (ValueError,TypeError,KeyError):continue
    return result


def update_approvals(character,profile,check,prior):
    result=validate_records(character,prior,profile)
    identity=check.get('identity',{}).get('verdict')
    if identity in {'mismatch','uncertain'}:return {}
    if identity!='supported':return result
    for row in check.get('dimensions',[]):
        key=row.get('key')
        if key not in DIMENSIONS:continue
        if row.get('verdict')=='supported':
            try:result[key]=make_record(character,key,profile['dimensions'][key],row)
            except (ValueError,TypeError,KeyError):result.pop(key,None)
        elif row.get('verdict')=='contradicted':result.pop(key,None)
    return result
