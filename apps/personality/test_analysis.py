import copy
import io
import json
import urllib.error
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import MagicMock, patch

from django.test import TestCase

from .analysis import shortlist, source_answers, validate_match, validate_persona
from .configuration import parse_config
from .models import PersonalityJob, PersonalitySettings
from .provider import AnalysisUnavailable, complete_json, list_models
from .services import build_report, enrich_report, process_job
from .tests import PersonalityTests
from .traits import TOPICS


def persona_fixture(row, report):
    refs = ["open-conflict"]
    return {"title": "温柔而有边界的理解者", "summary": "理解他人的处境，也愿意为自己的需要留出空间。", "keywords": ["理解处境", "表达边界", "真实自洽"], "persona_evidence": refs,
        "sections": [{"topic": key, "text": "你会先理解对方的难处，也希望通过表达自己的需要，让关系中的责任更清晰。", "evidence": refs} for key in TOPICS],
        "growth": [{"title": "说清自己的需要", "text": "在下次想勉强答应的时候，先说出自己的顾虑，再讨论双方可以接受的安排。", "evidence": refs}] * 2,
        "mechanisms": [{"key": "boundary", "reason": "你在回答中强调理解和表达自身需要。", "evidence": refs}],
        "type_review": [{"type": name, "support": "这些回答支持暂时保留这个类型作为候选。", "against": "但你的反应会随情境变化，仍需要注意与相近类型的区别。", "evidence": refs} for name in report["candidates"]],
        "quote": {"question_id": "open-conflict", "text": row.answers["open-conflict"]["note"]}}


def match_fixture(role):
    item = {"text": "你们都愿意先理解他人的难处，再判断自己愿意承担的责任。", "user_evidence": ["open-conflict"], "character_evidence": ["empathy"]}
    return {"character_id": role.pk, "cover_line": "理解别人的时候，也为自己留下一片天空。", "similarities": [item, item], "differences": [{**item, "text": "你会主动表达自己的需要，角色在这些情境中的回应仍然更侧重理解他人。"}]}


