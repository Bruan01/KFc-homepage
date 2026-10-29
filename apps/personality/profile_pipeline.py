"""Evidence first, bounded targeted repairs, six supported dimensions to publish."""
import copy
import json

from django.db import transaction

from .catalog import THEME_IDS, normalize_draft
from .character_rubric import VERSION, evidence_inventory, empty_dimensions, resolve_profile_references
from .evidence import evidence_connection, missing_dimensions, supplement
from .models import Character, PersonalitySettings, timestamp
from .questions import DIMENSIONS
from .review import review_profile, profile_fingerprint, source_fingerprint
from .approvals import update_approvals,validate_records
from .policy import MAX_REPAIR_ROUNDS

def run(job,settings,*,complete,draft,owned,retrieve=supplement):
    row=Character.objects.get(pk=job.character_id)
    expected=job.parameters.get('revision',row.revision)
    if row.status in {'approved','excluded'} or row.revision!=expected:
        raise ValueError('角色已被其它操作更新，已停止旧任务')
    if not settings.ai_enabled:
        raise ValueError('AI 服务已暂停，角色资料已保留')
    cp=copy.deepcopy(job.checkpoint) if job.checkpoint.get('source')==source_fingerprint(row) else {}
    cp.update(source=source_fingerprint(row),pipeline=VERSION)
    cp.setdefault('rounds',0);cp.setdefault('locked',{});cp.setdefault('searches',[])
    cp['dimension_approvals']=validate_records(row,cp.get('dimension_approvals',{}),cp.get('draft',row.profile))
    review_only=job.parameters.get('review_only') is True

    def heartbeat(phase='evidence_search'):
        if not owned.update(phase=phase,updated_at=timestamp()):
            raise ValueError('任务已取消')
        PersonalitySettings.objects.filter(pk=1).update(worker_last_seen_at=timestamp())
        if not Character.objects.filter(pk=row.pk,revision=expected).exclude(status__in=['approved','excluded']).exists():
            raise ValueError('角色资料已修改，已停止旧任务')

    def persist(phase,**changes):
        with transaction.atomic():
            if not owned.update(phase=phase,checkpoint=cp,updated_at=timestamp()):
                raise ValueError('任务已取消')
            if changes and not Character.objects.filter(pk=row.pk,revision=expected).exclude(status__in=['approved','excluded']).update(**changes):
                raise ValueError('角色资料已修改，旧结果不会覆盖新内容')

    def collect(targets):
        heartbeat()
        cp['evidence_attempted']=True
        cp['rounds']+=1
        persist('evidence_search')
        evidence=retrieve(row,settings,targets,heartbeat=heartbeat,round_number=cp['rounds']-1)
        cp['searches'].append({**{key:value for key,value in evidence.items() if key not in {'sources','cache'}},'added':len(evidence['sources']),'targets':targets})
        row.extra_sources=[*row.extra_sources,*evidence['sources']]
        row.evidence_cache=evidence['cache']
        cp['source']=source_fingerprint(row)
        cp.pop('review',None)
        persist('evidence_inventory',extra_sources=row.extra_sources,evidence_cache=row.evidence_cache,source_stats=row.source_stats)
        return evidence

    def generate(targets):
        heartbeat('targeted_revision' if cp.get('draft') else 'profile_generation')
        row._revision_targets=list(targets)
        row._locked_dimensions=copy.deepcopy(cp['locked'])
        row._dimension_review=cp.get('last_review',{})
        cp['needs_regeneration']=True;cp['targets']=list(targets)
        persist('targeted_revision' if cp.get('draft') else 'profile_generation')
        value=resolve_profile_references(normalize_draft(draft(row,settings,job.parameters.get('feedback',''))),row)
        if not isinstance(value,dict) or not isinstance(value.get('dimensions'),dict) or len(json.dumps(value))>50000:
            raise ValueError('角色草稿格式无效或内容过大')
        # The writer may omit unchanged dimensions in a targeted patch.
        base=copy.deepcopy(cp.get('draft',{}).get('dimensions',{}))
        base.update({key:item for key,item in value['dimensions'].items() if key in targets})
        base.update(copy.deepcopy(cp['locked']))
        value={**copy.deepcopy(cp.get('draft',{})),**value}
        value['dimensions']=base
        cp.update(draft=value,needs_regeneration=False)
        cp.pop('review',None)
        row.profile=value
        theme=value.get('theme')
        persist('profile_review',profile=value,status='draft',theme=theme if isinstance(theme,str) and theme in THEME_IDS else row.theme,profile_check={'status':'reviewing'})
        return value

    if not cp.get('inventory_prepared') and not review_only:
        heartbeat('evidence_inventory')
        inventory=evidence_inventory(row)
        targets=[key for key in empty_dimensions(inventory) if key not in cp['locked']]
        # This inventory is a retrieval aid; keyword hits do not constitute approval.
        if targets and evidence_connection(settings) is not None and cp['rounds']<MAX_REPAIR_ROUNDS:
            evidence=collect(targets)
            if evidence['sources'] and cp.get('draft'):
                cp['needs_regeneration']=True;cp['targets']=[key for key in DIMENSIONS if key not in cp['locked']]
        cp['inventory_prepared']=True
        persist('evidence_inventory')
    if review_only:
        profile=normalize_draft(row.profile)
        cp['draft']=profile
    elif cp.get('needs_regeneration') or 'draft' not in cp:
        profile=generate(cp.get('targets',list(DIMENSIONS)))
    else:
        profile=cp['draft'];row.profile=profile

    while True:
        heartbeat('profile_review')
        cached=cp.get('review',{})
        if cached.get('fingerprint')==profile_fingerprint(row,profile):
            check=cached
        else:
            row._locked_reviews=cp.get('accepted_reviews',{})
            check=review_profile(row,profile,settings,complete)
            cp['review']=check
            persist('profile_review')
        cp['dimension_approvals']=update_approvals(row,profile,check,cp['dimension_approvals'])
        if cp.get('repair_baseline') and check['status']!='passed':
            progress=[sum(item.get('verdict')=='supported' for item in check.get('dimensions',[])),
                      len(DIMENSIONS)-len(missing_dimensions(profile,row,check))]
            prior_counters={(item['key'],item.get('source_quote')) for item in cp.get('last_review',{}).get('dimensions',[]) if item.get('verdict')=='contradicted'}
            new_counter=any(item.get('verdict')=='contradicted' and (item['key'],item.get('source_quote')) not in prior_counters for item in check.get('dimensions',[]))
            if not cp.get('last_new_evidence') and not new_counter and progress<=cp['repair_baseline']:
                cp['stop_reason']='no_progress'
                break
        if check['status']=='passed' or check.get('category')=='format_error' or review_only:
            break
        # Identity mismatch is not repaired by changing scores.
        if check.get('identity',{}).get('verdict') in {'mismatch','uncertain'}:
            break
        if cp['rounds']>=MAX_REPAIR_ROUNDS:
            cp['stop_reason']='budget_exhausted'
            break
        targets=missing_dimensions(profile,row,check)
        cp['last_review']=copy.deepcopy(check)
        for item in check.get('dimensions',[]):
            key=item['key']
            if item['verdict']=='supported' and key in profile['dimensions']:
                cp['locked'][key]=copy.deepcopy(profile['dimensions'][key])
                cp.setdefault('accepted_reviews',{})[key]=copy.deepcopy(item)
            elif item['verdict']=='contradicted':
                cp['locked'].pop(key,None)
                cp.setdefault('accepted_reviews',{}).pop(key,None)
        # A locked dimension can only be reopened by actual contradictory evidence.
        for key in targets:
            cp['locked'].pop(key,None)
            cp.setdefault('accepted_reviews',{}).pop(key,None)
        cp['needs_regeneration']=True;cp['targets']=targets
        cp['repair_baseline']=[sum(item.get('verdict')=='supported' for item in check.get('dimensions',[])),
                               len(DIMENSIONS)-len(targets)]
        persist('evidence_search')
        evidence=collect(targets)
        cp['last_new_evidence']=bool(evidence['sources'])
        if not evidence['sources'] and not check.get('dimensions'):
            cp['needs_regeneration']=False
            cp['stop_reason']='no_new_evidence'
            persist('profile_review')
            break
        # Existing evidence can repair an overbroad interpretation even without a new page.
        profile=generate(targets)

    check=copy.deepcopy(check)
    check['rubric_version']=VERSION
    check['evidence_table']=evidence_inventory(row)
    searches=cp['searches']
    if searches:
        check['evidence']={'status':searches[-1]['status'],'added':sum(item['added'] for item in searches),
            'queries':sum(item['queries'] for item in searches),'fetched':sum(item['fetched'] for item in searches),
            'cached':sum(item['cached'] for item in searches),'rounds':len(searches),'note':searches[-1]['note']}
    check['repair_rounds']=cp['rounds']
    check['dimension_approvals']=cp['dimension_approvals']
    check['retained_dimensions']=list(cp['dimension_approvals'])
    check['reused_dimensions']=[key for key in cp.get('reused_dimensions',[]) if key in cp['locked']]
    check['stop_reason']='passed' if check['status']=='passed' else cp.get('stop_reason','needs_evidence')
    if Character.objects.filter(name=row.name,work_id=row.work_id).exclude(source_id=row.source_id).exists():
        check['status']='needs_sources';check['issues'].append('同一作品中存在同名角色条目，请确认是否重复')
    with transaction.atomic():
        if not owned.update(status='completed',phase='profile_reviewed',checkpoint={},error='',
            result={'character_id':row.pk,'review':check['status'],'pipeline':VERSION,'repair_rounds':cp['rounds'],'reused_dimensions':len(check['reused_dimensions'])},updated_at=timestamp()):
            return
        if not Character.objects.filter(pk=row.pk,revision=expected).exclude(status__in=['approved','excluded']).update(status='draft',profile=profile,profile_check=check):
            raise ValueError('角色资料已修改，复核结果不会覆盖新内容')
