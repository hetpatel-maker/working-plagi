# Generated manually
from django.db import migrations, models

class Migration(migrations.Migration):

    dependencies = [
        ('content_integrity', '0002_rename_ci_course_status_idx_content_int_course__b4101d_idx_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='contentcheck',
            name='scan_id',
            field=models.CharField(blank=True, db_index=True, default='', max_length=128),
        ),
    ]
