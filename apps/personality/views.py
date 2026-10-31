import json
from datetime import date,timedelta

from django.db import IntegrityError, transaction
from django.db.models import F, Q
from django.http import Http404, HttpResponse
from django.shortcuts import redirect
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.core.http import read_json
from apps.core.pages import _file_response, _safe_static_path
from apps.core.permissions import get_admin_context, require_admin, require_user
from apps.core.responses import json_error, json_ok
from .catalog import THEME_IDS, safe_image, validate_profile, normalize_draft
from .character_rubric import VERSION as CHARACTER_RUBRIC_VERSION
from .policy import MAX_SOURCES
from .approvals import retained_approvals,validate_records
from .models import Assessment, AnalysisCall, Character, DailyUsage, OperationalAlert, PersonalityJob, PersonalitySettings, QuestionFeedback, timestamp
from .provider import complete_json, encrypt_key, list_models
from .configuration import ai_service_status, parse_config, public_config, remember_connection_check
from .questions import VERSION, initial_steps
from .services import advance, config, eligible_characters, validate_answers
from .transfer import FILTER_LIMITS, export_catalog, import_catalog
from .images import character_image_bytes
from .review import profile_fingerprint, readiness
from .workflow import selected_ids, validate_versions, queue_profiles, batch_decision
from . import followups


@ensure_csrf_cookie
@require_GET
def page(request, kind="home", assessment_id=None):
    if kind in {"test", "report", "analysis"} and not request.user.is_authenticated:
        return redirect("/login?next=" + request.path)
    if kind in {"report","analysis"} and not Assessment.objects.filter(pk=assessment_id, user=request.user).exists():
        raise Http404
    if kind in {"admin", "admin_model", "admin_analysis", 'operations'}:
        admin = get_admin_context(request)
        if not admin:
            return redirect("/login?next=/admin/personality")
        if admin["admin_level"] < 3:
            return HttpResponse("需要 L3 管理员权限", status=403)
        if kind in {'admin_analysis', 'operations'} and not admin['is_super']:
            return HttpResponse('需要主管理员权限',status=403)
    filename = {"home": "index", "test": "test", "report": "report", "admin": "admin", "admin_model": "admin-model",'analysis':'analysis','admin_analysis':'analysis', 'operations':'operations'}[kind]
    response = _file_response(_safe_static_path(f"personality/{filename}.html"), request=request, inject_versions=True)
    if kind != "home":
        response["Cache-Control"] = "private, no-store"
    return response


@require_GET
def availability(request):
    settings = config()
    ai_ready, service_message = ai_service_status(settings)
    cast = []
    works = set()
    for row in eligible_characters().exclude(image_url="")[:40]:
        if row.work_id in works:
            continue
        works.add(row.work_id)
        cast.append({"id": row.pk, "name": row.name, "work": row.work_name, "theme": row.theme, "image": f"/api/personality/cast/{row.pk}/image"})
        if len(cast) >= 4:
            break
    response = json_ok({"enabled": settings.enabled, "ai_available": ai_ready, 'ai_required': True,
                    'service_message': service_message, 'can_start': settings.enabled and ai_ready,
                    "characters_ready": eligible_characters().count(), "question_version": VERSION, "cast": cast})
    response['Cache-Control'] = 'no-store'
    return response


@require_GET
def cast_image(request, character_id):
    row = eligible_characters().filter(pk=character_id).first()
    if not row:
        raise Http404
    try:
        raw = character_image_bytes(row.image_url)
    except (OSError, ValueError):
        raise Http404 from None
    response = HttpResponse(raw, content_type="image/webp")
    response["Cache-Control"] = "public, max-age=86400"
    response["X-Content-Type-Options"] = "nosniff"
    return response


def assessment_payload(row):
    payload = {"id": str(row.pk), "status": row.status, "revision": row.revision, "step_index": row.step_index,
            "step": row.steps[row.step_index] if row.step_index < len(row.steps) else None,
            "step_count": len(row.steps), "answers": row.answers, "created_at": row.created_at, "updated_at": row.updated_at,
            "ai_consent": row.ai_consent, 'feedback_question_ids': list(QuestionFeedback.objects.filter(assessment=row).values_list('question_id', flat=True))}
    if payload['step'] and payload['step'].get('ai_followup', {}).get('state') in {'pending', 'unavailable'}:
        from .operations import report_signal
        job = PersonalityJob.objects.filter(assessment=row, kind='followup').order_by('-created_at').first()
        payload['task_notice'] = report_signal(job, config())['notice']
    return payload