class DeepAnalysisTests(TestCase):
    setUpTestData = classmethod(PersonalityTests.setUpTestData.__func__)
    setUp = PersonalityTests.setUp
    send = PersonalityTests.send
    create = PersonalityTests.create
    finish = PersonalityTests.finish
    character = PersonalityTests.character

    def test_fandom_removed_only_from_analysis_not_original_answers(self):
        role = self.character()
        row = self.finish()
        original = row.answers["open-conflict"]["note"] + f"我很喜欢{role.name}，希望匹配到他。"
        row.answers["open-conflict"]["note"] = original
        source, removed = source_answers(row)
        self.assertNotIn(role.name, source["open-conflict"]["note"])
        self.assertIn("open-conflict", removed)
        self.assertEqual(row.answers["open-conflict"]["note"], original)

    @patch("apps.personality.services.complete_json")
    def test_anonymous_review_can_choose_different_role_and_never_change_scores(self, complete):
        first = self.character(name="角色甲", work_name="作品甲")
        second = self.character(name="角色乙", work_name="作品乙", theme="sunshine")
        row = self.finish(); before = build_report(row)
        complete.side_effect = [persona_fixture(row, before), match_fixture(second)]
        result = enrich_report(row, copy.deepcopy(before), PersonalitySettings(ai_enabled=True))
        self.assertEqual(result["character"]["id"], second.pk)
        self.assertEqual(result["theme"], "sunshine")
        self.assertEqual(result["axes"], before["axes"])
        self.assertEqual(result["dimensions"], before["dimensions"])
        self.assertEqual(len(result["sections"]), 10)
        payload = complete.call_args.args[2]
        encoded = json.dumps(payload, ensure_ascii=False)
        for name in [first.name, first.work_name, second.name, second.work_name]:
            self.assertNotIn(name, encoded)
        self.assertNotIn("image_url", encoded)
        self.assertNotIn("gender", encoded)
        self.assertEqual(result["audit"]["character_selection"], "anonymous_mechanism_review")

    def test_persona_rejects_numeric_claim_forged_evidence_and_unknown_type(self):
        row = self.finish(); report = build_report(row); source, _ = source_answers(row)
        valid = persona_fixture(row, report)
        for mutate in [lambda p: p["sections"][0].update(text="你的人格成功率达到百分之99，请相信这个结论。"),
                       lambda p: p["growth"][0].update(evidence=["forged"]),
                       lambda p: p["type_review"][0].update(type="XXXX")]:
            candidate = copy.deepcopy(valid); mutate(candidate)
            with self.assertRaises(ValueError):
                validate_persona(candidate, source, report)

    def test_match_rejects_unknown_role_and_unreviewed_character_evidence(self):
        role = self.character(); row = self.finish(); report = build_report(row)
        pool = shortlist(report, [role]); source, _ = source_answers(row)
        invalid = match_fixture(role); invalid["character_id"] += 100
        with self.assertRaises(ValueError): validate_match(invalid, pool, source)
        invalid = match_fixture(role); invalid["similarities"][0]["character_evidence"] = ["invented_story"]
        with self.assertRaises(ValueError): validate_match(invalid, pool, source)

    @patch("apps.personality.services.complete_json")
    def test_failed_character_stage_resumes_saved_persona_and_is_immutable(self, complete):
        PersonalitySettings.objects.create(ai_enabled=True, base_url="https://example.invalid/v1", model="test")
        role = self.character(); row = self.finish(consent=True); report = build_report(row)
        complete.side_effect = [persona_fixture(row, report), ValueError("复核暂不可用")]
        endpoint = f"/api/personality/assessments/{row.pk}/submit"
        self.send(endpoint); job = PersonalityJob.objects.get(assessment=row); process_job(job.pk)
        row.refresh_from_db(); job.refresh_from_db()
        self.assertEqual(row.status, "failed")
        self.assertIn("persona", job.checkpoint)
        self.assertIn("pool", job.checkpoint)
        complete.reset_mock(); complete.side_effect = None; complete.return_value = match_fixture(role)
        self.send(endpoint); retry = PersonalityJob.objects.filter(assessment=row, status="queued").get(); process_job(retry.pk)
        complete.assert_called_once()
        row.refresh_from_db(); retry.refresh_from_db()
        self.assertEqual(row.status, "completed")
        self.assertEqual(retry.checkpoint, {})
        frozen = copy.deepcopy(row.report)
        role.profile = {}; role.status = "excluded"; role.save()
        self.send(endpoint); row.refresh_from_db()
        self.assertEqual(row.report, frozen)

    @patch("apps.personality.views.list_models", return_value=["model-a", "model-b"])
    @patch("apps.personality.views.complete_json", return_value={"ok": True})
    def test_unsaved_connection_models_and_test_do_not_change_saved_settings(self, complete, models):
        stored = PersonalitySettings.objects.create(base_url="https://saved.invalid/v1", model="old")
        body = {"base_url": "https://temporary.invalid/v1", "model": "new", "api_key": "ephemeral-fixture", "timeout_seconds": 120}
        self.assertEqual(self.send("/api/admin/personality/models", body, self.admin).json()["models"], ["model-a", "model-b"])
        self.assertEqual(self.send("/api/admin/personality/test", body, self.admin).status_code, 200)
        self.assertEqual(complete.call_args.args[0].model, "new")
        stored.refresh_from_db(); self.assertEqual(stored.model, "old"); self.assertEqual(stored.api_key_ciphertext, "")
        self.assertEqual(self.send("/api/admin/personality/models", body).status_code, 401)

    def test_config_rejects_conflicting_clear_and_key_and_out_of_range_limits(self):
        for body in [{"api_key": "fixture", "clear_api_key": True}, {"timeout_seconds": 999}, {"max_output_tokens": -1}, {"token_parameter": "invalid"}]:
            with self.assertRaises(ValueError): parse_config(body, PersonalitySettings())

    def test_copy_connection_is_explicit_and_never_returns_secret(self):
        from apps.community_ai.models import AssistantSettings
        from .provider import encrypt_key, decrypt_key
        AssistantSettings.objects.create(base_url="https://example.invalid/v1", model="fixture", api_key_ciphertext=encrypt_key("copy-secret-fixture"))
        self.assertFalse(PersonalitySettings.objects.exists())
        response = self.send("/api/admin/personality/copy-connection", {"source": "xiaok"}, self.admin)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertNotIn(b"copy-secret-fixture", response.content)
        self.assertEqual(decrypt_key(PersonalitySettings.objects.get(pk=1).api_key_ciphertext), "copy-secret-fixture")

    def test_character_pagination_does_not_hide_large_catalog(self):
        from .models import Character
        role = self.character()
        Character.objects.bulk_create([Character(source_id=100+i, name=f"候选{i:03}", work_id=1, work_name="作品", source_text=role.source_text, source_url=role.source_url) for i in range(45)])
        first = self.admin.get("/api/admin/personality/characters?page=1").json()
        second = self.admin.get("/api/admin/personality/characters?page=2").json()
        self.assertEqual(first["total"], 46); self.assertEqual(first["pages"], 2)
        self.assertEqual(len(first["items"]), 40); self.assertEqual(len(second["items"]), 6)
        self.assertFalse({c["id"] for c in first["items"]} & {c["id"] for c in second["items"]})

    def test_real_http_compatible_service_end_to_end_pipeline(self):
        role = self.character(); row = self.finish(consent=True); report = build_report(row)
        responses = [persona_fixture(row, report), match_fixture(role)]
        received = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
                self.wfile.write(b'{"data":[{"id":"fixture-model"}]}')
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                received.append({"path": self.path, "model": body["model"], "payload": json.loads(body["messages"][1]["content"])})
                result = responses.pop(0)
                self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
                self.wfile.write(json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(result, ensure_ascii=False)}}]}).encode())
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        settings = PersonalitySettings(ai_enabled=True, base_url=f"http://127.0.0.1:{server.server_port}/v1", model="fixture-model")
        self.assertEqual(list_models(settings), ["fixture-model"])
        result = enrich_report(row, report, settings)
        self.assertEqual(result["character"]["id"], role.pk)
        self.assertEqual(len(received), 2)
        self.assertTrue(all(item["path"] == "/v1/chat/completions" for item in received))
        self.assertNotIn("name", received[1]["payload"]["candidates"][0])


