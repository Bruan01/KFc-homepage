from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("downloads", "0001_initial")]
    operations = [
        migrations.RunSQL(
            sql="""
            CREATE INDEX IF NOT EXISTS idx_downloads_product_downloaded ON downloads(product_id, downloaded_at DESC);
            CREATE INDEX IF NOT EXISTS idx_download_requests_user ON download_requests(user_id, status);
            CREATE INDEX IF NOT EXISTS idx_download_entitlements_user_product ON download_entitlements(user_id, product_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_download_requests_status ON download_requests(status, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_downloads_user_product ON downloads(user_id, product_id);
            CREATE INDEX IF NOT EXISTS idx_download_requests_product_user_status ON download_requests(product_id, user_id, status);
            """,
            reverse_sql="""
            DROP INDEX IF EXISTS idx_downloads_product_downloaded;
            DROP INDEX IF EXISTS idx_download_requests_user;
            DROP INDEX IF EXISTS idx_download_entitlements_user_product;
            DROP INDEX IF EXISTS idx_download_requests_status;
            DROP INDEX IF EXISTS idx_downloads_user_product;
            DROP INDEX IF EXISTS idx_download_requests_product_user_status;
            """,
        )
    ]
