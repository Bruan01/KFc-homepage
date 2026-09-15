from django.contrib import admin

from .models import ImageGenerationJob, ImagingTemplate


@admin.register(ImageGenerationJob)
class ImageGenerationJobAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "template_name", "status", "points_cost", "created_at", "completed_at")
    list_filter = ("status", "template_key", "output_format", "quality")
    search_fields = ("id", "user__username", "prompt", "original_prompt", "template_name")
    readonly_fields = ("id", "created_at", "updated_at", "started_at", "completed_at", "image_sha256")


@admin.register(ImagingTemplate)
class ImagingTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "key", "category", "enabled", "is_system", "sort_order", "version", "updated_at")
    list_filter = ("enabled", "is_system", "category")
    search_fields = ("name", "key", "description", "prompt_template")
