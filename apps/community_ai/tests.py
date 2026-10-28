import io
import json
import urllib.error
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from datetime import datetime, timedelta, timezone as dt_timezone
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from django.core.management import call_command
from django.test import Client, TestCase
from django.utils import timezone

from apps.accounts.models import OfficialCommunitySettings, User, UserFollow
from apps.imaging.models import ImagingProvider
from apps.messaging.models import PrivateMessage
from apps.murmurs.models import Murmur, MurmurBlock, MurmurComment
from apps.notifications.models import Notification
from .models import AssistantReplyJob, AssistantSettings
from .provider import ProviderError, complete, decrypt_key, encrypt_key, normalize_url
from .services import conversation_messages, dm_conversation_messages, enqueue_direct_reply, enqueue_reply, process_reply, recover_stale_jobs, today_start


class AssistantTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.official = User.objects.create(username="xiaok", display_name="小 K", created_at="x")
        cls.alice = User.objects.create(username="alice", email="private@example.invalid", created_at="x")
        cls.bob = User.objects.create(username="bob", created_at="x")
        OfficialCommunitySettings.objects.create(account=cls.official)
        UserFollow.objects.create(follower=cls.alice, following=cls.official, created_at="x")

    def setUp(self):
        self.config = AssistantSettings.objects.create(enabled=True, base_url="https://chat.example.invalid/v1", model="configured-model", api_key_ciphertext=encrypt_key("secret-for-test"))
        self.client.force_login(self.alice)
        self.admin = Client(); session = self.admin.session
        session["admin_username"] = "root"; session["admin_is_super"] = True; session["admin_level"] = 3; session.save()

    def post(self, content="@xiaok 你好", author="alice"):
        return Murmur.objects.create(author_username=author, content=content, client_key=f"post-{Murmur.objects.count()}", created_at="2026-01-01")

    def send(self, client, path, body):
        return client.post(path, json.dumps(body), content_type="application/json")

    def test_settings_encrypt_key_preserve_blank_and_remain_independent_of_imaging(self):
        provider = ImagingProvider.objects.create(name="image-only", base_url="https://image.invalid", model="image-model", api_key="image-secret")
        payload = {"enabled": True, "base_url": "https://new.invalid", "model": "new-model", "api_key": "new-private-key", "persona": "友善", "knowledge": "只讨论 KFlow"}
        response = self.send(self.admin, "/api/admin/community-ai/settings", payload)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("new-private-key", response.content.decode())
        self.config.refresh_from_db()
        self.assertNotEqual(self.config.api_key_ciphertext, "new-private-key")
        self.assertEqual(decrypt_key(self.config.api_key_ciphertext), "new-private-key")
        self.assertEqual(self.config.base_url, "https://new.invalid/v1")
        self.assertEqual(self.send(self.admin, "/api/admin/community-ai/settings", {"api_key": ""}).status_code, 200)
        self.config.refresh_from_db(); self.assertEqual(decrypt_key(self.config.api_key_ciphertext), "new-private-key")
        self.assertEqual(self.send(self.admin, "/api/admin/community-ai/settings", {"clear_api_key": True}).status_code, 200)
        self.config.refresh_from_db(); self.assertEqual(self.config.api_key_ciphertext, "")
        provider.refresh_from_db(); self.assertEqual(provider.api_key, "image-secret")
        self.assertEqual(provider.model, "image-model")

    def test_reply_limits_validated_saved_and_reported(self):
        for body in ({"daily_limit_per_user": -1}, {"daily_limit_total": 100001}, {"min_interval_seconds": 3601},
                     {"daily_limit_per_user": "10"}, {"daily_limit_total": 1.5}, {"min_interval_seconds": True}):
            self.assertEqual(self.send(self.admin, "/api/admin/community-ai/settings", body).status_code, 400, body)
        response = self.send(self.admin, "/api/admin/community-ai/settings",
                             {"daily_limit_per_user": 5, "min_interval_seconds": 30, "daily_limit_total": 50})
        self.assertEqual(response.status_code, 200)
        settings = response.json()["settings"]
        self.assertEqual((settings["daily_limit_per_user"], settings["min_interval_seconds"], settings["daily_limit_total"]), (5, 30, 50))
        self.assertEqual(settings["today_requests"], 0)
        self.config.refresh_from_db()
        self.assertEqual((self.config.daily_limit_per_user, self.config.min_interval_seconds, self.config.daily_limit_total), (5, 30, 50))

    def test_quota_day_boundary_uses_beijing_midnight(self):
        start = datetime.fromisoformat(today_start())
        self.assertEqual(start.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%H:%M:%S"), "00:00:00")

    def test_per_user_daily_limit_silently_skips_and_ignores_skipped_jobs(self):
        self.config.daily_limit_per_user = 2; self.config.save()
        self.assertIsNotNone(enqueue_reply(self.post()))
        self.assertIsNotNone(enqueue_reply(self.post()))
        self.assertIsNone(enqueue_reply(self.post()))
        self.assertEqual(AssistantReplyJob.objects.count(), 2)
        AssistantReplyJob.objects.update(status="skipped")
        self.assertIsNotNone(enqueue_reply(self.post()), "被跳过的任务不占用当天额度")

    def test_global_daily_limit_stops_every_requester(self):
        User.objects.create(username="carol", created_at="x")
        self.config.daily_limit_total = 1; self.config.save()
        self.assertIsNotNone(enqueue_reply(self.post()))
        other = Murmur.objects.create(author_username="carol", content="@xiaok 你好", client_key="post-carol", created_at="2026-01-01")
        self.assertIsNone(enqueue_reply(other))
        self.assertEqual(AssistantReplyJob.objects.count(), 1)

    def test_min_interval_blocks_rapid_repeat_requests(self):
        self.config.min_interval_seconds = 30; self.config.save()
        first = enqueue_reply(self.post())
        self.assertIsNotNone(first)
        self.assertIsNone(enqueue_reply(self.post()))
        AssistantReplyJob.objects.filter(pk=first.pk).update(created_at=(timezone.now() - timedelta(seconds=31)).isoformat())
        self.assertIsNotNone(enqueue_reply(self.post()))

    def test_yesterdays_jobs_do_not_consume_todays_quota(self):
        self.config.daily_limit_per_user = 1; self.config.save()
        job = enqueue_reply(self.post())
        self.assertIsNotNone(job)
        AssistantReplyJob.objects.filter(pk=job.pk).update(created_at=(timezone.now() - timedelta(days=1)).isoformat())
        self.assertIsNotNone(enqueue_reply(self.post()))

    def test_dm_reply_respects_daily_limit(self):
        self.config.daily_limit_per_user = 1; self.config.save()
        first = PrivateMessage.objects.create(sender=self.alice, recipient=self.official, content="在吗", client_key="dm-limit-1")
        self.assertIsNotNone(enqueue_direct_reply(first))
        AssistantReplyJob.objects.update(status="completed")
        second = PrivateMessage.objects.create(sender=self.alice, recipient=self.official, content="再问一句", client_key="dm-limit-2")
        self.assertIsNone(enqueue_direct_reply(second))
        self.assertEqual(AssistantReplyJob.objects.count(), 1)

    def test_permissions_csrf_and_validation(self):
        for path in ("settings", "test", "records"):
            url = f"/api/admin/community-ai/{path}"
            self.assertEqual(Client().get(url).status_code, 401)
            self.assertEqual(self.client.get(url).status_code, 401)
        lower = Client(); session = lower.session
        session["admin_username"] = "lower"; session["admin_level"] = 3; session["admin_is_super"] = False; session.save()
        self.assertEqual(lower.get("/api/admin/community-ai/settings").status_code, 403)
        strict = Client(enforce_csrf_checks=True); session = strict.session
        session["admin_username"] = "root"; session["admin_is_super"] = True; session["admin_level"] = 3; session.save()
        self.assertEqual(self.send(strict, "/api/admin/community-ai/settings", {}).status_code, 403)
        for body in ({"enabled": "yes"}, {"base_url": "https://user:pass@example.com"}, {"api_key": "a\nb"}, {"model": []}, {"persona": "x" * 4001}, {"clear_api_key": True, "api_key": "new"}):
            self.assertEqual(self.send(self.admin, "/api/admin/community-ai/settings", body).status_code, 400)
        OfficialCommunitySettings.objects.update(account=None)
        self.assertEqual(self.send(self.admin, "/api/admin/community-ai/settings", {"enabled": True}).status_code, 400)

    @patch("apps.community_ai.views.complete", return_value="测试回答")
    def test_preview_uses_unsaved_config_without_publishing_or_saving(self, model):
        response = self.send(self.admin, "/api/admin/community-ai/test", {"base_url": "https://test.invalid/v1", "model": "test-model", "api_key": "preview-key", "prompt": "测试一下"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["reply"], "测试回答")
        cfg, messages = model.call_args.args
        self.assertEqual(cfg.model, "test-model")
        self.assertEqual(decrypt_key(cfg.api_key_ciphertext), "preview-key")
        self.assertEqual(messages[-1]["content"], "测试一下")
        self.config.refresh_from_db(); self.assertEqual(self.config.model, "configured-model")
        self.assertFalse(MurmurComment.objects.exists()); self.assertFalse(AssistantReplyJob.objects.exists())

    @patch("apps.community_ai.services.complete", return_value="你好，我是小 K 👋")
    def test_post_mention_end_to_end_exact_notification_and_no_duplicate_on_replay(self, model):
        body = {"content": "@xiaok 你好", "client_key": "ai-request-post-001"}
        with self.captureOnCommitCallbacks(execute=True):
            response = self.send(self.client, "/api/murmurs", body)
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json()["ai_reply_queued"])
        job = AssistantReplyJob.objects.get()
        process_reply(job.pk); process_reply(job.pk)
        self.assertEqual(model.call_count, 1)
        job.refresh_from_db(); self.assertEqual(job.status, "completed")
        self.assertEqual(job.result_comment.author_username, "xiaok")
        notification = Notification.objects.get(recipient=self.alice)
        self.assertIn(f"&comment={job.result_comment_id}#murmur-comment-{job.result_comment_id}", notification.link)
        self.assertEqual(self.send(self.client, "/api/murmurs", body).status_code, 200)
        self.assertEqual(AssistantReplyJob.objects.count(), 1)
        item = self.client.get(f"/api/murmurs/{job.post_id}/comments").json()["items"][0]
        self.assertTrue(item["is_ai_reply"])

    @patch("apps.community_ai.services.complete", return_value="你好，我在的～")
    def test_direct_message_end_to_end_reply_notification_and_record(self, model):
        response = self.send(self.client, "/api/messages/xiaok", {"content": "在吗？", "client_key": "dm-request-001"})
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json()["ai_reply_queued"])
        job = AssistantReplyJob.objects.get()
        self.assertIsNone(job.post_id)
        self.assertEqual(job.source_key, f"dm:{job.source_message_id}")
        process_reply(job.pk); process_reply(job.pk)
        self.assertEqual(model.call_count, 1)
        job.refresh_from_db(); self.assertEqual(job.status, "completed")
        self.assertEqual(PrivateMessage.objects.filter(sender=self.official, recipient=self.alice).count(), 1)
        self.assertEqual(Notification.objects.filter(recipient=self.alice, type="message", actor_username="xiaok").count(), 1)
        messages = model.call_args.args[1]
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[-1], {"role": "user", "content": "在吗？"})
        record = self.admin.get("/api/admin/community-ai/records").json()["items"][0]
        self.assertEqual(record["source"], "dm")
        self.assertIn("/messages?user=alice", record["link"])
        self.assertEqual(record["reply"], "你好，我在的～")
        self.assertEqual(self.send(self.client, "/api/messages/xiaok", {"content": "在吗？", "client_key": "dm-request-001"}).json().get("ai_reply_queued"), None)

    def test_direct_message_context_maps_roles_and_limits_history(self):
        for index in range(12):
            PrivateMessage.objects.create(sender=self.alice, recipient=self.official, content=f"历史消息{index}", client_key=f"dm-old-{index}")
        PrivateMessage.objects.create(sender=self.official, recipient=self.alice, content="此前人工回复", client_key="dm-old-answer")
        job_message = PrivateMessage.objects.create(sender=self.alice, recipient=self.official, content="最新问题", client_key="dm-latest")
        job = enqueue_direct_reply(job_message)
        messages = dm_conversation_messages(job, self.config)
        self.assertEqual(len(messages), 11)
        self.assertEqual(messages[-1], {"role": "user", "content": "最新问题"})
        self.assertTrue(any(item["role"] == "assistant" and item["content"] == "此前人工回复" for item in messages))
        self.assertFalse(any("历史消息0" == (item["content"] or "") for item in messages))

    def test_direct_message_enqueue_gating(self):
        stranger = PrivateMessage.objects.create(sender=self.alice, recipient=self.bob, content="你好", client_key="dm-bob")
        self.assertIsNone(enqueue_direct_reply(stranger))
        self.config.enabled = False; self.config.save()
        self.assertIsNone(enqueue_direct_reply(PrivateMessage.objects.create(sender=self.alice, recipient=self.official, content="在吗", client_key="dm-off")))
        self.config.enabled = True; self.config.save()
        first = PrivateMessage.objects.create(sender=self.alice, recipient=self.official, content="在吗", client_key="dm-on")
        self.assertIsNotNone(enqueue_direct_reply(first))
        second = PrivateMessage.objects.create(sender=self.alice, recipient=self.official, content="再问一句", client_key="dm-second")
        self.assertIsNone(enqueue_direct_reply(second), "同一用户已有待处理私聊任务时不应重复入队")
        self.assertIsNone(enqueue_direct_reply(PrivateMessage.objects.create(sender=self.official, recipient=self.alice, content="官方发言", client_key="dm-from-xiaok")))
        virtual = User.objects.create(username="fan_1", is_system_generated=True, created_at="x")
        self.assertIsNone(enqueue_direct_reply(PrivateMessage.objects.create(sender=virtual, recipient=self.official, content="水军", client_key="dm-virtual")))
        MurmurBlock.objects.create(username="xiaok", blocked_username="alice")
        self.assertIsNone(enqueue_direct_reply(PrivateMessage.objects.create(sender=self.alice, recipient=self.official, content="被屏蔽", client_key="dm-blocked")))

    @patch("apps.community_ai.services.complete", return_value="不应发布")
    def test_direct_message_skipped_when_settings_change_during_generation(self, model):
        message = PrivateMessage.objects.create(sender=self.alice, recipient=self.official, content="在吗", client_key="dm-race")
        job = enqueue_direct_reply(message)
        def generate(*args):
            AssistantSettings.objects.update(enabled=False)
            return "不应发布"
        with patch("apps.community_ai.services.complete", side_effect=generate): process_reply(job.pk)
        job.refresh_from_db(); self.assertEqual(job.status, "skipped")
        self.assertFalse(PrivateMessage.objects.filter(sender=self.official).exists())

    @patch("apps.community_ai.services.complete", return_value="继续回答")
    def test_reply_to_ai_continues_conversation_and_ai_never_triggers_itself(self, model):
        post = self.post()
        first = enqueue_reply(post); process_reply(first.pk); first.refresh_from_db()
        response = self.send(self.client, f"/api/murmurs/{post.pk}/comments", {"content": "再说详细一点", "reply_to": first.result_comment_id})
        self.assertTrue(response.json()["ai_reply_queued"])
        followup = AssistantReplyJob.objects.exclude(pk=first.pk).get()
        process_reply(followup.pk)
        messages = model.call_args.args[1]
        self.assertTrue(any(item["role"] == "assistant" and item["content"] == "继续回答" for item in messages))
        self.assertIn("再说详细一点", messages[-1]["content"])
        self.assertIsNone(enqueue_reply(post, first.result_comment))
        self.assertEqual(AssistantReplyJob.objects.count(), 2)

    def test_only_mentions_or_replies_to_ai_are_eligible(self):
        plain = self.post("普通日常")
        self.assertIsNone(enqueue_reply(plain))
        UserFollow.objects.filter(follower=self.alice, following=self.official).delete()
        self.assertIsNone(enqueue_reply(self.post()))
        manual = MurmurComment.objects.create(murmur=plain, author_username="xiaok", content="人工回复", client_key="manual")
        reply = MurmurComment.objects.create(murmur=plain, author_username="alice", content="接一句", reply_to=manual, client_key="reply-manual")
        self.assertIsNone(enqueue_reply(plain, reply))
        self.config.enabled = False; self.config.save()
        self.assertIsNone(enqueue_reply(self.post()))

    @patch("apps.community_ai.services.complete", return_value="好的")
    def test_comment_mentions_reply_to_exact_source_and_allow_only_public_chain(self, model):
        post = self.post("公开内容", author="bob")
        unrelated = MurmurComment.objects.create(murmur=post, author_username="bob", content="不相关的其他评论", client_key="unrelated")
        comment = MurmurComment.objects.create(murmur=post, author_username="alice", content="@xiaok 请回答", client_key="question")
        job = enqueue_reply(post, comment); process_reply(job.pk); job.refresh_from_db()
        self.assertEqual(job.result_comment.reply_to_id, comment.pk)
        packed = json.dumps(model.call_args.args[1], ensure_ascii=False)
        self.assertNotIn(unrelated.content, packed)
        self.assertNotIn("private@example.invalid", packed)
        self.assertNotIn("secret-for-test", packed)

    def test_blocks_in_both_directions_prevent_enqueue(self):
        for left, right in [("alice", "xiaok"), ("xiaok", "alice")]:
            MurmurBlock.objects.all().delete(); MurmurBlock.objects.create(username=left, blocked_username=right)
            self.assertIsNone(enqueue_reply(self.post()))

    @patch("apps.community_ai.services.complete", return_value="仍可以回答")
    def test_unrelated_block_does_not_hide_requesters_own_post(self, model):
        MurmurBlock.objects.create(username="alice", blocked_username="bob")
        job = enqueue_reply(self.post()); self.assertIsNotNone(job)
        process_reply(job.pk); job.refresh_from_db(); self.assertEqual(job.status, "completed")

    def test_deleted_or_blocked_source_is_skipped_without_model_call(self):
        for change in ("deleted", "blocked"):
            MurmurBlock.objects.all().delete()
            post = self.post(); job = enqueue_reply(post)
            if change == "deleted": Murmur.objects.filter(pk=post.pk).update(is_deleted=True)
            else: MurmurBlock.objects.create(username="alice", blocked_username="xiaok")
            with patch("apps.community_ai.services.complete") as model:
                process_reply(job.pk); model.assert_not_called()
            job.refresh_from_db(); self.assertEqual(job.status, "skipped")

    def test_rechecks_visibility_switch_and_identity_after_generation(self):
        for change in ("delete", "disable", "revision", "account", "block"):
            OfficialCommunitySettings.objects.update(account=self.official)
            self.config.enabled = True; self.config.save(); MurmurBlock.objects.all().delete()
            post = self.post(); job = enqueue_reply(post)
            def generate(*args):
                if change == "delete": Murmur.objects.filter(pk=post.pk).update(is_deleted=True)
                elif change == "disable": AssistantSettings.objects.update(enabled=False)
                elif change == "revision": AssistantSettings.objects.update(revision=self.config.revision + 1)
                elif change == "account": OfficialCommunitySettings.objects.update(account=self.bob)
                else: MurmurBlock.objects.create(username="xiaok", blocked_username="alice")
                return "不应发布"
            with patch("apps.community_ai.services.complete", side_effect=generate): process_reply(job.pk)
            job.refresh_from_db(); self.assertEqual(job.status, "skipped", change)
            self.assertIsNone(job.result_comment_id)

    def test_retryable_failure_retries_once_without_duplicate_comment(self):
        job = enqueue_reply(self.post())
        with patch("apps.community_ai.services.complete", side_effect=[ProviderError("暂时失败", retryable=True), "恢复了"]) as model:
            process_reply(job.pk); process_reply(job.pk)
            self.assertEqual(model.call_count, 1)
            AssistantReplyJob.objects.filter(pk=job.pk).update(next_attempt_at="")
            process_reply(job.pk)
        job.refresh_from_db(); self.assertEqual(job.status, "completed"); self.assertEqual(job.attempts, 2)
        self.assertEqual(MurmurComment.objects.filter(author_username="xiaok").count(), 1)

    def test_stale_claim_recovery_and_old_worker_cannot_publish(self):
        job = enqueue_reply(self.post())
        AssistantReplyJob.objects.filter(pk=job.pk).update(status="processing", attempts=1, started_at=(timezone.now() - timedelta(minutes=5)).isoformat(), claim_token="old")
        self.assertEqual(recover_stale_jobs(), 1)
        def stolen(*args):
            AssistantReplyJob.objects.filter(pk=job.pk).update(claim_token="other-worker")
            return "不应发布"
        with patch("apps.community_ai.services.complete", side_effect=stolen): process_reply(job.pk)
        self.assertFalse(MurmurComment.objects.exists())

    def test_failed_record_retry_and_worker_command(self):
        job = enqueue_reply(self.post())
        with patch("apps.community_ai.services.complete", side_effect=ProviderError("API 鉴权失败")): process_reply(job.pk)
        job.refresh_from_db(); self.assertEqual(job.status, "failed")
        response = self.send(self.admin, f"/api/admin/community-ai/records/{job.pk}/retry", {})
        self.assertEqual(response.status_code, 200)
        with patch("apps.community_ai.services.complete", return_value="重试成功"):
            call_command("process_community_ai_jobs", once=True, stdout=io.StringIO())
        job.refresh_from_db(); self.assertEqual(job.status, "completed")
        record = self.admin.get("/api/admin/community-ai/records").json()["items"][0]
        self.assertEqual(record["reply"], "重试成功")
        self.assertEqual(self.send(self.admin, f"/api/admin/community-ai/records/{job.pk}/retry", {}).status_code, 409)

    @patch("apps.community_ai.services.complete", return_value="新回答")
    def test_conflicting_manual_publish_key_is_not_overwritten_or_marked_ai(self, model):
        job = enqueue_reply(self.post())
        manual = MurmurComment.objects.create(murmur=job.post, author_username="xiaok", content="原有人工内容", client_key=f"community-ai-{job.id.hex}")
        process_reply(job.pk)
        job.refresh_from_db(); manual.refresh_from_db()
        self.assertEqual(job.status, "failed")
        self.assertIsNone(job.result_comment_id)
        self.assertEqual(manual.content, "原有人工内容")


