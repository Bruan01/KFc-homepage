"""Two explicit administrator decisions around a version-bound generation/review job."""
import json
from datetime import date

from django.db import transaction
from django.db.models import F

from .catalog import THEME_IDS, validate_profile, normalize_draft
from .models import Character, CharacterDiscovery, PersonalityJob, PersonalitySettings, timestamp
from .review import profile_fingerprint, readiness, review_profile, source_fingerprint
from .evidence import missing_dimensions, supplement
from .character_rubric import VERSION as CHARACTER_RUBRIC_VERSION
from .approvals import retained_approvals
from .questions import DIMENSIONS


def selected_ids(value, maximum=120):
    if not isinstance(value, list) or not 1 <= len(value) <= maximum or any(type(pk) is not int or pk <= 0 for pk in value):
        raise ValueError(f"请选择 1–{maximum} 个角色")
    return list(dict.fromkeys(value))


def validate_versions(value, ids):
    if not isinstance(value, dict) or any(key not in {str(pk) for pk in ids} or type(rev) is not int or rev < 0 for key, rev in value.items()):
        raise ValueError("列表版本无效，请刷新后重试")
    return value


def queue_profiles(ids, actor, *, versions=None, regenerate=False, review_only=False, feedback="", keep_classics=False):
    result = {"queued": 0, "skipped": []}
    versions = versions or {}
    with transaction.atomic():
        Character.objects.filter(pk__in=ids).update(revision=F("revision"))
        rows = {row.pk: row for row in Character.objects.filter(pk__in=ids)}
        for pk in ids:
            row = rows.get(pk)
            reason = ""
            if not row:
                reason = "角色不存在"
            elif str(pk) in versions and row.revision != versions[str(pk)]:
                reason = "资料已修改，请刷新"
            elif row.status in {"approved", "excluded"}:
                reason = "已发布或已排除的角色不会重新生成"
            elif not regenerate and not review_only and row.status != "candidate":
                reason = "已有档案，不重复生成"
            elif PersonalityJob.objects.filter(character=row, kind="profile", status__in=["queued", "processing"]).exists():
                reason = "已有生成或复核任务"
            if reason:
                result["skipped"].append({"id": pk, "reason": reason})
                continue
            revision = row.revision + 1
            classic = row.classic or (keep_classics and row.classic_candidate)
            approvals=retained_approvals(row)
            checkpoint={}
            if approvals:
                targets=[key for key in DIMENSIONS if key not in approvals]
                checkpoint={'source':source_fingerprint(row),'draft':normalize_draft(row.profile),'dimension_approvals':approvals,
                    'locked':{key:record['dimension'] for key,record in approvals.items()},
                    'accepted_reviews':{key:record['review'] for key,record in approvals.items()},'targets':targets,
                    'needs_regeneration':bool(targets),'reused_dimensions':list(approvals),
                    'last_review':{key:row.profile_check[key] for key in ['identity','dimensions','issues'] if key in row.profile_check}}
                if row.profile_check.get('status')=='passed' and row.profile_check.get('fingerprint')==profile_fingerprint(row):
                    checkpoint['review']=row.profile_check
            Character.objects.filter(pk=pk, revision=row.revision).update(status="draft", classic=classic, revision=revision,
                profile_check={"status": "queued", "held": False})
            PersonalityJob.objects.create(kind="profile", character=row, requested_by=actor, parameters={
                "revision": revision, "review_only": review_only, "feedback": feedback,"pipeline":CHARACTER_RUBRIC_VERSION},checkpoint=checkpoint)
            result["queued"] += 1
    return result


def batch_decision(ids, action, actor, versions):
    result = {"changed": 0, "skipped": []}
    settings = PersonalitySettings.objects.filter(pk=1).first() or PersonalitySettings()
    with transaction.atomic():
        Character.objects.filter(pk__in=ids).update(revision=F("revision"))
        rows = {row.pk: row for row in Character.objects.filter(pk__in=ids)}
        for pk in ids:
            row = rows.get(pk)
            reason = "角色不存在" if not row else "资料已修改，请刷新" if str(pk) in versions and versions[str(pk)] != row.revision else ""
            if reason:
                result["skipped"].append({"id": pk, "reason": reason}); continue
            changes = {"revision": F("revision")+1}
            live = PersonalityJob.objects.filter(character=row, kind="profile", status__in=["queued", "processing"])
            if action == "approve":
                check = readiness(row, recent_years=settings.recent_years, current_year=date.today().year)
                if row.status != "draft" or live.exists() or not check["ready"]:
                    reason = "已有任务，请等待" if live.exists() else "；".join(check["problems"]) or "角色不在待发布列表"
                else:
                    cleaned = validate_profile(row.profile, row)
                    review = {**row.profile_check, "held": False}
                    changes.update(status="approved", profile=cleaned, profile_check=review, reviewed_by=actor, reviewed_at=timestamp())
            elif action == "exclude":
                changes.update(status="excluded")
                live.update(status="cancelled", claim_token="", error="管理员已排除此角色", updated_at=timestamp())
            elif action == "restore":
                if row.status != "excluded":
                    reason = "角色未被排除"
                else:
                    changes.update(status="draft" if row.profile else "candidate", profile_check={**row.profile_check, "held": False})
            elif action in {"hold", "release"}:
                if row.status != "draft" or live.exists():
                    reason = "请等待生成完成后再调整发布状态"
                else:
                    changes["profile_check"] = {**row.profile_check, "held": action == "hold", "held_by": actor}
            else:
                raise ValueError("批量操作无效")
            if reason:
                result["skipped"].append({"id": pk, "reason": reason}); continue
            if Character.objects.filter(pk=pk, revision=row.revision).update(**changes):
                result["changed"] += 1
    return result