@require_user
@require_http_methods(["GET", "POST"])
def assessments(request):
    if request.method == "GET":
        return json_ok({"items": [{"id": str(row.pk), "status": row.status, "step_index": row.step_index, "created_at": row.created_at,
                                   "type": row.report.get("type", ""), "title": row.report.get("title", "")} for row in Assessment.objects.filter(user=request.user).order_by("-created_at")[:40]]})
    try:
        settings = config()
        if not settings.enabled:
            return json_error("心映暂时暂停新测评，已有档案仍可查看", status=503)
        ai_ready, service_message = ai_service_status(settings)
        if not ai_ready:
            return json_error(service_message, status=503)
        body = read_json(request)
        consent = body.get("ai_consent", False)
        if type(consent) is not bool:
            raise ValueError("授权状态无效")
        if not consent:
            return json_error('请先同意 AI 分析，再开始测评', status=400)
        if Assessment.objects.filter(user=request.user, status="active").count() >= 10:
            return json_error("请先继续或删除未完成的测评", status=429)
        previous = Assessment.objects.filter(user=request.user).order_by("-created_at").first()
        previous_ids = [q["id"] for step in previous.steps for q in step["questions"]] if previous else []
        row = Assessment(user=request.user, version=VERSION, ai_consent=consent)
        row.steps = initial_steps(seed=str(row.pk), previous_ids=previous_ids)
        row.steps[0]['followup_policy'] = 'bank-v1'
        row.save()
        return json_ok(assessment_payload(row), status=201)
    except ValueError as exc:
        return json_error(str(exc))


@require_user
@require_http_methods(["GET", "POST", "DELETE"])
def assessment_detail(request, assessment_id):
    row = Assessment.objects.filter(pk=assessment_id, user=request.user).first()
    if not row:
        return json_error("档案不存在", status=404)
    if request.method == "GET":
        response = json_ok(assessment_payload(row)); response['Cache-Control'] = 'private, no-store'
        return response
    if request.method == "DELETE":
        from apps.notifications.models import Notification
        with transaction.atomic():
            Notification.objects.filter(recipient_id=row.user_id, link=f'/personality/report/{row.pk}').update(link='')
            row.delete()
        return json_ok()
    try:
        body = read_json(request)
        if type(body.get("revision")) is not int or body["revision"] != row.revision:
            return json_error("进度已在其它页面更新，请重新载入", status=409)
        previous_status = row.status
        cancel_followup = False
        if body.get('action') == 'authorize_ai':
            if row.status not in {'active', 'ready'} or body.get('ai_consent') is not True:
                return json_error('请先同意 AI 分析后继续', status=400)
            if not ai_service_status(config())[0]:
                return json_error('AI 分析服务暂不可用，原有回答已保存，请稍后继续', status=503)
            changed = Assessment.objects.filter(pk=row.pk, user=request.user, revision=row.revision, status=previous_status).update(
                ai_consent=True, revision=F('revision')+1, updated_at=timestamp())
            if not changed:
                return json_error('进度已在其它页面更新，请重新载入', status=409)
            row.refresh_from_db()
            return json_ok(assessment_payload(row))
        if row.status != "active" and not (row.status == "ready" and body.get("action") == "back"):
            return json_error("此测评已提交，请新建一次探索", status=409)
        if body.get('action') == 'retry_followup':
            settings = config()
            if not row.ai_consent or not ai_service_status(settings)[0]:
                return json_error('追问服务暂不可用，原有回答已保存，请稍后重试', status=503)
            with transaction.atomic():
                if not Assessment.objects.filter(pk=row.pk, revision=row.revision, status='active').update(updated_at=timestamp()):
                    return json_error('进度已在其它页面更新，请重新载入', status=409)
                row.refresh_from_db()
                followups.retry_job(row, settings)
            return json_ok(assessment_payload(row))
        if body.get("action") == "back":
            row.status = "active"
            row.step_index = max(0, row.step_index - 1)
            while row.step_index > 0 and not row.steps[row.step_index]['questions']:
                row.step_index -= 1
            cancel_followup = True
        elif body.get('action') == 'skip_followup':
            if row.status != 'active' or row.step_index >= len(row.steps) or 'ai_followup' not in row.steps[row.step_index]:
                return json_error('当前没有等待中的补充追问', status=409)
            step = row.steps[row.step_index]
            for question in step['questions']:
                row.answers[question['id']] = {**row.answers.get(question['id'], {'value': None, 'note': ''}), 'skipped': True}
            row.steps[row.step_index] = {**step, 'ai_followup': {**step['ai_followup'], 'state': 'skipped'}}
            row.step_index = len(row.steps); row.status = 'ready'; cancel_followup = True
        else:
            finish = body.get("complete", False)
            if type(finish) is not bool:
                raise ValueError("提交状态无效")
            if followups.pending(row):
                if finish or body.get('answers'):
                    return json_error('正在准备补充追问，也可以选择跳过', status=409)
                return json_ok(assessment_payload(row))
            cleaned = validate_answers(row.steps[row.step_index], body.get("answers"), complete=finish)
            cancel_followup = followups.trim_changed_followups(row, cleaned)
            row.answers = {**row.answers, **cleaned}
            if finish:
                advance(row)
        with transaction.atomic():
            changed = Assessment.objects.filter(pk=row.pk, user=request.user, status=previous_status, revision=body["revision"]).update(
                step_index=row.step_index, steps=row.steps, answers=row.answers, status=row.status, revision=F("revision") + 1, updated_at=timestamp())
            if not changed:
                return json_error("进度已在其它页面更新，请重新载入", status=409)
            if cancel_followup:
                PersonalityJob.objects.filter(assessment=row, kind='followup', status__in=['queued','processing']).update(status='cancelled', claim_token='', updated_at=timestamp())
                from .operations import resolve_alerts
                resolve_alerts(row.pk)
            row.refresh_from_db()
            followups.queue_pending(row, config())
        row.refresh_from_db()
        return json_ok(assessment_payload(row))
    except ValueError as exc:
        return json_error(str(exc))


