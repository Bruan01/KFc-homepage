# Generated manually for the template-library release.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("imaging", "0002_imaging_provider_pool"),
    ]

    operations = [
        migrations.AddField(
            model_name="imagegenerationjob",
            name="original_prompt",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="imagegenerationjob",
            name="template_key",
            field=models.CharField(blank=True, default="", max_length=80),
        ),
        migrations.AddField(
            model_name="imagegenerationjob",
            name="template_name",
            field=models.CharField(blank=True, default="", max_length=120),
        ),
    ]
