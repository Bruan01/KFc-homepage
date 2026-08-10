from django.db import migrations


class Migration(migrations.Migration):
    """Drop the retired market tables without keeping the market app installed."""

    initial = True

    dependencies = []

    operations = [
        migrations.RunSQL(
            sql=[
                "DROP TABLE IF EXISTS market_marketadminaudit",
                "DROP TABLE IF EXISTS market_marketbotdailyusage",
                "DROP TABLE IF EXISTS market_marketdailyusage",
                "DROP TABLE IF EXISTS market_marketorder",
                "DROP TABLE IF EXISTS market_marketposition",
                "DROP TABLE IF EXISTS market_marketquote",
                "DROP TABLE IF EXISTS market_marketbotinventory",
                "DROP TABLE IF EXISTS market_markettreasuryledger",
                "DROP TABLE IF EXISTS market_marketasset",
                "DROP TABLE IF EXISTS market_marketround",
                "DELETE FROM django_migrations WHERE app = 'market'",
            ],
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
