from django.contrib import admin

from .models import ContentCheck, CourseReport


@admin.register(ContentCheck)
class ContentCheckAdmin(admin.ModelAdmin):
    list_display = ("usage_key", "course_id", "block_type", "status", "score", "last_checked_at")
    list_filter = ("status", "block_type")
    search_fields = ("usage_key", "course_id")
    readonly_fields = ("created_at", "updated_at")


@admin.register(CourseReport)
class CourseReportAdmin(admin.ModelAdmin):
    list_display = ("course_id", "total_components", "checked_components", "flagged_components", "average_score", "generated_at")
    search_fields = ("course_id",)
