# Generated manually for the imaging provider pool.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("imaging", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="ImagingProvider",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120, unique=True)),
                ("enabled", models.BooleanField(default=True)),
                ("base_url", models.CharField(max_length=500)),
                ("api_key", models.TextField(blank=True, default="")),
                ("model", models.CharField(max_length=120)),
                ("timeout_seconds", models.PositiveIntegerField(default=360)),
                ("weight", models.PositiveIntegerField(default=1)),
                ("priority", models.IntegerField(default=100)),
                ("schedule_current_weight", models.IntegerField(default=0)),
                ("consecutive_failures", models.PositiveIntegerField(default=0)),
                ("circuit_open_until", models.DateTimeField(blank=True, null=True)),
                ("last_success_at", models.DateTimeField(blank=True, null=True)),
                ("last_failure_at", models.DateTimeField(blank=True, null=True)),
                ("last_error", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "indexes": [
                    models.Index(fields=["enabled", "circuit_open_until"], name="imaging_provider_avail_idx"),
                    models.Index(fields=["priority", "id"], name="imaging_provider_order_idx"),
                ],
            },
        ),
        migrations.AddField(
            model_name="imagegenerationjob",
            name="provider",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="generation_jobs", to="imaging.imagingprovider"),
        ),
        migrations.CreateModel(
            name="ImagingProviderAttempt",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("provider_name", models.CharField(blank=True, default="", max_length=120)),
                ("attempt_number", models.PositiveIntegerField()),
                ("status", models.CharField(choices=[("succeeded", "成功"), ("failed", "失败")], max_length=16)),
                ("error", models.TextField(blank=True, default="")),
                ("started_at", models.DateTimeField()),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("duration_ms", models.PositiveIntegerField(default=0)),
                ("job", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="provider_attempts", to="imaging.imagegenerationjob")),
                ("provider", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="attempts", to="imaging.imagingprovider")),
            ],
            options={
                "ordering": ["attempt_number"],
                "constraints": [
                    models.UniqueConstraint(fields=("job", "attempt_number"), name="uq_imaging_job_attempt_number"),
                ],
            },
        ),
    ]