@require_user
@require_POST
def submit_report(request, assessment_id):
    try:
        body = read_json(request)
        if 'ai_consent' in body and type(body['ai_consent']) is not bool:
            raise ValueError('授权状态无效')
        with transaction.atomic():
            # First operation is a write: SQLite cannot upgrade concurrent read
            # transactions safely, and select_for_update has no effect there.
            claimed = Assessment.objects.filter(pk=assessment_id, user=request.user, status__in=["ready", "failed"]).update(status="queued", updated_at=timestamp())
            row = Assessment.objects.filter(pk=assessment_id, user=request.user).first()
            if not row:
                return json_error("档案不存在", status=404)
            if not claimed and row.status in {"completed", "queued", "processing"}:
                return json_ok({"id": str(row.pk), "status": row.status})
            if not claimed:
                return json_error("请先完成测评", status=409)
            settings = config()
            if not (row.ai_consent or body.get('ai_consent') is True):
                transaction.set_rollback(True)
                return json_error('请先同意使用已有回答进行 AI 分析，无需重新答题', status=400)
            if not ai_service_status(settings)[0]:
                transaction.set_rollback(True)
                return json_error('AI 分析服务暂不可用，回答已保存，请稍后重试', status=503)
            previous = PersonalityJob.objects.filter(kind='report', assessment=row, status='failed').exclude(
                Q(parameters__has_key='character_only') & Q(parameters__character_only=True)).exclude(
                Q(parameters__has_key='heartline_only') & Q(parameters__heartline_only=True)).order_by('-created_at').first()
            day = timezone.localdate().isoformat()
            # A failed normal report already reserved this assessment's report
            # allowance. Reuse it even across days; retries are not new reports.
            if previous is None:
                usage, _ = DailyUsage.objects.get_or_create(user=request.user, day=day)
                if not DailyUsage.objects.filter(pk=usage.pk, reports__lt=settings.daily_reports_per_user).update(reports=F("reports") + 1):
                    transaction.set_rollback(True)
                    return json_error("今天的报告生成次数已用完，请明天再试", status=429)
            PersonalityJob.objects.create(kind="report", assessment=row, requested_by=request.user.username,
                parameters={"ai": True, 'quota_reserved': True}, checkpoint=previous.checkpoint if previous else {})
            from .operations import resolve_alerts
            resolve_alerts(row.pk)
            row.ai_consent = True
            row.status = "queued"; row.updated_at = timestamp(); row.save(update_fields=["status", "updated_at", 'ai_consent'])
        return json_ok({"id": str(row.pk), "status": row.status}, status=202)
    except ValueError as exc:
        return json_error(str(exc))


@require_user
@require_GET
def report_data(request, assessment_id):
    row = Assessment.objects.filter(pk=assessment_id, user=request.user).first()
    if not row:
        return json_error("档案不存在", status=404)
    if row.status != "completed":
        job = PersonalityJob.objects.filter(assessment=row).order_by("-created_at").first()
        from .operations import report_signal
        signal = report_signal(job, config())
        return json_ok({"id": str(row.pk), "status": row.status, 'needs_ai_consent': not row.ai_consent,
                        "error": signal['notice'] if job and job.status == 'failed' else '', "phase": job.phase if job else "", **signal})
    match_job = PersonalityJob.objects.filter(assessment=row, parameters__character_only=True).order_by("-created_at").first() if not row.report.get("character") else None
    complete_dimensions=len(row.report.get('dimensions',[]))==6 and all(d.get('value') is not None for d in row.report['dimensions'])
    has_pool=eligible_characters().exists()
    missing_reason='' if row.report.get('character') else ('这份档案有维度回答不足，暂不能进行完整角色对照。' if not complete_dimensions else '角色库暂时没有可用档案，准备好后可用原答案补全。' if not has_pool else '这份档案尚未匹配动漫角色，可以用原答案补全角色共鸣。')
    return json_ok({"id": str(row.pk), "status": row.status, "report": row.report,
        "can_add_character": not row.report.get("character") and complete_dimensions and has_pool,'character_missing_reason':missing_reason,
        "character_match_status": match_job.status if match_job else "", "character_match_error": match_job.error if match_job and match_job.status == "failed" else ""})


