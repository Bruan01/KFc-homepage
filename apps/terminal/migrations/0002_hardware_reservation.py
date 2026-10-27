import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("terminal", "0001_initial_terminal_device"),
    ]

    operations = [
        migrations.CreateModel(
            name="HardwareReservation",
            fields=[
                ("id", models.AutoField(primary_key=True, serialize=False)),
                ("queue_no", models.PositiveIntegerField(unique=True)),
                ("code", models.CharField(max_length=16, unique=True)),
                ("status", models.CharField(choices=[("reserved", "已预约"), ("cancelled", "已取消"), ("granted", "已发放")], default="reserved", max_length=12)),
                ("remark", models.CharField(blank=True, default="", max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("cancelled_at", models.DateTimeField(blank=True, null=True)),
                ("granted_at", models.DateTimeField(blank=True, null=True)),
                ("user", models.OneToOneField(db_column="user_id", on_delete=django.db.models.deletion.CASCADE, related_name="hardware_reservation", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "db_table": "terminal_hardware_reservations",
                "ordering": ["queue_no"],
            },
        ),
    ]
