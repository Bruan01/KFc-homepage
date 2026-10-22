"""Mentions are plain text; only followed, unblocked accounts receive alerts."""
import re

from django.db.models import Q

from apps.accounts.models import User, UserFollow
from apps.notifications.services import notify
from .models import MurmurBlock

MENTION_RE = re.compile(r"(?<![\w@])@(?:\{([^{}\n]{1,150})\}|([\w-]{1,150}))(?![\w-])")


def recipients(username, content):
    names = {match.group(1) or match.group(2) for match in MENTION_RE.finditer(content)}
    blocked = MurmurBlock.objects.filter(Q(username=username) | Q(blocked_username=username))
    excluded = set(blocked.values_list("username", flat=True)) | set(blocked.values_list("blocked_username", flat=True))
    return list(User.objects.filter(username__in=names, follower_edges__follower__username=username).exclude(username__in=excluded | {username}))


def send_mentions(post, username, content, users, comment_id=None):
    name = User.objects.filter(username=username).values_list("display_name", flat=True).first() or username
    link = f"/murmurs?post={post.pk}"
    if comment_id:
        link += f"&comment={comment_id}#murmur-comment-{comment_id}"
    else:
        link += f"#murmur-{post.pk}"
    for user in users:
        notify(recipient=user, type_="mention", title=f"{name}在{'评论' if comment_id else '碎碎念'}中 @ 了你",
               body=content, link=link, actor_username=username)