@require_user
@require_POST
def complete_character(request, assessment_id):
    try:
        with transaction.atomic():
            Assessment.objects.filter(pk=assessment_id, user=request.user, status="completed").update(updated_at=F("updated_at"))
            row = Assessment.objects.filter(pk=assessment_id, user=request.user).first()
            if not row:
                return json_error("档案不存在", status=404)
            if row.status != "completed":
                return json_error("请先等待人格报告完成", status=409)
            if row.report.get("character"):
                return json_ok({"status": "completed"})
            if not eligible_characters().exists():
                return json_error("角色资料正在准备中", status=409)
            live = PersonalityJob.objects.filter(assessment=row, status__in=["queued", "processing"])
            if live.exists():
                return json_ok({"status": live.first().status}, status=202)
            settings = config()
            if settings.ai_enabled and row.ai_consent:
                usage, _ = DailyUsage.objects.get_or_create(user=request.user, day=timezone.localdate().isoformat())
                if not DailyUsage.objects.filter(pk=usage.pk, reports__lt=settings.daily_reports_per_user).update(reports=F("reports")+1):
                    return json_error("今天的报告请求次数已用完", status=429)
            PersonalityJob.objects.create(kind="report", assessment=row, requested_by=request.user.username, parameters={"character_only": True, "ai": settings.ai_enabled and row.ai_consent})
        return json_ok({"status": "queued"}, status=202)
    except ValueError as exc:
        return json_error(str(exc))


@require_user
@require_GET
def report_answers(request, assessment_id):
    row = Assessment.objects.filter(pk=assessment_id, user=request.user).first()
    if not row:
        return json_error("档案不存在", status=404)
    return json_ok({"steps": row.steps, "answers": row.answers})


@require_user
@require_GET
def character_image(request, assessment_id):
    row = Assessment.objects.filter(pk=assessment_id, user=request.user, status="completed").first()
    image = ((row.report if row else {}).get("character") or {}).get("image_url", "")
    if not image or not safe_image(image):
        raise Http404
    try:
        raw = character_image_bytes(image)
    except (OSError, ValueError):
        raise Http404 from None
    output = HttpResponse(raw, content_type="image/webp")
    output["Cache-Control"] = "private, max-age=86400"
    output["X-Content-Type-Options"] = "nosniff"
    return output


@require_user
@require_POST
def question_feedback(request, assessment_id):
    row = Assessment.objects.filter(pk=assessment_id, user=request.user).first()
    if not row:
        return json_error('档案不存在', status=404)
    try:
        key = read_json(request).get('question_id')
        if not isinstance(key, str) or not 1 <= len(key) <= 80:
            raise ValueError('题目编号无效')
        question = next((q for step in row.steps for q in step['questions'] if q['id'] == key), None)
        if question is None:
            raise ValueError('题目不属于这次测评')
        words = question['text']
        if key.startswith('follow-') and not question.get('source_quote'):
            words = '历史补充理解题（不展示嵌入的个人原话）'
        feedback, created = QuestionFeedback.objects.get_or_create(assessment=row, question_id=key,
            defaults={'question_version': question.get('wording_version') or row.version, 'question_text': words})
        return json_ok({'received': True, 'id': str(feedback.pk)}, status=201 if created else 200)
    except ValueError as exc:
        return json_error(str(exc))


@require_admin(super_only=True)
@require_GET
def admin_operations(request):
    from django.db.models import Count, Min
    from .operations import readiness, scan_alerts
    settings = config()
    scan_alerts(settings)
    summary = {'readiness': readiness(settings), 'counts': {
        'alerts': OperationalAlert.objects.filter(status='open').count(),
        'feedback': QuestionFeedback.objects.filter(status='new').count()}}
    if request.GET.get('summary') == '1':
        response = json_ok(summary)
        response['Cache-Control'] = 'private, no-store'
        return response
    alerts = OperationalAlert.objects.select_related('job').exclude(status='resolved').order_by('-created_at')[:50]
    groups = QuestionFeedback.objects.values('question_id', 'question_version', 'question_text').annotate(
        count=Count('id'), pending=Count('id', filter=Q(status='new')), representative=Min('id'))
    groups = groups.filter(pending__gt=0).order_by('-pending', 'question_version', 'question_id')[:50]
    response = json_ok({**summary,
        'alerts': [{'id': str(alert.pk), 'assessment_id': str(alert.job.assessment_id), 'job_id': str(alert.job_id),
                    'code': alert.code, 'status': alert.status, 'job_status': alert.job.status,
                    'phase': alert.job.phase, 'created_at': alert.created_at, 'updated_at': alert.job.updated_at,
                    'kind': alert.job.kind} for alert in alerts],
        'feedback': [{'id': str(item['representative']), 'question_id': item['question_id'], 'version': item['question_version'],
                      'question': item['question_text'], 'count': item['count'], 'pending': item['pending']} for item in groups]})
    response['Cache-Control'] = 'private, no-store'
    return response


