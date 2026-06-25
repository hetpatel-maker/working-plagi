from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="ContentCheck",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("course_id", models.CharField(db_index=True, max_length=255)),
                ("usage_key", models.CharField(db_index=True, max_length=255, unique=True)),
                ("block_type", models.CharField(db_index=True, max_length=64)),
                ("content_hash", models.CharField(blank=True, default="", max_length=64)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("clean", "Clean"),
                            ("flagged", "Flagged"),
                            ("error", "Error"),
                            ("skipped", "Skipped (no checkable text)"),
                        ],
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("score", models.FloatField(blank=True, null=True)),
                ("provider", models.CharField(blank=True, default="", max_length=64)),
                ("matched_sources", models.JSONField(blank=True, default=list)),
                ("error_message", models.TextField(blank=True, default="")),
                ("last_checked_at", models.DateTimeField(blank=True, null=True)),
                ("content_changed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.CreateModel(
            name="CourseReport",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("course_id", models.CharField(db_index=True, max_length=255, unique=True)),
                ("generated_at", models.DateTimeField(auto_now=True)),
                ("total_components", models.IntegerField(default=0)),
                ("checked_components", models.IntegerField(default=0)),
                ("flagged_components", models.IntegerField(default=0)),
                ("average_score", models.FloatField(blank=True, null=True)),
                ("is_complete", models.BooleanField(default=False)),
                ("summary", models.JSONField(blank=True, default=dict)),
            ],
        ),
        migrations.AddIndex(
            model_name="contentcheck",
            index=models.Index(fields=["course_id", "status"], name="ci_course_status_idx"),
        ),
    ]
