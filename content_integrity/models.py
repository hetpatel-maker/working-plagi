"""
Two tables, matching the design we settled on:

ContentCheck  - one row per XBlock (course component). Holds the content
                hash we last checked, so we can skip re-checking unchanged
                content on every publish.
CourseReport  - one row per course, a rolled-up summary built by aggregating
                ContentCheck rows. This is what the course team actually
                looks at.
"""
from django.db import models


class ContentCheckStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    CLEAN = "clean", "Clean"
    FLAGGED = "flagged", "Flagged"
    ERROR = "error", "Error"
    SKIPPED = "skipped", "Skipped (no checkable text)"


class ContentCheck(models.Model):
    course_id = models.CharField(max_length=255, db_index=True)
    usage_key = models.CharField(max_length=255, unique=True, db_index=True)
    block_type = models.CharField(max_length=64, db_index=True)

    # sha256 hex digest of the extracted plain text we last ran a check on.
    # Empty string means "never successfully checked".
    content_hash = models.CharField(max_length=64, blank=True, default="")

    status = models.CharField(
        max_length=16,
        choices=ContentCheckStatus.choices,
        default=ContentCheckStatus.PENDING,
    )
    score = models.FloatField(
        null=True, blank=True,
        help_text="Similarity / match percentage returned by the provider, 0-100",
    )
    provider = models.CharField(max_length=64, blank=True, default="")
    scan_id = models.CharField(max_length=128, blank=True, default="", db_index=True)
    matched_sources = models.JSONField(default=list, blank=True)
    
    # New analysis fields
    ai_score = models.FloatField(null=True, blank=True, help_text="AI Generation percentage likelihood, 0-100")
    grammar_score = models.FloatField(null=True, blank=True, help_text="Overall writing feedback score, 0-100")
    readability_text = models.CharField(max_length=64, blank=True, default="", help_text="e.g. '5th Grader'")
    flag_reasons = models.JSONField(default=list, blank=True, help_text="List of reasons this was flagged (e.g., ['plagiarism', 'ai'])")
    
    error_message = models.TextField(blank=True, default="")

    last_checked_at = models.DateTimeField(null=True, blank=True)
    content_changed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["course_id", "status"]),
        ]

    def __str__(self):
        return f"{self.usage_key} [{self.status}]"


class CourseReport(models.Model):
    course_id = models.CharField(max_length=255, unique=True, db_index=True)
    generated_at = models.DateTimeField(auto_now=True)

    total_components = models.IntegerField(default=0)
    checked_components = models.IntegerField(default=0)
    flagged_components = models.IntegerField(default=0)
    average_score = models.FloatField(null=True, blank=True)
    is_complete = models.BooleanField(
        default=False,
        help_text="False while some components are still pending/queued.",
    )

    # Snapshot of the worst offenders, so the report view doesn't have to
    # join back to ContentCheck just to render the headline list.
    summary = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return f"Report for {self.course_id} ({self.flagged_components} flagged)"