def run_profile_job(job, settings, *, complete, draft, owned):
    if job.parameters.get('pipeline')==CHARACTER_RUBRIC_VERSION:
        from .profile_pipeline import run
        return run(job,settings,complete=complete,draft=draft,owned=owned,retrieve=supplement)
    row = Character.objects.get(pk=job.character_id)
    expected = job.parameters.get("revision", row.revision)
    if row.status in {"approved", "excluded"} or row.revision != expected:
        raise ValueError("角色已被其它操作更新，已停止旧任务")
    if not settings.ai_enabled:
        raise ValueError("AI 服务已暂停，角色资料已保留")
    source = source_fingerprint(row)
    cached = job.checkpoint if job.checkpoint.get("source") == source else {}
    if job.parameters.get("review_only"):
        profile = row.profile
    elif "draft" in cached:
        profile = cached["draft"]
    else:
        owned.update(phase="profile_generation", updated_at=timestamp())
        profile = draft(row, settings, job.parameters.get("feedback", ""))
    checkpoint = {**cached, "source": source}

    def heartbeat(phase="evidence_search"):
        if not owned.update(phase=phase, updated_at=timestamp()):
            raise ValueError("任务已取消")
        PersonalitySettings.objects.filter(pk=1).update(worker_last_seen_at=timestamp())
        if not Character.objects.filter(pk=row.pk, revision=expected, status="draft").exists():
            raise ValueError("角色资料已修改，已停止旧任务")

    def save_draft(value):
        value = normalize_draft(value)
        if not isinstance(value, dict) or len(json.dumps(value)) > 50000:
            raise ValueError("角色草稿格式无效或内容过大")
        next_checkpoint = {**checkpoint, "draft": value, "needs_regeneration": False}
        theme = value.get("theme")
        with transaction.atomic():
            if not owned.update(phase="profile_review", checkpoint=next_checkpoint, updated_at=timestamp()):
                raise ValueError("任务已取消")
            if not Character.objects.filter(pk=row.pk, revision=expected).exclude(status__in=["approved", "excluded"]).update(profile=value,
                theme=theme if isinstance(theme, str) and theme in THEME_IDS else row.theme, status="draft", profile_check={"status": "reviewing"}):
                raise ValueError("角色资料已修改，旧草稿不会覆盖新内容")
        checkpoint.update(next_checkpoint)
        row.profile = value
        return value

    if cached.get("needs_regeneration"):
        heartbeat("profile_generation")
        profile = draft(row, settings, job.parameters.get("feedback", ""))
    profile = save_draft(profile)
    heartbeat("profile_review")
    check = review_profile(row, profile, settings, complete)
    if check["status"] == "needs_sources" and check.get("category") != "format_error" and not job.parameters.get("review_only") and not checkpoint.get("evidence_attempted"):
        heartbeat()
        checkpoint["evidence_attempted"] = True
        owned.update(checkpoint=checkpoint, updated_at=timestamp())
        evidence = supplement(row, settings, missing_dimensions(profile, row, check), heartbeat=heartbeat)
        metadata = {key: value for key, value in evidence.items() if key not in {"sources", "cache"}}
        metadata['added'] = len(evidence['sources'])
        with transaction.atomic():
            if not owned.update(checkpoint={**checkpoint, "evidence": metadata}, updated_at=timestamp()):
                raise ValueError("任务已取消")
            if not Character.objects.filter(pk=row.pk, revision=expected, status="draft").update(
                extra_sources=[*row.extra_sources, *evidence['sources']], evidence_cache=evidence['cache'],source_stats=row.source_stats):
                raise ValueError("角色资料已修改，搜索结果不会覆盖新内容")
            row.extra_sources = [*row.extra_sources, *evidence['sources']]
            row.evidence_cache = evidence['cache']
            checkpoint.update(source=source_fingerprint(row), evidence=metadata, needs_regeneration=bool(evidence['sources']))
            owned.update(checkpoint=checkpoint, updated_at=timestamp())
        if evidence['sources']:
            heartbeat("profile_generation")
            profile = save_draft(draft(row, settings, job.parameters.get("feedback", "")))
            heartbeat("profile_review")
            check = review_profile(row, profile, settings, complete)
    if checkpoint.get("evidence"):
        check['evidence'] = checkpoint['evidence']
    if Character.objects.filter(name=row.name, work_id=row.work_id).exclude(source_id=row.source_id).exists():
        check["status"] = "needs_sources"
        check["issues"].append("同一作品中存在同名角色条目，请确认是否重复")
    with transaction.atomic():
        if not owned.update(status="completed", phase="profile_reviewed", checkpoint={}, error="", result={"character_id": row.pk, "review": check["status"]}, updated_at=timestamp()):
            return
        if not Character.objects.filter(pk=row.pk, status="draft", revision=expected).update(profile_check=check):
            raise ValueError("角色资料已修改，复核结果不会覆盖新内容")


def mark_profile_error(job, error):
    query = Character.objects.filter(pk=job.character_id, status__in=["candidate", "draft"])
    if "revision" in job.parameters:
        query = query.filter(revision=job.parameters["revision"])
    category='output_limit' if any(term in error for term in ['输出被截断','输出达到上限']) else 'reference_error' if '证据编号' in error else 'task_error'
    checkpoint=PersonalityJob.objects.filter(pk=job.pk).values_list('checkpoint',flat=True).first() or {}
    query.update(status="draft", profile_check={"status": "error", "category":category,"issues": [error],
        "dimension_approvals":checkpoint.get('dimension_approvals',{})})
