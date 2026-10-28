from django.db import models


class Announcement(models.Model):
    """站点群公告：同一时间最多一条生效，历史保留便于追溯。"""

    content = models.TextField()
    # 旧版单图字段，保留给历史数据与旧客户端；多图以 AnnouncementImage 为准。
    image = models.CharField(max_length=300, blank=True, default="")
    popup_days = models.PositiveIntegerField(default=3)
    valid_days = models.PositiveIntegerField(default=7)
    expires_at = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=False, db_index=True)
    created_by = models.CharField(max_length=150, blank=True, default="")
    created_at = models.TextField(blank=True, default="")
    updated_at = models.TextField(blank=True, default="")

    class Meta:
        db_table = "announcements"
        ordering = ["-id"]


class AnnouncementImage(models.Model):
    """公告配图，按 position 顺序在弹窗中逐行展示。"""

    announcement = models.ForeignKey(
        Announcement, related_name="images", on_delete=models.CASCADE,
    )
    image = models.CharField(max_length=300)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "announcement_images"
        ordering = ["position", "id"]
