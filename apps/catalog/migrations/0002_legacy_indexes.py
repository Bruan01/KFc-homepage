from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("catalog", "0001_initial")]
    operations = [
        migrations.RunSQL(
            sql="""
            CREATE INDEX IF NOT EXISTS idx_products_status_updated ON products(status, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_products_status_published ON products(status, published_at DESC);
            CREATE INDEX IF NOT EXISTS idx_product_packages_product ON product_packages(product_id, sort_order);
            CREATE INDEX IF NOT EXISTS idx_product_versions_product ON product_versions(product_id, version DESC);
            CREATE INDEX IF NOT EXISTS idx_uploads_product ON admin_upload_events(product_id);
            """,
            reverse_sql="""
            DROP INDEX IF EXISTS idx_products_status_updated;
            DROP INDEX IF EXISTS idx_products_status_published;
            DROP INDEX IF EXISTS idx_product_packages_product;
            DROP INDEX IF EXISTS idx_product_versions_product;
            DROP INDEX IF EXISTS idx_uploads_product;
            """,
        )
    ]
