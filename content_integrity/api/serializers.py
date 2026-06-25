from rest_framework import serializers

from ..models import ContentCheck, CourseReport


class ContentCheckSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContentCheck
        fields = [
            "usage_key", "block_type", "status", "score",
            "provider", "matched_sources", "last_checked_at",
        ]


class CourseReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = CourseReport
        fields = [
            "course_id", "generated_at", "total_components", "checked_components",
            "flagged_components", "average_score", "is_complete", "summary",
        ]
