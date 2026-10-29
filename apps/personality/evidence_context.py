"""Bounded prompt excerpts drawn from a larger persistent source pool."""
from .character_rubric import RUBRIC,evidence_inventory,evidence_registry
from .policy import MAX_CONTEXT_SOURCES,MIN_CONTEXT_SOURCES,MAX_CONTEXT_CHARS
from .questions import DIMENSIONS


def compact_dimension(row):
    result={key:row[key] for key in ['level','reason','evidence_id','supporting_evidence_ids'] if key in row}
    if not row.get('evidence_id'):result['quote']=row.get('quote','')
    if not row.get('supporting_evidence_ids') and row.get('supporting_quotes'):result['supporting_quotes']=row['supporting_quotes']
    return result


def analysis_context(character,targets=None):
    targets=[key for key in (targets or DIMENSIONS) if key in DIMENSIONS]
    inventory=evidence_inventory(character);registry=evidence_registry(character)
    by_source={}
    for item in registry.values():by_source.setdefault(item['source_url'],[]).append(item)
    scores={}
    for url,items in by_source.items():
        per_dimension={key:max((sum(word.casefold() in item['quote'].casefold() for word in RUBRIC[key]['keywords']) for item in items),default=0) for key in targets}
        scores[url]=per_dimension
    selected=[character.source_url] if character.source_url in by_source else []
    uncovered={key for key in targets if not selected or not scores[selected[0]][key]}
    minimum=min(MIN_CONTEXT_SOURCES,len(by_source))
    while len(selected)<MAX_CONTEXT_SOURCES:
        remaining=[url for url in by_source if url not in selected]
        if not remaining:break
        best=max(remaining,key=lambda url:(sum(scores[url][key]>0 for key in uncovered),sum(scores[url].values())))
        relevance=sum(scores[best].values())
        if len(selected)>=minimum and not relevance:break
        selected.append(best);uncovered-={key for key,value in scores[best].items() if value}
    identity_excerpt=character.source_text[:400]
    catalog=[];allocation=(MAX_CONTEXT_CHARS-len(identity_excerpt))//max(1,len(selected))
    selected_ids=set()
    for url in selected:
        items=by_source[url]
        # Pick evidence covering different missing dimensions before additional similar snippets.
        ordered=[];pending=set(targets)
        for _ in range(4):
            candidates=[item for item in items if item['id'] not in {old['id'] for old in ordered}]
            if not candidates:break
            def item_score(item):
                covered={key for key in targets if any(word.casefold() in item['quote'].casefold() for word in RUBRIC[key]['keywords'])}
                return len(covered&pending),len(covered)
            item=max(candidates,key=item_score);ordered.append(item)
            pending-={key for key in targets if any(word.casefold() in item['quote'].casefold() for word in RUBRIC[key]['keywords'])}
        used=0
        for item in ordered:
            if used+len(item['quote'])>allocation:continue
            catalog.append(item);selected_ids.add(item['id']);used+=len(item['quote'])
    for row in inventory['dimensions'].values():
        # Candidate IDs remain short; quote text appears only once in evidence_catalog.
        candidates=[item for item in catalog if item['id'] in {old['id'] for old in row['candidates']}]
        if not candidates:
            candidates=catalog[:2]
        row['candidates']=[{'id':item['id'],'source_url':item['source_url']} for item in candidates[:4]]
    documents=[{'url':url,'excerpt_ids':[item['id'] for item in catalog if item['source_url']==url]} for url in selected]
    return {'evidence_table':inventory,'evidence_catalog':catalog,'source_documents':documents,
            'identity_source':{'url':character.source_url,'excerpt':identity_excerpt,'character':character.name,'work':character.work_name},
            'material_selection':{'available_sources':len(by_source),'selected_sources':len(selected),'excerpt_characters':sum(len(item['quote']) for item in catalog)+len(identity_excerpt),'targets':targets}}