@require_admin(super_only=True)
@require_POST
def acknowledge_alert(request, alert_id):
    changed = OperationalAlert.objects.filter(pk=alert_id).exclude(status='resolved').update(status='acknowledged', acknowledged_by=request.kflow_admin['username'])
    return json_ok({'acknowledged': True}) if changed else json_error('提醒已恢复或不存在，请刷新', status=404)


@require_admin(super_only=True)
@require_POST
def handle_question_feedback(request, feedback_id):
    feedback = QuestionFeedback.objects.filter(pk=feedback_id).first()
    if not feedback:
        return json_error('反馈不存在', status=404)
    QuestionFeedback.objects.filter(question_id=feedback.question_id, question_version=feedback.question_version,
        question_text=feedback.question_text, status='new').update(status='handled', handled_by=request.kflow_admin['username'])
    return json_ok({'handled': True})


def settings_payload(row):
    return public_config(row)


@require_admin(3)
@require_http_methods(["GET", "POST"])
def admin_catalog_settings(request):
    row = config()
    if request.method == "POST":
        try:
            body = read_json(request)
            if set(body) - set(FILTER_LIMITS):
                raise ValueError("此入口仅保存角色采集设置")
            for field, (low, high) in FILTER_LIMITS.items():
                if field in body:
                    if type(body[field]) is not int or not low <= body[field] <= high:
                        raise ValueError("采集筛选数值超出范围")
                    setattr(row, field, body[field])
            if PersonalitySettings.objects.filter(pk=1).exists():
                row.save(update_fields=list(FILTER_LIMITS))
            else:
                row.save()
        except ValueError as exc:
            return json_error(str(exc))
    return json_ok({"settings": {key: getattr(row, key) for key in FILTER_LIMITS}})


