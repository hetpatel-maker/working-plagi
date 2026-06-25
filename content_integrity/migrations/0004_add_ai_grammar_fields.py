# Generated manually
from django.db import migrations, models

class Migration(migrations.Migration):

    dependencies = [
        ('content_integrity', '0003_contentcheck_scan_id'),
    ]

    operations = [
        migrations.AddField(
            model_name='contentcheck',
            name='ai_score',
            field=models.FloatField(blank=True, help_text='AI Generation percentage likelihood, 0-100', null=True),
        ),
        migrations.AddField(
            model_name='contentcheck',
            name='grammar_score',
            field=models.FloatField(blank=True, help_text='Overall writing feedback score, 0-100', null=True),
        ),
        migrations.AddField(
            model_name='contentcheck',
            name='readability_text',
            field=models.CharField(blank=True, default='', help_text="e.g. '5th Grader'", max_length=64),
        ),
        migrations.AddField(
            model_name='contentcheck',
            name='flag_reasons',
            field=models.JSONField(blank=True, default=list, help_text="List of reasons this was flagged (e.g., ['plagiarism', 'ai'])"),
        ),
    ]
