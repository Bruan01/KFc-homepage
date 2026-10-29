"""Trusted display-name aliases from Bangumi metadata; never infer identity from model memory."""
import copy
import re
import unicodedata
from datetime import timedelta

from django.utils import timezone

ALIAS_KEYS={'别名','简体中文名','繁体中文名','中文名','英文名','日文名','罗马字','罗马音','外文名','原名','本名','昵称','alias','aliases','name','english name','romanized name'}


def compact(value):
    return re.sub(r'[\W_]+','',unicodedata.normalize('NFKC',value)).casefold()


def clean_aliases(values,limit=24):
    result=[];seen=set()
    for value in values:
        if not isinstance(value,str) or not 2<=len(value.strip())<=160 or '\n' in value or '://' in value:
            continue
        value=value.strip();key=compact(value)
        if len(key)>=2 and key not in seen:
            result.append(value);seen.add(key)
        if len(result)>=limit:break
    return result


def metadata_names(data):
    values=[data.get('name'),data.get('name_cn')]
    def unpack(value):
        if isinstance(value,str):return [value]
        if isinstance(value,list):return [part for item in value[:30] for part in unpack(item)]
        if isinstance(value,dict):return unpack(value.get('v',value.get('value')))
        return []
    values+=unpack(data.get('aliases'))
    for item in data.get('infobox',[]) if isinstance(data.get('infobox'),list) else []:
        if isinstance(item,dict) and str(item.get('key','')).strip().casefold() in ALIAS_KEYS:
            values+=unpack(item.get('value'))
    return clean_aliases(values)


def metadata_identity(character_data,work_data):
    return {'character_aliases':metadata_names(character_data),'work_aliases':metadata_names(work_data),
            'character_loaded':True,'work_loaded':'infobox' in work_data}


def aliases(character):
    stats=character.source_stats if isinstance(character.source_stats,dict) else {}
    identity=stats.get('identity',{}) if isinstance(stats.get('identity',{}),dict) else {}
    names=identity.get('character_aliases',[]);works=identity.get('work_aliases',[])
    return {'character':clean_aliases([character.name,*(names if isinstance(names,list) else [])]),
            'work':clean_aliases([character.work_name,*(works if isinstance(works,list) else [])])}


def contains_alias(text,names):
    folded=unicodedata.normalize('NFKC',text).casefold()
    joined=compact(text)
    for name in names:
        key=compact(name)
        if not key:continue
        # Short Latin names must be whole words (Rei must not match "foreign").
        if key.isascii() and key.isalnum() and len(key)<=5:
            if re.search(r'(?<![a-z0-9])'+re.escape(key)+r'(?![a-z0-9])',folded):return True
        elif key in joined:
            return True
    return False


def identity_matches(character,text,title=''):
    names=aliases(character)
    return contains_alias(text,names['character']) and contains_alias(title+' '+text,names['work'])


def alias_positions(text,names):
    positions=[]
    for name in names:
        positions.extend(match.start() for match in list(re.finditer(re.escape(name),text,re.I))[:30])
    if positions:return positions
    # Locate names split by punctuation, line wrapping or full-width characters
    # while returning offsets into the untouched original body.
    characters=[];offsets=[]
    for index,char in enumerate(text):
        for normalized in unicodedata.normalize('NFKC',char).casefold():
            if normalized.isalnum():characters.append(normalized);offsets.append(index)
    joined=''.join(characters)
    for name in names:
        key=compact(name);start=0
        for _ in range(30):
            found=joined.find(key,start)
            if found<0:break
            positions.append(offsets[found]);start=found+len(key)
    return positions


def hydrate_identity(character,*,heartbeat=lambda:None,fetch=None):
    """One metadata refresh for old stored characters; new imports retain aliases directly."""
    if not character.pk:return
    from . import catalog
    fetch=fetch or catalog.bangumi
    stats=copy.deepcopy(character.source_stats) if isinstance(character.source_stats,dict) else {}
    identity=stats.get('identity',{})
    identity=copy.deepcopy(identity) if isinstance(identity,dict) else {}
    if identity.get('character_loaded') and identity.get('work_loaded'):return
    try:
        if identity.get('retry_after') and timezone.datetime.fromisoformat(identity['retry_after'])>timezone.now():return
    except (TypeError,ValueError):pass
    try:
        if not identity.get('character_loaded'):
            heartbeat();data=fetch(f'characters/{character.source_id}')
            if not isinstance(data,dict) or data.get('id')!=character.source_id:raise ValueError('角色别名元数据的身份不一致')
            identity['character_aliases']=metadata_names(data);identity['character_loaded']=True
        if not identity.get('work_loaded'):
            heartbeat();data=fetch(f'subjects/{character.work_id}')
            if not isinstance(data,dict) or data.get('id')!=character.work_id:raise ValueError('作品别名元数据的身份不一致')
            identity['work_aliases']=metadata_names(data);identity['work_loaded']=True
        identity.pop('error',None);identity.pop('retry_after',None)
    except ValueError as exc:
        identity['error']=str(exc)[:200]
        identity['retry_after']=(timezone.now()+timedelta(days=1)).isoformat()
    stats['identity']=identity;character.source_stats=stats