@require_admin(3)
@require_GET
def admin_catalog_export(request):
    response = HttpResponse(json.dumps(export_catalog(), ensure_ascii=False, indent=2), content_type="application/json; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="xinying-characters.json"'
    response["Cache-Control"] = "private, no-store"
    return response


@require_admin(3)
@require_POST
def admin_catalog_import(request):
    try:
        if int(request.META.get("CONTENT_LENGTH") or 0) > 2 * 1024 * 1024:
            return json_error("网页导入上限 2 MB，大数据包请使用管理命令", status=413)
        return json_ok(import_catalog(read_json(request)))
    except ValueError as exc:
        return json_error(str(exc))


@require_admin(super_only=True)
@require_http_methods(["GET", "POST"])
def admin_settings(request):
    row = config()
    if request.method == "GET":
        return json_ok({"settings": settings_payload(row)})
    try:
        body = read_json(request)
        row = parse_config(body, row)
        row.updated_by = request.kflow_admin["username"]; row.updated_at = timestamp()
        # A stale settings form must never overwrite the worker heartbeat.
        fields = [f.name for f in PersonalitySettings._meta.fields if f.name in body and f.name not in {"id", "worker_last_seen_at", "api_key_ciphertext", "evidence_api_key_ciphertext", "provider_check"}]
        fields += ["updated_at", "updated_by"]
        if body.get("api_key", "").strip() or body.get("clear_api_key"):
            fields.append("api_key_ciphertext")
        if body.get("evidence_api_key", "").strip() or body.get("clear_evidence_api_key"):
            fields.append("evidence_api_key_ciphertext")
        if PersonalitySettings.objects.filter(pk=1).exists():
            PersonalitySettings.objects.filter(pk=1).update(**{f: getattr(row, f) for f in fields})
        else:
            row.save(force_insert=True)
        return json_ok({"settings": settings_payload(row)})
    except ValueError as exc:
        return json_error(str(exc))


@require_admin(super_only=True)
@require_POST
def admin_test_provider(request):
    row = None
    try:
        row = parse_config(read_json(request), config())
        row.ai_enabled = True
        result = complete_json(row, '只返回 {"ok":true}，用于连接检查。', {"purpose": "connection_check"})
        if result.get("ok") is not True:
            raise ValueError("接口已响应，但未返回约定的 JSON，请检查模型兼容性")
        remember_connection_check(row, "passed")
        return json_ok({"connected": True})
    except ValueError as exc:
        if row is not None:
            remember_connection_check(row, "failed", str(exc))
        return json_error(str(exc))


@require_admin(super_only=True)
@require_POST
def admin_models(request):
    try:
        return json_ok({"models": list_models(parse_config(read_json(request), config()))})
    except ValueError as exc:
        return json_error(str(exc))


@require_admin(super_only=True)
@require_POST
def admin_copy_connection(request):
    try:
        source = read_json(request).get("source")
        row = config()
        if source == "xiaok":
            from apps.community_ai.models import AssistantSettings
            original = AssistantSettings.objects.filter(pk=1).first()
            if not original or not original.base_url or not original.model:
                raise ValueError("小 K 尚未配置文本服务")
            row.base_url, row.model, row.api_key_ciphertext = original.base_url, original.model, original.api_key_ciphertext
        elif source == "imaging":
            from apps.imaging.skill_runtime import skill_chat_api_key, skill_chat_config_payload
            original = skill_chat_config_payload()
            if not original.get("configured"):
                raise ValueError("显影尚未配置 Skill 文本服务")
            row.base_url, row.model = original["baseUrl"], original["model"]
            row.api_key_ciphertext = encrypt_key(skill_chat_api_key())
        else:
            raise ValueError("请选择小 K 或显影的文本配置")
        row.updated_by = request.kflow_admin["username"]; row.updated_at = timestamp()
        if row.pk and PersonalitySettings.objects.filter(pk=1).exists():
            row.save(update_fields=["base_url", "model", "api_key_ciphertext", "updated_at", "updated_by"])
        else:
            row.save()
        return json_ok({"settings": settings_payload(row)})
    except ValueError as exc:
        return json_error(str(exc))


@require_admin(3)
@require_http_methods(["GET", "POST"])
def admin_characters(request):
    if request.method == "GET":
        rows = Character.objects.all()
        state = request.GET.get("status")
        if state in {"candidate", "draft", "approved", "excluded"}:
            rows = rows.filter(status=state)
        keyword = request.GET.get("q", "")[:100]
        if keyword:
            from django.db.models import Q
            rows = rows.filter(Q(name__icontains=keyword) | Q(work_name__icontains=keyword))
        try:
            page_number = max(1, int(request.GET.get("page", "1")[:6]))
        except (ValueError, TypeError):
            return json_error("页码无效")
        total = rows.count(); pages = max(1, (total + 39) // 40); page_number = min(page_number, pages)
        start = (page_number - 1) * 40
        settings = config()
        return json_ok({"items": [character_payload(row, settings) for row in rows[start:start + 40]], "ready": eligible_characters().count(), "total": total, "page": page_number, "pages": pages,
            "counts": {key: Character.objects.filter(status=key).count() for key in ["candidate", "draft", "approved", "excluded"]}, "operator": request.kflow_admin["username"]})
    try:
        body = read_json(request)
        mode = body.get("mode", "recent")
        work_limit, character_limit = body.get("work_limit", 10), body.get("character_limit", 100)
        subjects = body.get("subject_ids", [])
        if mode not in {"recent", "classic"} or type(work_limit) is not int or not 1 <= work_limit <= 40 or type(character_limit) is not int or not 1 <= character_limit <= 120:
            raise ValueError("导入模式或数量无效")
        if not isinstance(subjects, list) or len(subjects) > 10 or any(type(pk) is not int or pk <= 0 for pk in subjects):
            raise ValueError("作品 ID 最多填写 10 个正整数")
        if PersonalityJob.objects.filter(kind="import", status__in=["queued", "processing"]).exists():
            return json_error("已有导入任务，请等待完成", status=409)
        retry_errors = body.get("retry_errors", False)
        if type(retry_errors) is not bool:
            raise ValueError("重试选项无效")
        job = PersonalityJob.objects.create(kind="import", requested_by=request.kflow_admin["username"], parameters={"mode": mode, "work_limit": work_limit, "character_limit": character_limit, "subject_ids": subjects, "retry_errors": retry_errors})
        return json_ok({"job_id": str(job.pk)}, status=202)
    except ValueError as exc:
        return json_error(str(exc))


def character_payload(row, settings=None):
    settings = settings or config()
    check = readiness(row, recent_years=settings.recent_years, current_year=date.today().year)
    return {"id": row.pk, "source_id": row.source_id, "name": row.name, "work_name": row.work_name, "work_year": row.work_year,
            "image_url": row.image_url, "image_layout": row.image_layout, "status": row.status, "theme": row.theme, "classic": row.classic,
            "classic_candidate": row.classic_candidate, "source_url": row.source_url, "source_text": row.source_text, "extra_sources": row.extra_sources, "profile": row.profile, "stats": row.source_stats,
            "revision": row.revision, "profile_check": row.profile_check, "publication": check,
            "review_origin":"starter_editor" if row.reviewed_by=='starter-evidence-v1' and row.profile_check.get('status') not in {'passed','manual'} else "ai" if row.profile_check.get('status')=='passed' else "editor"}


@require_admin(3)
@require_POST
def admin_character(request, character_id):
    row = Character.objects.filter(pk=character_id).first()
    if not row:
        return json_error("角色不存在", status=404)
    previous_status, previous_reviewed_at, previous_revision = row.status, row.reviewed_at, row.revision
    try:
        body = read_json(request)
        if "revision" in body and (type(body["revision"]) is not int or body["revision"] != row.revision):
            return json_error("角色资料已修改，请刷新后重试", status=409)
        if body.get("action") == "draft":
            if row.status in {"approved", "excluded"}:
                raise ValueError("请先将角色退回候选，避免覆盖已审核内容")
            if not config().ai_enabled:
                raise ValueError("请先配置文本分析服务")
            result = queue_profiles([row.pk], request.kflow_admin["username"], regenerate=True)
            if not result["queued"]:
                return json_error(result["skipped"][0]["reason"], status=409)
            job = PersonalityJob.objects.filter(character=row, kind="profile", status="queued").first()
            return json_ok({"job_id": str(job.pk)}, status=202)
        state = body.get("status", row.status)
        theme = body.get("theme", row.theme)
        classic = body.get("classic", row.classic)
        layout = body.get("image_layout", row.image_layout)
        if state not in {"candidate", "draft", "approved", "excluded"} or theme not in THEME_IDS or type(classic) is not bool or layout not in {"portrait", "cutout"}:
            raise ValueError("角色状态或主题无效")
        profile = body.get("profile", row.profile)
        if not isinstance(profile, dict) or len(json.dumps(profile)) > 50000:
            raise ValueError("角色档案格式无效")
        sources = body.get("extra_sources", row.extra_sources)
        if not isinstance(sources, list) or len(sources) > MAX_SOURCES:
            raise ValueError("最多补充 12 个资料来源")
        from urllib.parse import urlsplit
        cleaned_sources = []
        for source in sources:
            if not isinstance(source, dict) or not isinstance(source.get("url"), str) or not isinstance(source.get("text"), str):
                raise ValueError("补充资料需包含来源链接与原文")
            url, text = source["url"].strip(), source["text"].strip()
            parsed = urlsplit(url)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or len(url) > 1000 or not 10 <= len(text) <= 10000:
                raise ValueError("补充来源需为 HTTPS 链接，原文需为 10–10000 字")
            cleaned_sources.append({"url": url, "text": text})
        row.extra_sources = cleaned_sources
        if state == "approved":
            profile = validate_profile(profile, row)
            if not classic and (row.work_year is None or row.work_year < date.today().year - config().recent_years):
                raise ValueError("较早年代的角色需明确勾选经典保留，或暂留草稿")
            row.reviewed_by = request.kflow_admin["username"]; row.reviewed_at = timestamp()
        original=Character.objects.get(pk=row.pk)
        prior_approvals=retained_approvals(original)
        old_fingerprint = profile_fingerprint(original)
        new_fingerprint = profile_fingerprint(row, profile)
        if state == "approved":
            row.profile_check = {"status": "manual", "fingerprint": new_fingerprint, "issues": [], "checked_at": timestamp(), "summary": "管理员人工确认依据"}
        elif old_fingerprint != new_fingerprint:
            kept=validate_records(row,prior_approvals,profile)
            row.profile_check = {'status':'needs_sources','category':'review_required','dimension_approvals':kept,
                'retained_dimensions':list(kept),'issues':['资料已更新，需复核当前档案']} if kept else {}
        row.status = state; row.theme = theme; row.classic = classic; row.image_layout = layout; row.profile = profile
        with transaction.atomic():
            updated = Character.objects.filter(pk=row.pk, status=previous_status, reviewed_at=previous_reviewed_at, revision=previous_revision).update(
                status=state, theme=theme, classic=classic, image_layout=layout, profile=profile, extra_sources=row.extra_sources,
                reviewed_by=row.reviewed_by, reviewed_at=row.reviewed_at, profile_check=row.profile_check, revision=F("revision")+1)
            if not updated:
                return json_error("角色已被其它操作更新，请刷新后重新审核", status=409)
        row.revision += 1
        return json_ok({"character": character_payload(row)})
    except ValueError as exc:
        return json_error(str(exc))


@require_admin(3)
@require_GET
def admin_jobs(request):
    return json_ok({"items": [{"id": str(job.pk), "kind": job.kind, "status": job.status, "result": job.result, "error": job.error,
                               "phase": job.phase, "created_at": job.created_at} for job in PersonalityJob.objects.order_by("-created_at")[:30]]})


def analysis_payload(row):
    recent=row.analysis_calls.filter(created_at__gte=(timezone.now()-timedelta(days=30)).isoformat())
    calls=list(recent.order_by('-created_at')[:100]);calls.reverse()
    return {'assessment':{'id':str(row.pk),'version':row.version,'status':row.status,'ai_consent':row.ai_consent,'analysis_mode':row.report.get('analysis_mode',''),'has_character':bool(row.report.get('character'))},
            'jobs':list(PersonalityJob.objects.filter(assessment=row).order_by('-created_at').values('id','status','phase','error','created_at','attempts')[:20]),
            'calls':[{'id':str(call.pk),'job_id':str(call.job_id) if call.job_id else '', 'stage':call.stage,'status':call.status,'request':call.request,'response':call.response,'usage':call.usage,'error':call.error,'elapsed_ms':call.elapsed_ms,'created_at':call.created_at} for call in calls],
            'total_calls':recent.count()}


@require_user
@require_GET
def analysis_detail(request,assessment_id):
    row=Assessment.objects.filter(pk=assessment_id,user=request.user).first()
    if not row:return json_error('档案不存在',status=404)
    response=json_ok(analysis_payload(row));response['Cache-Control']='private, no-store';return response


@require_admin(super_only=True)
@require_GET
def admin_report_list(request):
    from django.db.models import Q,Count
    import uuid
    rows=Assessment.objects.select_related('user').annotate(call_count=Count('analysis_calls')).order_by('-created_at')
    query=(request.GET.get('q') or '').strip()[:150]
    if query:
        condition=Q(user__username__icontains=query)
        try:condition|=Q(pk=uuid.UUID(query))
        except ValueError:pass
        rows=rows.filter(condition)
    response=json_ok({'items':[{'id':str(row.pk),'username':row.user.username,'status':row.status,'mode':row.report.get('analysis_mode',''),'has_character':bool(row.report.get('character')),'call_count':row.call_count,'created_at':row.created_at} for row in rows[:40]]})
    response['Cache-Control']='private, no-store';return response


@require_admin(super_only=True)
@require_GET
def admin_analysis_detail(request,assessment_id):
    row=Assessment.objects.filter(pk=assessment_id).first()
    if not row:return json_error('档案不存在',status=404)
    response=json_ok(analysis_payload(row));response['Cache-Control']='private, no-store';return response


@require_admin(3)
@require_POST
def admin_batch_drafts(request):
    if not config().ai_enabled:
        return json_error("请先配置并启用文本分析服务")
    try:
        body = read_json(request)
        ids = selected_ids(body.get("ids"), 40)
        return json_ok(queue_profiles(ids, request.kflow_admin["username"]), status=202)
    except ValueError as exc:
        return json_error(str(exc))


@require_admin(3)
@require_POST
def admin_batch_action(request):
    try:
        body = read_json(request)
        action = body.get("action")
        if not isinstance(action, str) or action not in {"generate", "regenerate", "recheck", "approve", "exclude", "restore", "hold", "release"}:
            raise ValueError("批量操作无效")
        ids = selected_ids(body.get("ids"), 40 if action in {"generate", "regenerate", "recheck"} else 120)
        versions = validate_versions(body.get("versions", {}), ids)
        if action in {"generate", "regenerate", "recheck"}:
            if not config().ai_enabled:
                raise ValueError("请先在 AI 模型服务页配置并启用接口")
            feedback = body.get("feedback", "")
            keep = body.get("keep_classics", False)
            if not isinstance(feedback, str) or len(feedback) > 600 or type(keep) is not bool:
                raise ValueError("意见或经典保留选项无效")
            result = queue_profiles(ids, request.kflow_admin["username"], versions=versions,
                regenerate=action=="regenerate", review_only=action=="recheck", feedback=feedback, keep_classics=keep)
            return json_ok(result, status=202)
        return json_ok(batch_decision(ids, action, request.kflow_admin["username"], versions))
    except ValueError as exc:
        return json_error(str(exc))


@require_admin(3)
@require_POST
def admin_retry_job(request, job_id):
    with transaction.atomic():
        PersonalityJob.objects.filter(pk=job_id, status="failed").update(updated_at=F("updated_at"))
        job = PersonalityJob.objects.filter(pk=job_id, status="failed", kind__in=["import", "profile"]).first()
        if not job:
            return json_error("仅可重试失败的导入或草稿任务", status=409)
        if job.kind == "profile" and (not job.character_id or job.character.status in {"approved", "excluded"}):
            return json_error("已审核或已排除的角色不能覆盖", status=409)
        live = PersonalityJob.objects.filter(kind=job.kind, status__in=["queued", "processing"])
        if job.kind == "profile":
            live = live.filter(character_id=job.character_id)
        if live.exists():
            return json_error("已有同类任务正在处理", status=409)
        parameters = {**job.parameters, **({"retry_errors": True} if job.kind == "import" else {})}
        checkpoint=job.checkpoint
        if job.kind == "profile":
            expected = job.parameters.get("revision", job.character.revision)
            if expected != job.character.revision:
                return json_error("资料已修改，请从列表重新生成或复核", status=409)
            Character.objects.filter(pk=job.character_id, revision=expected).update(profile_check={"status": "queued"})
            if parameters.get('pipeline')!=CHARACTER_RUBRIC_VERSION:
                parameters['pipeline']=CHARACTER_RUBRIC_VERSION
                checkpoint={**checkpoint,'draft':normalize_draft(checkpoint['draft'])} if 'draft' in checkpoint else checkpoint
        if not PersonalityJob.objects.filter(pk=job.pk, status="failed").update(status="queued", phase="", parameters=parameters, checkpoint=checkpoint, error="", claim_token="", updated_at=timestamp()):
            return json_error("任务状态已更新", status=409)
    return json_ok({"job_id": str(job.pk)}, status=202)
