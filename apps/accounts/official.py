"""Official identity, one-time default follows and managed community accounts."""
import secrets
import uuid

from django.contrib.auth.hashers import make_password
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.murmurs.models import MurmurBlock
from .models import OfficialCommunitySettings, OfficialFollowInitialization, User, UserFollow

MAX_TARGET_FOLLOWERS = 10000


def official_account_id():
    return OfficialCommunitySettings.objects.filter(pk=1).values_list("account_id", flat=True).first()


def blocked_with(username):
    rows = MurmurBlock.objects.filter(Q(username=username) | Q(blocked_username=username)).values_list("username", "blocked_username")
    return {name for row in rows for name in row} - {username}


def initialize_official_follow(user, *, using="default"):
    """Called once at creation; retries never restore a user's cancelled follow."""
    official = OfficialCommunitySettings.objects.using(using).filter(pk=1).select_related("account").first()
    if not official or not official.account_id or official.account_id == user.pk:
        return
    with transaction.atomic(using=using):
        _, created = OfficialFollowInitialization.objects.using(using).get_or_create(
            user=user, official_id=official.account_id, defaults={"created_at": timezone.now().isoformat()})
        if not created or user.username in blocked_with(official.account.username):
            return
        UserFollow.objects.using(using).get_or_create(follower=user, following_id=official.account_id,
            defaults={"created_at": timezone.now().isoformat(), "is_managed": user.is_system_generated})


def initialize_existing_users(official):
    rows = list(User.objects.exclude(pk=official.pk).exclude(official_follow_initializations__official=official))
    blocked = blocked_with(official.username)
    now = timezone.now().isoformat()
    OfficialFollowInitialization.objects.bulk_create([
        OfficialFollowInitialization(user=user, official=official, created_at=now) for user in rows
    ], ignore_conflicts=True)
    edges = [UserFollow(follower=user, following=official, created_at=now, is_managed=user.is_system_generated)
             for user in rows if user.username not in blocked]
    before = official.follower_edges.count()
    UserFollow.objects.bulk_create(edges, ignore_conflicts=True)
    return official.follower_edges.count() - before


def adjust_managed_followers(official, target):
    """Only system-managed edges can be removed; user accounts are never deleted."""
    managed = UserFollow.objects.filter(following=official, is_managed=True, follower__is_system_generated=True)
    protected = official.follower_edges.count() - managed.count()
    wanted = max(0, target - protected)
    current = managed.count()
    if current > wanted:
        ids = list(managed.order_by("-pk").values_list("pk", flat=True)[:current - wanted])
        UserFollow.objects.filter(pk__in=ids).delete()
        return {"created_accounts": 0, "added_follows": 0, "removed_follows": len(ids)}
    needed = wanted - current
    if not needed:
        return {"created_accounts": 0, "added_follows": 0, "removed_follows": 0}
    blocked = blocked_with(official.username)
    available = list(User.objects.filter(is_system_generated=True).exclude(pk=official.pk).exclude(username__in=blocked)
                     .exclude(following_edges__following=official).order_by("pk")[:needed])
    new_users = []
    now = timezone.now().isoformat()
    names = ["晨光", "云雀", "南风", "星河", "远帆", "青藤", "灯塔", "拾光"]
    for _ in range(needed - len(available)):
        new_users.append(User(username=f"community_fan_{uuid.uuid4().hex}",
            display_name=f"{secrets.choice(names)}·{secrets.randbelow(10000):04d}",
            password=make_password(None), is_system_generated=True, created_at=now))
    # bulk_create intentionally avoids the default-follow signal; both edges and
    # initialization history are written here in the enclosing admin transaction.
    User.objects.bulk_create(new_users)
    available.extend(new_users)
    UserFollow.objects.bulk_create([UserFollow(follower=user, following=official, created_at=now, is_managed=True) for user in available])
    OfficialFollowInitialization.objects.bulk_create([
        OfficialFollowInitialization(user=user, official=official, created_at=now) for user in available
    ], ignore_conflicts=True)
    return {"created_accounts": len(new_users), "added_follows": len(available), "removed_follows": 0}


def settings_payload(config):
    account = config.account if config else None
    counts = {"follower_count": 0, "managed_follower_count": 0, "other_follower_count": 0}
    if account:
        total = account.follower_edges.count()
        managed = account.follower_edges.filter(is_managed=True, follower__is_system_generated=True).count()
        counts.update(follower_count=total, managed_follower_count=managed, other_follower_count=total - managed)
    return {
        "account": {"id": account.pk, "username": account.username, "display_name": account.display_name or account.username} if account else None,
        "target_follower_count": config.target_follower_count if config else 0,
        "max_target": MAX_TARGET_FOLLOWERS,
        "updated_by": config.updated_by if config else "",
        "updated_at": config.updated_at if config else "",
        **counts,
    }
