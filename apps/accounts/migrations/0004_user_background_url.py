from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0003_user_avatar_url_user_bio_user_display_name"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="background_url",
            field=models.CharField(blank=True, default="", max_length=500),
        ),
    ]
