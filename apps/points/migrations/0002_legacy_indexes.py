from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("points", "0001_initial")]
    operations = [
        migrations.RunSQL(
            sql="""
            CREATE INDEX IF NOT EXISTS idx_point_ledger_user_time ON point_ledger(user_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_daily_activity_user_date ON user_daily_activity(user_id, activity_date DESC);
            """,
            reverse_sql="""
            DROP INDEX IF EXISTS idx_point_ledger_user_time;
            DROP INDEX IF EXISTS idx_daily_activity_user_date;
            """,
        )
    ]
