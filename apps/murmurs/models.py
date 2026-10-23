"""Lightweight, plain-text community posts. Existing forum tables stay unchanged."""
from django.db import models
from django.utils import timezone


def timestamp():
    return timezone.now().isoformat()


class Murmur(models.Model):
    author_username = models.CharField(max_length=150)
    content = models.TextField(blank=True, default="")
    client_key = models.CharField(max_length=64)
    is_deleted = models.BooleanField(default=False)
    is_pinned = models.BooleanField(default=False)
    deleted_at = models.TextField(blank=True, default="")
    deleted_by = models.CharField(max_length=150, blank=True, default="")
    deletion_reason = models.TextField(blank=True, default="")
    appeal_deadline = models.TextField(blank=True, default="")
    restored_at = models.TextField(blank=True, default="")
    created_at = models.TextField(default=timestamp)
    images = models.ManyToManyField("forum.ForumImage", through="MurmurImage")

    class Meta:
        db_table = "community_murmurs"
        ordering = ["-id"]
        constraints = [models.UniqueConstraint(fields=["author_username", "client_key"], name="uq_murmur_client_key")]
        indexes = [
            models.Index(fields=["is_deleted", "-is_pinned", "-id"], name="murmur_pinned_feed_idx"),
            models.Index(fields=["is_deleted", "-id"], name="murmur_feed_idx"),
            models.Index(fields=["author_username", "is_deleted", "-id"], name="murmur_author_idx"),
        ]


class MurmurReadState(models.Model):
    murmur = models.ForeignKey(Murmur, on_delete=models.CASCADE, related_name="read_states")
    username = models.CharField(max_length=150)
    last_comment_id = models.PositiveBigIntegerField(default=0)

    class Meta:
        db_table = "murmur_read_states"
        constraints = [models.UniqueConstraint(fields=["murmur", "username"], name="uq_murmur_read_state")]


class MurmurImage(models.Model):
    murmur = models.ForeignKey(Murmur, related_name="attachments", on_delete=models.CASCADE)
    image = models.ForeignKey("forum.ForumImage", on_delete=models.PROTECT)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "community_murmur_images"
        ordering = ["position", "id"]
        constraints = [models.UniqueConstraint(fields=["murmur", "image"], name="uq_murmur_image")]


class MurmurLike(models.Model):
    murmur = models.ForeignKey(Murmur, related_name="likes", on_delete=models.CASCADE)
    username = models.CharField(max_length=150)
    created_at = models.TextField(default=timestamp)

    class Meta:
        db_table = "community_murmur_likes"
        constraints = [models.UniqueConstraint(fields=["murmur", "username"], name="uq_murmur_like")]


class MurmurComment(models.Model):
    murmur = models.ForeignKey(Murmur, related_name="comments", on_delete=models.CASCADE)
    reply_to = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="replies")
    author_username = models.CharField(max_length=150)
    content = models.TextField()
    client_key = models.CharField(max_length=64)
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.TextField(blank=True, default="")
    deleted_by = models.CharField(max_length=150, blank=True, default="")
    deletion_reason = models.TextField(blank=True, default="")
    appeal_deadline = models.TextField(blank=True, default="")
    restored_at = models.TextField(blank=True, default="")
    created_at = models.TextField(default=timestamp)
    images = models.ManyToManyField("forum.ForumImage", through="MurmurCommentImage")

    class Meta:
        db_table = "community_murmur_comments"
        ordering = ["id"]
        constraints = [models.UniqueConstraint(fields=["author_username", "client_key"], name="uq_murmur_comment_key")]
        indexes = [models.Index(fields=["murmur", "is_deleted", "id"], name="murmur_comment_idx")]


class MurmurCommentImage(models.Model):
    comment = models.ForeignKey(MurmurComment, related_name="attachments", on_delete=models.CASCADE)
    image = models.ForeignKey("forum.ForumImage", on_delete=models.PROTECT)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "community_murmur_comment_images"
        ordering = ["position", "id"]
        constraints = [models.UniqueConstraint(fields=["comment", "image"], name="uq_murmur_comment_image")]


class MurmurBlock(models.Model):
    username = models.CharField(max_length=150)
    blocked_username = models.CharField(max_length=150)
    created_at = models.TextField(default=timestamp)

    class Meta:
        db_table = "community_murmur_blocks"
        constraints = [models.UniqueConstraint(fields=["username", "blocked_username"], name="uq_murmur_block")]


class MurmurAppeal(models.Model):
    murmur = models.ForeignKey(Murmur, related_name="appeals", on_delete=models.CASCADE)
    comment = models.ForeignKey(MurmurComment, null=True, blank=True, related_name="appeals", on_delete=models.CASCADE)
    target_key = models.CharField(max_length=64, unique=True)
    appellant_username = models.CharField(max_length=150)
    reason = models.TextField()
    status = models.CharField(max_length=16, default="pending")
    reviewer_username = models.CharField(max_length=150, blank=True, default="")
    review_note = models.TextField(blank=True, default="")
    created_at = models.TextField(default=timestamp)
    reviewed_at = models.TextField(blank=True, default="")

    class Meta:
        db_table = "community_murmur_appeals"
        ordering = ["-id"]
        indexes = [models.Index(fields=["status", "-id"], name="murmur_appeal_idx")]


class MurmurReport(models.Model):
    murmur = models.ForeignKey(Murmur, on_delete=models.CASCADE)
    comment = models.ForeignKey(MurmurComment, null=True, blank=True, on_delete=models.CASCADE)
    target_key = models.CharField(max_length=64)
    reporter_username = models.CharField(max_length=150)
    reason = models.CharField(max_length=32)
    details = models.TextField(blank=True, default="")
    status = models.CharField(max_length=16, default="pending")
    reviewer_username = models.CharField(max_length=150, blank=True, default="")
    review_note = models.TextField(blank=True, default="")
    created_at = models.TextField(default=timestamp)
    reviewed_at = models.TextField(blank=True, default="")

    class Meta:
        db_table = "community_murmur_reports"
        constraints = [models.UniqueConstraint(fields=["target_key", "reporter_username"], name="uq_murmur_report")]
        indexes = [models.Index(fields=["status", "-id"], name="murmur_report_idx")]
