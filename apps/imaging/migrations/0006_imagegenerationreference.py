from django.db import migrations, models
import apps.imaging.models


class Migration(migrations.Migration):
    dependencies = [("imaging", "0005_imagingtemplate_modes")]

    operations = [
        migrations.CreateModel(
            name="ImageGenerationReference",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("image", models.FileField(upload_to=apps.imaging.models.reference_upload_to)),
                ("original_name", models.CharField(max_length=255)),
                ("content_type", models.CharField(max_length=100)),
                ("file_size", models.PositiveIntegerField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("job", models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="references", to="imaging.imagegenerationjob")),
            ],
        ),
    ]
