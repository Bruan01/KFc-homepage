from django.db import migrations


def reclassify(apps, schema_editor):
    Notification = apps.get_model("notifications", "Notification")
    Notification.objects.filter(
        type="system",
        body="你有一条新私信",
        title__endswith="给你发来私信",
    ).update(type="message")


class Migration(migrations.Migration):

    dependencies = [
        ("notifications", "0003_alter_notification_type"),
    ]

    operations = [
        migrations.RunPython(reclassify, migrations.RunPython.noop),
    ]
