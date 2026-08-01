from __future__ import annotations

import time

from django.contrib.sessions.models import Session
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounts.models import LegacySession


class Command(BaseCommand):
    help = "Remove expired Django and legacy sessions."

    def handle(self, *args, **options):
        django_count, _ = Session.objects.filter(expire_date__lt=timezone.now()).delete()
        legacy_count, _ = LegacySession.objects.filter(exp__lt=time.time()).delete()
        self.stdout.write(
            self.style.SUCCESS(
                f"Removed {django_count} Django sessions and {legacy_count} legacy sessions."
            )
        )
