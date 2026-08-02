from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("market", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="marketposition",
            name="invested_fee_points",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="marketorder",
            name="profit_points",
            field=models.IntegerField(default=0),
        ),
    ]
