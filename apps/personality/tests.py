import json
import urllib.error
from datetime import date, timedelta
from unittest.mock import patch
from unittest.mock import MagicMock

from django.test import Client, TestCase
from django.utils import timezone

from apps.accounts.models import User
from .catalog import bangumi, import_characters, safe_image, validate_profile
from .models import Assessment, Character, DailyUsage, PersonalityJob, PersonalitySettings, timestamp
from .questions import DIMENSIONS, VERSION, initial_steps, quantified
from .services import build_report, eligible_characters, enrich_report, process_job, recover_jobs


def ready_ai_fixture():
    """A checked synthetic connection; provider calls are mocked by workflow tests."""
    from .configuration import remember_connection_check
    from .provider import encrypt_key
    row, _ = PersonalitySettings.objects.get_or_create(pk=1)
    row.ai_enabled = True
    row.base_url = row.base_url or 'https://example.invalid/v1'
    row.model = row.model or 'fixture'
    row.api_key_ciphertext = row.api_key_ciphertext or encrypt_key('fixture-key')
    row.save()
    remember_connection_check(row, 'passed')
    row.refresh_from_db()
    return row


class PersonalityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(username="personality_alice", password="test-only", created_at=timestamp())
        cls.bob = User.objects.create_user(username="personality_bob", password="test-only", created_at=timestamp())

    def setUp(self):
        self.client.force_login(self.alice)
        self.admin = Client()
        session = self.admin.session
        session["admin_username"] = "root"; session["admin_level"] = 3; session["admin_is_super"] = True; session.save()

    def send(self, path, body=None, client=None):
        return (client or self.client).post(path, json.dumps(body or {}), content_type="application/json")

    def create(self, **kwargs):
        # Stored/legacy fixture for scoring and old-report compatibility. The
        # public creation endpoint is exercised in test_ai_requirement.py.
        from .views import assessment_payload
        previous = Assessment.objects.filter(user=self.alice).order_by('-created_at').first()
        previous_ids = [q['id'] for s in previous.steps for q in s['questions']] if previous else []
        row = Assessment(user=self.alice, version=VERSION, ai_consent=kwargs.get('ai_consent', False))
        row.steps = initial_steps(seed=str(row.pk), previous_ids=previous_ids)
        # Frozen legacy workflows have separate coverage from the single-call
        # public creation path in test_single_report.py.
        row.steps[0]['analysis_policy'] = 'legacy-batches'
        row.steps[0]['followup_policy'] = 'adaptive-v1'
        row.save()
        return assessment_payload(row)

    def finish(self, *, consent=False, context=False):
        if consent:
            ready_ai_fixture()
        state = self.create(ai_consent=consent)
        # Report fixtures keep the established fixed interview. The optional
        # asynchronous interview has independent workflow coverage.
        fixture = Assessment.objects.get(pk=state['id'])
        fixture.steps[0].pop('followup_policy', None); fixture.save(update_fields=['steps'])
        while state["status"] == "active":
            answers = {q["id"]: {"value": 6 if q["kind"] == "scale" else None, "note": ("以前常常勉强答应，但是现在会先讲清自己的感受。" if context else "我会先理解对方的处境，再说出自己的需要。") if q["kind"] == "open" else "", "skipped": False} for q in state["step"]["questions"]}
            response = self.send("/api/personality/assessments/" + state["id"], {"revision": state["revision"], "answers": answers, "complete": True})
            self.assertEqual(response.status_code, 200, response.content)
            state = response.json()
        return Assessment.objects.get(pk=state["id"])

    def character(self, **kwargs):
        text = "他会察觉他人的难处，在关系中反复思考，也会表达自己的边界。遇到挫折后逐渐恢复，尝试多种办法，并坚持完成自己的计划。"
        profile = {"summary": "在不同的关系中探索理解与承担的边界。", "mechanism": "先理解对方的难处，再根据自身原则决定行动。", "dimensions": {key: {"level": 5, "quote": "他会察觉他人的难处", "reason": "这是测试夹具中的显式编辑依据，用来验证数据流与审核。"} for key in DIMENSIONS}}
        defaults = {"source_id": Character.objects.count() + 1, "name": "测试角色", "work_id": 1, "work_name": "测试作品", "work_year": date.today().year,
                    "source_text": text, "source_url": "https://bgm.tv/character/1", "image_url": "https://lain.bgm.tv/pic/cover/l/test.jpg", "profile": profile, "status": "approved"}
        defaults.update(kwargs)
        return Character.objects.create(**defaults)

    def test_pages_auth_and_csrf(self):
        guest = Client()
        self.assertEqual(guest.get("/personality").status_code, 200)
        self.assertEqual(guest.get("/personality/test").status_code, 302)
        self.assertEqual(guest.get("/api/personality/assessments").status_code, 401)
        self.assertEqual(self.client.get("/admin/personality").status_code, 302)
        strict = Client(enforce_csrf_checks=True); strict.force_login(self.alice)
        self.assertEqual(self.send("/api/personality/assessments", client=strict).status_code, 403)
        self.assertEqual(self.admin.get("/admin/personality").status_code, 200)

    def test_real_reverse_scoring_and_skips_are_not_zero(self):
        steps = initial_steps()
        answers = {}
        for step in steps:
            for question in step["questions"]:
                if question["kind"] != "scale":
                    continue
                answers[question["id"]] = {"value": 1 if question["reverse"] else 7, "note": "", "skipped": False}
        scores = quantified(steps, answers)
        self.assertTrue(all(value["value"] == 100 for value in scores.values()))
        for step in steps:
            for question in step["questions"]:
                if question.get("target") == "recovery":
                    answers[question["id"]] = {"value": None, "note": "不适用", "skipped": True}
        self.assertIsNone(quantified(steps, answers)["recovery"]["value"])

    def test_preserves_notes_and_rejects_invalid_values_and_stale_revision(self):
        state = self.create(); endpoint = "/api/personality/assessments/" + state["id"]; qid = state["step"]["questions"][0]["id"]
        for value in [True, 0, 8, "5"]:
            self.assertEqual(self.send(endpoint, {"revision": 0, "answers": {qid: {"value": value}}}).status_code, 400)
        response = self.send(endpoint, {"revision": 0, "answers": {qid: {"value": None, "note": "5，但是只在工作上如此"}}})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["answers"][qid]["note"], "5，但是只在工作上如此")
        self.assertEqual(self.send(endpoint, {"revision": 0, "answers": {}}).status_code, 409)
        self.assertEqual(self.send(endpoint, {"revision": 1, "answers": {"forged-id": {"value": 7}}}).status_code, 400)

    def test_adaptive_rounds_followups_and_ready_can_go_back(self):
        row = self.finish(context=True)
        self.assertEqual(row.status, "ready")
        self.assertEqual(len(row.steps), 9)
        self.assertEqual(len(row.steps[6]["questions"]), 6)
        self.assertTrue(any(q["id"] == "follow-context" for q in row.steps[8]["questions"]))
        text = json.dumps(row.steps, ensure_ascii=False)
        self.assertNotIn("喜欢什么动漫", text)
        self.assertNotIn("喜欢哪些角色", text)
        response = self.send(f"/api/personality/assessments/{row.pk}", {"revision": row.revision, "action": "back"})
        self.assertEqual(response.json()["status"], "active")

    def test_owner_isolation_for_all_private_endpoints(self):
        row = self.finish()
        other = Client(); other.force_login(self.bob)
        prefix = f"/api/personality/assessments/{row.pk}"
        for suffix in ["", "/report", "/answers"]:
            self.assertEqual(other.get(prefix + suffix).status_code, 404)
        self.assertEqual(self.send(prefix + "/submit", client=other).status_code, 404)
        self.assertEqual(other.delete(prefix).status_code, 404)
        self.assertEqual(other.get(f"/personality/report/{row.pk}").status_code, 404)

    @patch('apps.personality.services.enrich_report', side_effect=lambda row, result, *args: {**result, 'analysis_mode': 'ai'})
    def test_submit_idempotent_report_snapshot_and_deletion_does_not_reset_quota(self, enrich):
        role = self.character()
        row = self.finish(consent=True)
        path = f"/api/personality/assessments/{row.pk}/submit"
        self.assertEqual(self.send(path).status_code, 202)
        self.assertEqual(self.send(path).status_code, 200)
        self.assertEqual(PersonalityJob.objects.filter(assessment=row).count(), 1)
        job = PersonalityJob.objects.get(assessment=row); process_job(job.pk)
        row.refresh_from_db()
        self.assertEqual(row.status, "completed")
        self.assertEqual(row.report["character"]["id"], role.pk)
        self.assertEqual(row.report["quote"]["text"], "我会先理解对方的处境，再说出自己的需要。")
        old = row.report
        role.name = "已改名"; role.theme = "sunshine"; role.save()
        self.send(path); process_job(job.pk)
        self.assertEqual(self.client.get(f"/api/personality/assessments/{row.pk}/report").json()["report"], old)
        self.client.delete(f"/api/personality/assessments/{row.pk}")
        self.assertEqual(DailyUsage.objects.get(user=self.alice).reports, 1)

    def test_no_approved_role_means_no_fabricated_character(self):
        self.character(status="draft")
        row = self.finish()
        report = build_report(row)
        self.assertIsNone(report["character"])
        self.assertNotIn("probability", report)
        self.assertNotIn("total_score", report)

    def test_classics_need_explicit_retention_and_profiles_require_exact_quotes(self):
        role = self.character(work_year=1999)
        self.assertFalse(eligible_characters().exists())
        response = self.send(f"/api/admin/personality/characters/{role.pk}", {"status": "approved"}, client=self.admin)
        self.assertEqual(response.status_code, 400)
        response = self.send(f"/api/admin/personality/characters/{role.pk}", {"status": "approved", "classic": True}, client=self.admin)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(eligible_characters().exists())
        role.profile["dimensions"]["empathy"]["quote"] = "这是模型编出来的剧情依据"
        with self.assertRaises(ValueError):
            validate_profile(role.profile, role)

    def test_unknown_dimension_levels_cannot_be_approved(self):
        role = self.character(status="draft")
        role.profile["dimensions"]["execution"]["level"] = None
        response = self.send(f"/api/admin/personality/characters/{role.pk}", {"status": "approved", "profile": role.profile}, client=self.admin)
        self.assertEqual(response.status_code, 400)

    def test_settings_key_is_encrypted_and_never_public(self):
        response = self.send("/api/admin/personality/settings", {"base_url": "https://example.invalid", "model": "test", "api_key": "secret-fixture", "ai_enabled": True}, client=self.admin)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"secret-fixture", response.content)
        self.assertNotEqual(PersonalitySettings.objects.get(pk=1).api_key_ciphertext, "secret-fixture")
        self.assertNotIn(b"base_url", self.client.get("/api/personality/config").content)
        self.assertEqual(self.send("/api/admin/personality/settings", {"api_key": "new"}).status_code, 401)

    @patch("apps.personality.services.complete_json")
    def test_ai_requires_user_consent_and_error_keeps_answers(self, complete):
        PersonalitySettings.objects.create(ai_enabled=True, base_url="https://example.invalid/v1", model="test")
        row = self.finish(consent=False)
        ready_ai_fixture()
        self.assertEqual(self.send(f"/api/personality/assessments/{row.pk}/submit").status_code, 400)
        self.assertFalse(PersonalityJob.objects.filter(assessment=row).exists())
        complete.assert_not_called()
        row = self.finish(consent=True); before = row.answers
        complete.side_effect = ValueError("分析暂不可用")
        self.send(f"/api/personality/assessments/{row.pk}/submit")
        process_job(PersonalityJob.objects.get(assessment=row).pk)
        row.refresh_from_db()
        self.assertEqual(row.status, "failed")
        self.assertEqual(row.answers, before)
        self.assertFalse(row.report)

    @patch("apps.personality.services.complete_json")
    def test_ai_rejects_untraceable_evidence_and_invented_numbers(self, complete):
        row = self.finish()
        report = build_report(row)
        complete.return_value = {"sections": [{"title": "关系", "text": "你的人格概率是99%，这是未经计算的数据。", "evidence": ["forged"]}] * 4}
        with self.assertRaises(ValueError):
            enrich_report(row, report, PersonalitySettings(ai_enabled=True))

    def test_missing_answers_remain_missing_in_report(self):
        row = Assessment.objects.create(user=self.alice, steps=initial_steps())
        report = build_report(row)
        self.assertEqual(report["type"], "待补充")
        self.assertTrue(all(d["value"] is None for d in report["dimensions"]))
        self.assertIsNone(report["character"])

    @patch("apps.personality.catalog.time.sleep")
    @patch("apps.personality.catalog.bangumi")
    def test_import_is_candidate_only_deduplicates_and_respects_exclusions(self, bangumi, sleep):
        source = "主角在旅途中理解他人的困难，并在不同关系中学着表达自己的想法。经历挫折后，他尝试新的方向，坚持完成自己的计划。"
        work = {"id": 10, "type": 2, "name": "测试动画", "date": f"{date.today().year}-01-01", "collection": {"collect": 9000}}
        bangumi.side_effect = lambda path, data=None: work if path == "subjects/10" else [{"id": 500, "name": "角色", "type": 1, "relation": "主角"}] if path.endswith("/characters") else {"name": "角色", "summary": source, "stat": {"collects": 99}, "images": {"large": "https://lain.bgm.tv/pic/l/a.jpg"}}
        result = import_characters({"subject_ids": [10], "work_limit": 1, "character_limit": 10})
        self.assertEqual(result["imported"], 1)
        role = Character.objects.get(source_id=500)
        self.assertEqual(role.status, "candidate")
        role.status = "excluded"; role.classic = True; role.save()
        import_characters({"subject_ids": [10], "work_limit": 1, "character_limit": 10})
        role.refresh_from_db(); self.assertEqual(role.status, "excluded"); self.assertTrue(role.classic)
        self.assertEqual(Character.objects.count(), 1)

    def test_image_proxy_allows_only_expected_cdn(self):
        self.assertTrue(safe_image("https://lain.bgm.tv/pic/a.png"))
        for url in ["http://127.0.0.1/a.png", "https://evil.example/a", "https://user:pass@lain.bgm.tv/a", "https://lain.bgm.tv.evil.example/a"]:
            self.assertFalse(safe_image(url))

    def test_stale_job_is_recoverable_without_losing_answers(self):
        row = self.finish(); row.status = "processing"; row.save()
        before = row.answers
        PersonalityJob.objects.create(kind="report", assessment=row, status="processing", requested_by="test", updated_at=(timezone.now() - timedelta(minutes=20)).isoformat())
        recover_jobs(); row.refresh_from_db()
        self.assertEqual(row.status, "failed"); self.assertEqual(row.answers, before)

    def test_supplementary_evidence_is_saved_and_referenced(self):
        role = self.character(status="draft")
        role.profile["dimensions"]["recovery"]["quote"] = "遇到困难后他会休息并重新尝试"
        sources = [{"url": "https://example.org/verified-story", "text": "在这段已核对的情节中，遇到困难后他会休息并重新尝试，随后找到了不同的方法。"}]
        response = self.send(f"/api/admin/personality/characters/{role.pk}", {"status": "approved", "profile": role.profile, "extra_sources": sources}, client=self.admin)
        self.assertEqual(response.status_code, 200, response.content)
        role.refresh_from_db()
        self.assertEqual(role.profile["dimensions"]["recovery"]["source_url"], sources[0]["url"])
        self.assertEqual(role.extra_sources, sources)
        response = self.send(f"/api/admin/personality/characters/{role.pk}", {"status": "draft", "extra_sources": [{"url": "javascript:alert(1)", "text": "足够长度的测试资料文本，不应该通过校验。"}]}, client=self.admin)
        self.assertEqual(response.status_code, 400)

    @patch("apps.personality.services.complete_json")
    def test_valid_ai_sections_keep_literal_quote(self, complete):
        row = self.finish(context=True)
        from .traits import TOPICS
        report = build_report(row)
        complete.return_value = {
            "title": "温柔而有边界的理解者", "summary": "先理解别人的处境，也开始为自己的需要留出空间。", "keywords": ["理解处境", "表达边界", "真实自洽"], "persona_evidence": ["open-conflict"],
            "sections": [{"topic": key, "text": "你的回答保留了不同情境下的变化，也强调先理解自己真实的需要。", "evidence": ["open-conflict"]} for key in TOPICS],
            "growth": [{"title": "先表达自己的需要", "text": "在下次想勉强答应的时候，先说出自己的顾虑，再讨论双方可以接受的安排。", "evidence": ["open-conflict"]}] * 2,
            "mechanisms": [{"key": "boundary", "reason": "回答强调现在会先讲清自己的感受。", "evidence": ["open-conflict"]}],
            "type_review": [{"type": name, "support": "回答中的偏好支持暂时保留这个候选。", "against": "但情境变化和相近偏好仍然值得继续观察。", "evidence": ["open-conflict"]} for name in report["candidates"]],
            "quote": {"question_id": "open-conflict", "text": row.answers["open-conflict"]["note"]}}
        result = enrich_report(row, report, PersonalitySettings(ai_enabled=True))
        self.assertEqual(result["analysis_mode"], "ai")
        self.assertEqual(result["quote"]["text"], row.answers["open-conflict"]["note"])
        self.assertNotIn("username", complete.call_args.args[2])

    def test_report_quota_cannot_be_bypassed_by_deleting_assessment(self):
        PersonalitySettings.objects.create(daily_reports_per_user=1)
        one = self.finish(consent=True)
        self.send(f"/api/personality/assessments/{one.pk}/submit")
        self.client.delete(f"/api/personality/assessments/{one.pk}")
        two = self.finish(consent=True)
        self.assertEqual(self.send(f"/api/personality/assessments/{two.pk}/submit").status_code, 429)

    def test_production_assets_are_served_under_static_prefix(self):
        for name in ["app.js", "app.css", "report.js", "themes.css", "admin.js"]:
            response = self.client.get("/static/personality/" + name)
            self.assertEqual(response.status_code, 200)
            response.close()

    @patch("apps.personality.catalog.time.sleep")
    @patch("apps.personality.catalog.urllib.request.urlopen")
    def test_bangumi_transient_failure_is_retried(self, opener, sleep):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"data": []}'
        opener.side_effect = [urllib.error.URLError("temporary"), response]
        self.assertEqual(bangumi("search/subjects?limit=1", {"keyword": ""}), {"data": []})
        self.assertEqual(opener.call_count, 2)

    @patch("apps.personality.views.complete_json", return_value={"ok": True})
    def test_provider_check_uses_no_user_answers_or_state_change(self, complete):
        row = PersonalitySettings.objects.create(ai_enabled=False, base_url="https://example.invalid/v1", model="test")
        response = self.send("/api/admin/personality/test", client=self.admin)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(complete.call_args.args[2], {"purpose": "connection_check"})
        row.refresh_from_db(); self.assertFalse(row.ai_enabled)
        self.assertEqual(self.send("/api/admin/personality/test").status_code, 401)

    def test_batch_drafts_skip_reviewed_roles_and_duplicate_queued_jobs(self):
        PersonalitySettings.objects.create(ai_enabled=True)
        pending = self.character(status="candidate")
        reviewed = self.character(status="approved")
        endpoint = "/api/admin/personality/characters/batch-draft"
        payload = {"ids": [pending.pk, reviewed.pk]}
        self.assertEqual(self.send(endpoint, payload, client=self.admin).json()["queued"], 1)
        self.assertEqual(self.send(endpoint, payload, client=self.admin).json()["queued"], 0)
        self.assertEqual(PersonalityJob.objects.filter(kind="profile").count(), 1)
        self.assertFalse(PersonalityJob.objects.filter(character=reviewed).exists())
