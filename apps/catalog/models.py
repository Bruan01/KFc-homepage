"""Django ORM models backed by the legacy product tables."""
from django.db import models


class Product(models.Model):
    id = models.AutoField(primary_key=True)
    slug = models.TextField(unique=True)
    name = models.TextField()
    summary = models.TextField(blank=True, default="")
    description = models.TextField(blank=True, default="")
    category = models.TextField(blank=True, default="")
    platforms = models.TextField(default="[]")
    architectures = models.TextField(default="[]")
    tags = models.TextField(blank=True, default="")
    announcement = models.TextField(blank=True, default="")
    version = models.TextField(default="0.1.0")
    changelog = models.TextField(blank=True, default="")
    status = models.TextField(default="draft")
    created_by = models.TextField(blank=True, default="")
    file_name = models.TextField(null=True, blank=True)
    file_path = models.TextField(null=True, blank=True)
    file_size = models.IntegerField(null=True, blank=True)
    file_sha256 = models.TextField(null=True, blank=True)
    created_at = models.TextField()
    updated_at = models.TextField()
    published_at = models.TextField(null=True, blank=True)
    point_download_cost = models.IntegerField(null=True, blank=True)
    points_redemption_enabled = models.IntegerField(default=1)

    class Meta:
        db_table = "products"
        managed = True

    def __str__(self):
        return self.name


class ProductPackage(models.Model):
    id = models.AutoField(primary_key=True)
    product = models.ForeignKey(Product, db_column="product_id", on_delete=models.DO_NOTHING, related_name="packages")
    platform = models.TextField(null=True, blank=True)
    architecture = models.TextField(null=True, blank=True)
    file_name = models.TextField(null=True, blank=True)
    file_path = models.TextField(null=True, blank=True)
    file_size = models.IntegerField(null=True, blank=True)
    file_sha256 = models.TextField(null=True, blank=True)
    sort_order = models.IntegerField(default=0)
    created_at = models.TextField()
    updated_at = models.TextField()

    class Meta:
        db_table = "product_packages"
        managed = True


class ProductVersion(models.Model):
    id = models.AutoField(primary_key=True)
    product = models.ForeignKey(Product, db_column="product_id", on_delete=models.DO_NOTHING, related_name="versions")
    name = models.TextField()
    slug = models.TextField()
    category = models.TextField(blank=True, default="")
    platforms = models.TextField(default="[]")
    architectures = models.TextField(default="[]")
    tags = models.TextField(blank=True, default="")
    announcement = models.TextField(blank=True, default="")
    version = models.TextField()
    summary = models.TextField(blank=True, default="")
    description = models.TextField(blank=True, default="")
    changelog = models.TextField(blank=True, default="")
    status = models.TextField(default="draft")
    file_name = models.TextField(null=True, blank=True)
    file_path = models.TextField(null=True, blank=True)
    file_size = models.IntegerField(null=True, blank=True)
    file_sha256 = models.TextField(null=True, blank=True)
    published_at = models.TextField(null=True, blank=True)
    created_at = models.TextField()
    created_by = models.TextField(blank=True, default="")
    source = models.TextField(default="snapshot")

    class Meta:
        db_table = "product_versions"
        managed = True


class AdminUploadEvent(models.Model):
    id = models.AutoField(primary_key=True)
    admin_username = models.TextField()
    product = models.ForeignKey(Product, db_column="product_id", on_delete=models.DO_NOTHING, related_name="admin_upload_events")
    uploaded_at = models.TextField()
    file_size = models.IntegerField(default=0)

    class Meta:
        db_table = "admin_upload_events"
        managed = True
        constraints = [
            models.UniqueConstraint(fields=["admin_username", "product"], name="uq_admin_upload_admin_product"),
        ]


class SystemSetting(models.Model):
    setting_key = models.TextField(primary_key=True)
    setting_value = models.TextField(blank=True, default="")
    updated_at = models.TextField(blank=True, default="")
    updated_by = models.TextField(blank=True, default="")

    class Meta:
        db_table = "system_settings"
        managed = True
