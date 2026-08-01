"""Django ORM models backed by the legacy publishing tables."""
from django.db import models


class PublishRequest(models.Model):
    id = models.AutoField(primary_key=True)
    product = models.ForeignKey("catalog.Product", db_column="product_id", on_delete=models.DO_NOTHING, related_name="publish_requests")
    requested_by = models.TextField()
    requester_level = models.IntegerField()
    reviewer_scope = models.TextField()
    reviewer_pool_count = models.IntegerField()
    reviewer_pool_weight = models.IntegerField(default=0)
    approve_threshold_weight = models.IntegerField(default=0)
    status = models.TextField(default="pending")
    created_at = models.TextField()
    expires_at = models.TextField(null=True, blank=True)
    decided_at = models.TextField(null=True, blank=True)
    decided_note = models.TextField(blank=True, default="")

    class Meta:
        db_table = "publish_requests"
        managed = True


class PublishRequestVote(models.Model):
    id = models.AutoField(primary_key=True)
    request = models.ForeignKey(PublishRequest, db_column="request_id", on_delete=models.DO_NOTHING, related_name="votes")
    reviewer_username = models.TextField()
    reviewer_level = models.IntegerField()
    vote = models.TextField()
    note = models.TextField(blank=True, default="")
    created_at = models.TextField()

    class Meta:
        db_table = "publish_request_votes"
        managed = True
        constraints = [
            models.UniqueConstraint(fields=["request", "reviewer_username"], name="uq_publish_vote_request_reviewer"),
        ]


class ProductDeleteRequest(models.Model):
    id = models.AutoField(primary_key=True)
    product = models.ForeignKey("catalog.Product", db_column="product_id", on_delete=models.DO_NOTHING, related_name="delete_requests")
    product_name = models.TextField(blank=True, default="")
    product_slug = models.TextField(blank=True, default="")
    requested_by = models.TextField()
    requester_level = models.IntegerField()
    owner_username = models.TextField()
    reason = models.TextField(blank=True, default="")
    status = models.TextField(default="pending")
    created_at = models.TextField()
    decided_at = models.TextField(null=True, blank=True)
    decided_by = models.TextField(null=True, blank=True)
    decision_note = models.TextField(blank=True, default="")

    class Meta:
        db_table = "product_delete_requests"
        managed = True
