from django.db import migrations, models

class Migration(migrations.Migration):

    dependencies = [
        ('content_integrity', '0004_add_ai_grammar_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='contentcheck',
            name='report_pdf',
            field=models.FileField(blank=True, help_text='The downloaded PDF report from Copyleaks', null=True, upload_to='copyleaks_reports/'),
        ),
    ]
