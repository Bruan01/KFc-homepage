from django.conf import settings
from django.db import models
from django.utils import timezone


class PrivateMessage(models.Model):
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="sent_private_messages")
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="received_private_messages")
    content = models.TextField()
    client_key = models.CharField(max_length=64)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "private_messages"
        constraints = [models.UniqueConstraint(fields=["sender", "client_key"], name="uq_private_message_key"),
                       models.CheckConstraint(condition=~models.Q(sender=models.F("recipient")), name="private_message_not_self")]
        indexes = [models.Index(fields=["sender", "recipient", "-id"], name="private_message_pair_idx"),
                   models.Index(fields=["recipient", "is_read", "-id"], name="private_message_unread_idx")]