class ProviderContractTests(TestCase):
    @patch("apps.personality.provider.urllib.request.build_opener")
    def test_compatible_content_blocks_endpoint_and_models(self, opener):
        response = MagicMock(); response.__enter__.return_value.read.return_value = json.dumps({"choices": [{"message": {"content": [{"type": "text", "text": '```json\n{"ok":true}\n```'}]}}]}).encode()
        opener.return_value.open.return_value = response
        settings = PersonalitySettings(ai_enabled=True, base_url="https://example.invalid/v1/chat/completions", model="fixture", token_parameter="max_completion_tokens")
        self.assertEqual(complete_json(settings, "test", {}), {"ok": True})
        request = opener.return_value.open.call_args.args[0]
        self.assertEqual(request.full_url, "https://example.invalid/v1/chat/completions")
        self.assertIn("max_completion_tokens", json.loads(request.data))
        response.__enter__.return_value.read.return_value = b'{"data":[{"id":"a"},{"id":"a"},{"id":"b"}]}'
        self.assertEqual(list_models(settings), ["a", "b"])

    @patch("apps.personality.provider.urllib.request.build_opener")
    def test_unsupported_token_parameter_retries_once_without_exposing_body(self, opener):
        response = MagicMock(); response.__enter__.return_value.read.return_value = b'{"choices":[{"message":{"content":"{\\"ok\\":true}"}}]}'
        error = urllib.error.HTTPError("https://example.invalid", 400, "Bad request", {}, io.BytesIO(b'{"error":{"param":"max_tokens","message":"secret-in-body"}}'))
        opener.return_value.open.side_effect = [error, response]
        settings = PersonalitySettings(ai_enabled=True, base_url="https://example.invalid/v1", model="fixture")
        self.assertEqual(complete_json(settings, "test", {}), {"ok": True})
        self.assertNotIn("max_tokens", json.loads(opener.return_value.open.call_args.args[0].data))
        self.assertEqual(opener.return_value.open.call_count, 2)

    @patch("apps.personality.provider.urllib.request.build_opener")
    def test_auth_error_does_not_expose_upstream_message(self, opener):
        opener.return_value.open.side_effect = urllib.error.HTTPError("https://example.invalid", 401, "raw-secret", {}, io.BytesIO(b'private-key-and-body'))
        with self.assertRaises(AnalysisUnavailable) as error:
            list_models(PersonalitySettings(base_url="https://example.invalid/v1"))
        self.assertNotIn("raw-secret", str(error.exception)); self.assertNotIn("private-key", str(error.exception))