class ProviderTests(TestCase):
    def test_actual_http_transport_with_local_compatible_service(self):
        observed = {}
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                observed["path"] = self.path
                observed["authorization"] = self.headers.get("Authorization")
                observed["payload"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                data = json.dumps({"choices": [{"message": {"content": "本地接口已接通"}}]}, ensure_ascii=False).encode()
                self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            config = AssistantSettings(base_url=f"http://127.0.0.1:{server.server_port}/v1", model="local-model", api_key_ciphertext=encrypt_key("local-key"))
            self.assertEqual(complete(config, [{"role": "user", "content": "你好"}]), "本地接口已接通")
            self.assertEqual(observed["path"], "/v1/chat/completions")
            self.assertEqual(observed["authorization"], "Bearer local-key")
            self.assertEqual(observed["payload"]["model"], "local-model")
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=2)

    def test_url_normalization_and_rejected_credentials(self):
        self.assertEqual(normalize_url("https://api.example.com/"), "https://api.example.com/v1")
        self.assertEqual(normalize_url("https://api.example.com/proxy/v1/"), "https://api.example.com/proxy/v1")
        for bad in ("file:///tmp/key", "https://user:pass@host/v1", "https://host/v1?key=x", "https://host/#fragment", "http://host:bad"):
            with self.assertRaises(ValueError): normalize_url(bad)

    @patch("apps.community_ai.provider.urllib.request.build_opener")
    def test_payload_full_endpoint_and_text_array_output(self, build):
        response = Mock(); response.read.return_value = json.dumps({"choices": [{"message": {"content": [{"type": "text", "text": "你好"}]}}]}).encode()
        build.return_value.open.return_value.__enter__.return_value = response
        config = AssistantSettings(base_url="https://test.invalid/v1/chat/completions", model="my-model", api_key_ciphertext=encrypt_key("my-key"))
        self.assertEqual(complete(config, [{"role": "user", "content": "你好"}]), "你好")
        request = build.return_value.open.call_args.args[0]
        self.assertEqual(request.full_url, config.base_url)
        self.assertEqual(request.get_header("Authorization"), "Bearer my-key")
        self.assertEqual(json.loads(request.data)["model"], "my-model")

    @patch("apps.community_ai.provider.urllib.request.build_opener")
    def test_upstream_error_does_not_leak_secret_and_empty_reply_is_failure(self, build):
        config = AssistantSettings(base_url="https://test.invalid/v1", model="model")
        build.return_value.open.side_effect = urllib.error.HTTPError(config.base_url, 401, "secret-in-provider-error", {}, io.BytesIO(b"secret-in-provider-body"))
        with self.assertRaises(ProviderError) as caught: complete(config, [])
        self.assertNotIn("secret", str(caught.exception))
        build.return_value.open.side_effect = None
        response = Mock(); response.read.return_value = b'{"choices": [{"message": {"content": ""}}]}'
        build.return_value.open.return_value.__enter__.return_value = response
        with self.assertRaises(ProviderError): complete(config, [])

    @patch("apps.community_ai.provider.urllib.request.build_opener")
    def test_long_output_remains_within_comment_limit(self, build):
        response = Mock(); response.read.return_value = json.dumps({"choices": [{"message": {"content": "字" * 700}}]}).encode()
        build.return_value.open.return_value.__enter__.return_value = response
        result = complete(AssistantSettings(base_url="http://localhost:8317/v1", model="model"), [])
        self.assertEqual(len(result), 500)
