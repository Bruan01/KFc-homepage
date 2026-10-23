import json
from datetime import datetime, timezone as utc
from unittest.mock import patch
from django.test import TestCase, Client, override_settings
from django.core.cache import cache
from django.contrib.sessions.models import Session
from apps.accounts.models import User, UserFollow, AdminAccount
from apps.forum.models import ForumTopic, ForumCategory, ForumImage, ForumPoll, ForumPollBallot
from apps.murmurs.models import Murmur, MurmurComment, MurmurBlock, MurmurReadState
from apps.messaging.models import PrivateMessage
from apps.notifications.models import Notification


class CommunityUpgradeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice=User.objects.create_user(username="upgrade-alice", password="OldPassword!2026",email="alice@example.com")
        cls.bob=User.objects.create_user(username="upgrade-bob", password="OldPassword!2026")
        cls.carol=User.objects.create_user(username="upgrade-carol", password="OldPassword!2026")
        cls.category=ForumCategory.objects.create(slug="upgrade-tests",name="Upgrade")
        cls.topic=ForumTopic.objects.create(category=cls.category,author_username=cls.alice.username,title="Test",content="content")
        UserFollow.objects.create(follower=cls.alice,following=cls.bob,created_at="2026-10-23T00:00:00Z")

    def setUp(self):
        cache.clear()
        self.client.force_login(self.alice)

    def send(self,url,body,client=None):
        return (client or self.client).post(url,json.dumps(body),content_type="application/json")

    def post(self,**kwargs):
        return Murmur.objects.create(author_username=self.alice.username,content="today",client_key=f"key-{Murmur.objects.count()}",**kwargs)

    def test_mentions_only_resolve_existing_followed_unblocked_users(self):
        content=f"@{self.bob.username} @{self.carol.username} @missing-user"
        row=Murmur.objects.create(author_username=self.alice.username,content=content,client_key="mentions")
        result=self.client.get(f"/api/murmurs/{row.pk}").json()["item"]
        self.assertEqual(result["mention_usernames"],[self.bob.username])
        MurmurBlock.objects.create(username=self.bob.username,blocked_username=self.alice.username)
        self.assertEqual(self.client.get(f"/api/murmurs/{row.pk}").json()["item"]["mention_usernames"],[])

    def test_forum_mentions_exclude_code_and_notify_followed_users(self):
        response=self.send("/api/forum/topics/create",{"title":"mentions","category":self.category.slug,
                  "content":f"@{self.bob.username} @{self.carol.username} @missing-user `@{self.carol.username}`"})
        self.assertEqual(response.status_code,201)
        topic=response.json()["topic"]
        self.assertEqual(topic["mention_usernames"],[self.bob.username])
        self.assertEqual(set(Notification.objects.filter(type="mention").values_list("recipient_id",flat=True)),{self.bob.pk})

    def test_reply_mention_notification_links_to_exact_reply_page(self):
        self.topic.author_username=self.carol.username;self.topic.save(update_fields=["author_username"])
        response=self.send(f"/api/forum/topics/{self.topic.pk}/replies",{"content":f"hello @{self.bob.username} 😀"})
        self.assertEqual(response.status_code,201)
        reply=response.json()["reply"]
        self.assertEqual(reply["mention_usernames"],[self.bob.username])
        notice=Notification.objects.get(recipient=self.bob,type="mention")
        self.assertIn(f"comment={reply['id']}",notice.link)

    def test_forum_reply_images_are_owned_and_allow_image_only(self):
        image=ForumImage.objects.create(uploader_username=self.alice.username,file="forum/owned.png",width=40,height=40)
        response=self.send(f"/api/forum/topics/{self.topic.pk}/replies",{"content":"","images":[image.pk]})
        self.assertEqual(response.status_code,201)
        self.assertEqual(response.json()["reply"]["images"][0]["id"],image.pk)
        other=Client();other.force_login(self.bob)
        self.assertEqual(self.send(f"/api/forum/topics/{self.topic.pk}/replies",{"images":[image.pk]},other).status_code,400)

    def make_poll(self,multiple=False):
        response=self.send("/api/forum/topics/create",{"title":"Poll","content":"Discuss","category":self.category.slug,
                           "poll":{"question":"Which?","multiple":multiple,"options":["One","Two","Three"]}})
        self.assertEqual(response.status_code,201)
        topic_id=response.json()["topic"]["id"]
        poll=self.client.get(f"/api/forum/topics/{topic_id}").json()["topic"]["poll"]
        return topic_id,[row["id"] for row in poll["options"]]

    def test_poll_single_choice_authorization_validation_and_retry(self):
        topic,ids=self.make_poll()
        url=f"/api/forum/topics/{topic}/poll/vote"
        self.assertEqual(self.send(url,{"options":[ids[0]]},Client()).status_code,401)
        self.assertEqual(self.send(url,{"options":ids[:2]}).status_code,400)
        self.assertEqual(self.send(url,{"options":[999999]}).status_code,400)
        self.assertEqual(self.send(url,{"options":[ids[0]]}).status_code,200)
        self.assertEqual(self.send(url,{"options":[ids[0]]}).json()["poll"]["voters"],1)
        self.assertEqual(self.send(url,{"options":[ids[1]]}).status_code,409)
        self.assertEqual(ForumPollBallot.objects.filter(poll__topic_id=topic).count(),1)

    def test_multi_choice_poll_counts_voters_and_rejects_duplicate_or_foreign_options(self):
        topic,ids=self.make_poll(True)
        other,otherids=self.make_poll()
        url=f"/api/forum/topics/{topic}/poll/vote"
        self.assertEqual(self.send(url,{"options":[otherids[0]]}).status_code,400)
        self.assertEqual(self.send(url,{"options":[ids[0],ids[0]]}).status_code,400)
        result=self.send(url,{"options":ids[:2]}).json()["poll"]
        self.assertEqual(result["voters"],1)
        self.assertEqual(sum(row["votes"] for row in result["options"]),2)

    def test_invalid_poll_does_not_create_topic(self):
        before=ForumTopic.objects.count()
        response=self.send("/api/forum/topics/create",{"title":"Invalid","content":"test","category":self.category.slug,
                           "poll":{"question":"Which?","multiple":False,"options":["same","same"]}})
        self.assertEqual(response.status_code,400)
        self.assertEqual(ForumTopic.objects.count(),before)

    def test_date_range_is_ten_per_page_and_keeps_pins_within_range(self):
        rows=[]
        for day in [1,2,3]:
            for hour in range(10):
                rows.append(self.post(created_at=f"2026-10-{day:02d}T{hour:02d}:00:00+00:00"))
        rows[0].is_pinned=True;rows[0].save(update_fields=["is_pinned"])
        outside=self.post(created_at="2026-09-01T00:00:00+00:00",is_pinned=True)
        ids=[]
        for page in [1,2,3]:
            response=self.client.get("/api/murmurs",{"page":page,"start":"2026-10-01","end":"2026-10-03"})
            self.assertEqual(response.status_code,200,response.content)
            data=response.json();self.assertEqual(data["total"],30);self.assertEqual(data["total_pages"],3)
            self.assertEqual(len(data["items"]),10);ids.extend(row["id"] for row in data["items"])
        self.assertEqual(len(set(ids)),30);self.assertEqual(ids[0],rows[0].pk);self.assertNotIn(outside.pk,ids)

    def test_date_boundaries_use_shanghai_not_utc(self):
        previous=self.post(created_at="2026-10-01T15:59:59+00:00")
        start=self.post(created_at="2026-10-01T16:00:00+00:00")
        end=self.post(created_at="2026-10-02T15:59:59+00:00")
        following=self.post(created_at="2026-10-02T16:00:00+00:00")
        data=self.client.get("/api/murmurs",{"page":1,"start":"2026-10-02","end":"2026-10-02"}).json()
        self.assertEqual({row["id"] for row in data["items"]},{start.pk,end.pk})

    def test_default_page_shows_today_and_invalid_ranges_are_rejected(self):
        from django.utils import timezone
        today=self.post(created_at=timezone.now().isoformat())
        yesterday=self.post(created_at="2020-01-01T00:00:00Z")
        ids={row["id"] for row in self.client.get("/api/murmurs?page=1").json()["items"]}
        self.assertIn(today.pk,ids);self.assertNotIn(yesterday.pk,ids)
        for params in [{"page":"bad"},{"start":"bad","end":"bad","page":1},{"start":"2026-10-03","end":"2026-10-01","page":1}]:
            self.assertEqual(self.client.get("/api/murmurs",params).status_code,400)

    def test_unread_replies_clear_only_after_read_and_respect_user_scope(self):
        post=self.post(created_at="2020-01-01T00:00:00Z")
        comment=MurmurComment.objects.create(murmur=post,author_username=self.bob.username,content="reply",client_key="read-test")
        result=self.client.get("/api/murmurs?page=1&unread=1")
        self.assertEqual(result.status_code,200,result.content)
        self.assertEqual(result.json()["total"],1)
        self.assertEqual(self.send(f"/api/murmurs/{post.pk}/read",{"upto":comment.pk}).status_code,200)
        self.assertEqual(self.client.get("/api/murmurs?page=1&unread=1").json()["total"],0)
        MurmurComment.objects.create(murmur=post,author_username=self.bob.username,content="new",client_key="new-read-test")
        self.assertEqual(self.client.get("/api/murmurs?page=1&unread=1").json()["total"],1)
        self.assertEqual(Client().get("/api/murmurs?page=1&unread=1").status_code,401)

    def test_private_messages_are_private_idempotent_and_blockable(self):
        url=f"/api/messages/{self.bob.username}"
        response=self.send(url,{"content":"hello 😀","client_key":"message-retry-123"})
        self.assertEqual(response.status_code,201,response.content)
        self.assertEqual(self.send(url,{"content":"hello 😀","client_key":"message-retry-123"}).status_code,200)
        self.assertEqual(PrivateMessage.objects.count(),1)
        self.assertEqual(self.send(url,{"content":"changed","client_key":"message-retry-123"}).status_code,409)
        stranger=Client();stranger.force_login(self.carol)
        self.assertEqual(stranger.get(url).json()["items"],[])
        self.assertEqual(stranger.get("/api/messages").json()["items"],[])
        MurmurBlock.objects.create(username=self.bob.username,blocked_username=self.alice.username)
        self.assertEqual(self.send(url,{"content":"blocked","client_key":"blocked-message"}).status_code,403)

    def test_message_unread_count_and_read_scope(self):
        row=PrivateMessage.objects.create(sender=self.bob,recipient=self.alice,content="new",client_key="new-12345")
        self.assertEqual(self.client.get("/api/messages").json()["unread"],1)
        self.send(f"/api/messages/{self.carol.username}/read",{"upto":row.pk})
        row.refresh_from_db();self.assertFalse(row.is_read)
        self.send(f"/api/messages/{self.bob.username}/read",{"upto":row.pk})
        self.assertEqual(self.client.get("/api/messages").json()["unread"],0)

    def test_message_csrf_self_synthetic_and_size(self):
        client=Client(enforce_csrf_checks=True);client.force_login(self.alice)
        url=f"/api/messages/{self.bob.username}"
        self.assertEqual(self.send(url,{"content":"hello","client_key":"csrf-test-123"},client).status_code,403)
        self.assertEqual(self.send(f"/api/messages/{self.alice.username}",{"content":"x","client_key":"self-test-123"}).status_code,400)
        self.assertEqual(self.send(url,{"content":"x"*2001,"client_key":"large-test-123"}).status_code,400)

    def test_account_settings_are_private_and_never_expose_password(self):
        self.assertEqual(Client().get("/api/account/settings").status_code,401)
        response=self.client.get("/api/account/settings",HTTP_X_FORWARDED_FOR="8.8.8.8",REMOTE_ADDR="127.0.0.1")
        data=response.json();self.assertEqual(data["username"],self.alice.username);self.assertEqual(data["email"],self.alice.email)
        self.assertNotIn("password",data);self.assertNotIn(self.alice.password,response.content.decode())
        self.assertEqual(data["ip"],"127.0.0.1");self.assertEqual(response["Cache-Control"],"no-store")

    def test_password_change_requires_current_and_revokes_other_devices(self):
        other=Client();other.force_login(self.alice);other_key=other.session.session_key
        body={"current_password":"wrong","new_password":"NewPassword!2026","confirm_password":"NewPassword!2026"}
        self.assertEqual(self.send("/api/account/password",body).status_code,403)
        body["current_password"]="OldPassword!2026"
        response=self.send("/api/account/password",body)
        self.assertEqual(response.status_code,200,response.content)
        self.alice.refresh_from_db();self.assertTrue(self.alice.check_password(body["new_password"]))
        self.assertFalse(Session.objects.filter(session_key=other_key).exists())
        self.assertEqual(self.client.get("/api/account/settings").status_code,200)

    def test_admin_passwords_stay_synced(self):
        AdminAccount.objects.create(username=self.alice.username,password_hash=self.alice.password,admin_level=2,created_at="2026-10-23")
        self.assertEqual(self.send("/api/account/password",{"current_password":"OldPassword!2026","new_password":"NewPassword!2026","confirm_password":"NewPassword!2026"}).status_code,200)
        self.alice.refresh_from_db();self.assertEqual(AdminAccount.objects.get(username=self.alice.username).password_hash,self.alice.password)

    @override_settings(ADMIN_USERNAME="upgrade-root",ADMIN_PASSWORD="OldRootPassword!2026")
    def test_super_admin_new_password_replaces_bootstrap_password(self):
        root=User.objects.create_user(username="upgrade-root",password="random-internal-password")
        AdminAccount.objects.create(username=root.username,password_hash=root.password,admin_level=3,is_super=1,created_at="2026-10-23")
        self.assertEqual(self.send("/api/admin/login",{"username":root.username,"password":"OldRootPassword!2026"},Client()).status_code,200)
        client=Client();client.force_login(root)
        response=self.send("/api/account/password",{"current_password":"OldRootPassword!2026","new_password":"NewRootPassword!2026","confirm_password":"NewRootPassword!2026"},client)
        self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(self.send("/api/admin/login",{"username":root.username,"password":"OldRootPassword!2026"},Client()).status_code,401)
        self.assertEqual(self.send("/api/admin/login",{"username":root.username,"password":"NewRootPassword!2026"},Client()).status_code,200)

    def test_message_history_is_bounded_and_paginates_without_leaking(self):
        rows=[PrivateMessage.objects.create(sender=self.bob,recipient=self.alice,content=f"row {i}",client_key=f"history-{i}") for i in range(35)]
        unrelated=PrivateMessage.objects.create(sender=self.bob,recipient=self.carol,content="private other pair",client_key="unrelated-message")
        url=f"/api/messages/{self.bob.username}"
        first=self.client.get(url).json();self.assertEqual(len(first["items"]),30)
        second=self.client.get(url,{"before":first["next_cursor"]}).json()
        ids=[item["id"] for item in second["items"]+first["items"]]
        self.assertEqual(ids,[row.pk for row in rows]);self.assertNotIn(unrelated.pk,ids)
        self.assertIsNone(second["next_cursor"])

    def test_message_rate_limit_cannot_be_bypassed_by_retry_or_second_recipient(self):
        PrivateMessage.objects.bulk_create([PrivateMessage(sender=self.alice,recipient=self.bob,content="limited",client_key=f"limit-{i}") for i in range(15)])
        response=self.send(f"/api/messages/{self.carol.username}",{"content":"too fast","client_key":"rate-limit-new"})
        self.assertEqual(response.status_code,429)

    def test_reply_notification_can_locate_later_pages(self):
        from .models import ForumReply
        rows=[ForumReply.objects.create(topic=self.topic,author_username=self.bob.username,content="reply") for _ in range(35)]
        response=self.client.get(f"/api/forum/topics/{self.topic.pk}",{"comment":rows[-1].pk,"reply_page_size":10})
        self.assertEqual(response.status_code,200)
        topic=response.json()["topic"]
        self.assertEqual(topic["reply_page"],4)
        self.assertIn(rows[-1].pk,[row["id"] for row in topic["replies_detail"]])
