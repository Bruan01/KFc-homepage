from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import User


@receiver(post_save, sender=User, dispatch_uid="accounts.initialize_official_follow")
def default_official_follow(sender, instance, created, raw=False, using="default", **kwargs):
    if created and not raw:
        from .official import initialize_official_follow
        initialize_official_follow(instance, using=using)
