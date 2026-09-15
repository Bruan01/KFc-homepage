from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("imaging", "0004_imagingtemplate")]

    operations = [
        migrations.AddField(
            model_name="imagingtemplate",
            name="template_type",
            field=models.CharField(choices=[("prompt", "Prompt 模板"), ("skill", "Skill 模板")], default="prompt", max_length=20),
        ),
        migrations.AddField(
            model_name="imagingtemplate",
            name="skill_key",
            field=models.CharField(blank=True, default="", max_length=120),
        ),
        migrations.AddField(
            model_name="imagingtemplate",
            name="reference_required",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="imagingtemplate",
            name="reference_max_count",
            field=models.PositiveIntegerField(default=0),
        ),
    ]
