from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("publishing", "0001_initial")]
    operations = [
        migrations.RunSQL(
            sql="""
            CREATE INDEX IF NOT EXISTS idx_publish_requests_product ON publish_requests(product_id);
            CREATE INDEX IF NOT EXISTS idx_publish_requests_status ON publish_requests(status, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_publish_request_votes_request ON publish_request_votes(request_id);
            CREATE INDEX IF NOT EXISTS idx_product_delete_requests_status ON product_delete_requests(status, created_at DESC);
            """,
            reverse_sql="""
            DROP INDEX IF EXISTS idx_publish_requests_product;
            DROP INDEX IF EXISTS idx_publish_requests_status;
            DROP INDEX IF EXISTS idx_publish_request_votes_request;
            DROP INDEX IF EXISTS idx_product_delete_requests_status;
            """,
        )
    ]
