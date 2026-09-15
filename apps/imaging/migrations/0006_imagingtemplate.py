from django.db import migrations, models


def seed_templates(apps, schema_editor):
    ImagingTemplate = apps.get_model("imaging", "ImagingTemplate")
    from apps.imaging.prompt_templates import TEMPLATES

    for index, template in enumerate(TEMPLATES, start=1):
        ImagingTemplate.objects.create(
            key=template.key,
            name=template.name,
            category=template.category,
            description=template.description,
            accent=template.accent,
            cover_url=template.cover_url,
            fields=[field.payload() for field in template.fields],
            prompt_template=f"__builtin__:{template.key}",
            enabled=True,
            sort_order=index * 10,
            is_system=True,
            version=1,
        )


class Migration(migrations.Migration):
    dependencies = [("imaging", "0005_imagegenerationjob_template_metadata")]

    operations = [
        migrations.CreateModel(
            name="ImagingTemplate",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("key", models.SlugField(max_length=80, unique=True)),
                ("name", models.CharField(max_length=120)),
                ("category", models.CharField(blank=True, default="", max_length=80)),
                ("description", models.CharField(blank=True, default="", max_length=500)),
                ("accent", models.CharField(blank=True, default="", max_length=40)),
                ("cover_url", models.CharField(blank=True, default="", max_length=500)),
                ("fields", models.JSONField(default=list)),
                ("prompt_template", models.TextField()),
                ("enabled", models.BooleanField(default=True)),
                ("sort_order", models.IntegerField(default=100)),
                ("is_system", models.BooleanField(default=False)),
                ("version", models.PositiveIntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["sort_order", "id"]},
        ),
        migrations.AddIndex(
            model_name="imagingtemplate",
            index=models.Index(fields=["enabled", "sort_order", "id"], name="imaging_template_order_idx"),
        ),
        migrations.RunPython(seed_templates, migrations.RunPython.noop),
    ]
