# pyright: reportMissingImports=false
from django.contrib import admin

from .models import ForumCategory, ForumLike, ForumModerationAction, ForumReply, ForumReport, ForumTopic


@admin.register(ForumCategory)
class ForumCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "sort_order", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name", "slug")
    ordering = ("sort_order", "id")
    filter_horizontal = ("moderators",)


@admin.register(ForumTopic)
class ForumTopicAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "category",
        "author_username",
        "status",
        "is_pinned",
        "is_featured",
        "views",
        "created_at",
    )
    list_filter = ("status", "is_pinned", "is_featured", "category")
    search_fields = ("title", "content", "author_username", "tags")
    list_select_related = ("category",)


@admin.register(ForumReply)
class ForumReplyAdmin(admin.ModelAdmin):
    list_display = ("topic", "author_username", "is_deleted", "created_at")
    list_filter = ("is_deleted",)
    search_fields = ("content", "author_username", "topic__title")
    list_select_related = ("topic",)


@admin.register(ForumLike)
class ForumLikeAdmin(admin.ModelAdmin):
    list_display = ("topic", "username", "created_at")
    search_fields = ("username", "topic__title")
    list_select_related = ("topic",)


@admin.register(ForumReport)
class ForumReportAdmin(admin.ModelAdmin):
    list_display = ("target_type", "target_id", "reporter_username", "reason", "status", "created_at")
    list_filter = ("status", "target_type", "reason")
    search_fields = ("reporter_username", "details", "reviewer_username")


@admin.register(ForumModerationAction)
class ForumModerationActionAdmin(admin.ModelAdmin):
    list_display = ("target_type", "target_id", "action", "admin_username", "created_at")
    list_filter = ("target_type", "action")
    search_fields = ("admin_username", "note")
