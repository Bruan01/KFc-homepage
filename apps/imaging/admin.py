from django.contrib import admin

from .models import ImageGenerationJob


@admin.register(ImageGenerationJob)
class ImageGenerationJobAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "status", "points_cost", "created_at", "completed_at")
    list_filter = ("status", "output_format", "quality")
    search_fields = ("id", "user__username", "prompt")
    readonly_fields = ("id", "created_at", "updated_at", "started_at", "completed_at", "image_sha256")
