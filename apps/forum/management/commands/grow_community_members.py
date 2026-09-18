# pyright: reportMissingImports=false
"""每天自动增加一名社区成员（虚拟账号），让统计数字自然增长。

幂等：基于日期生成唯一用户名（community_guest_YYYYMMDD），每天只会创建一次。
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone

from django.core.management.base import BaseCommand
from django.utils.crypto import get_random_string

from apps.accounts.models import User


class Command(BaseCommand):
    help = "每日自动创建一名社区虚拟成员 +1，使社区成员数稳定增长"

    def handle(self, *args, **options):
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        username = f"community_guest_{today}"
        if User.objects.filter(username=username).exists():
            self.stdout.write(self.style.WARNING(f"今日 ({today}) 成员已存在，跳过"))
            return
        # 随机显示名
        nicknames = ["晨光", "云雀", "南风", "星河", "远帆", "青藤", "灯塔", "海客", "归雁", "鹤归", "玉壶", "拾光"]
        suffix = get_random_string(3, allowed_chars="0123456789")
        display_name = f"{nicknames[datetime.now(timezone.utc).day % len(nicknames)]}·{suffix}"
        # 用随机密码创建
        user = User.objects.create(
            username=username,
            display_name=display_name,
            password=get_random_string(32),
            email="",
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        # 赠送 0 积分（不参与正式活动），仅占位
        try:
            from apps.points.services import award_registration

            award_registration(user)
        except Exception:
            pass
        self.stdout.write(self.style.SUCCESS(f"已创建今日成员：{username} ({display_name})"))
