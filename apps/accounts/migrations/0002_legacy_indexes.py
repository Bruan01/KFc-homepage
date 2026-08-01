from django.db import migrations


INDEX_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_email_codes_lookup ON email_verification_codes(email, purpose, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_email_verification_codes_email_purpose_expires ON email_verification_codes(email, purpose, expires_at)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_admin_accounts_email_unique ON admin_accounts(email) WHERE email <> ''",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_verified_email_unique ON users(lower(email)) WHERE email <> '' AND email_verified_at IS NOT NULL",
]


class Migration(migrations.Migration):
    dependencies = [("accounts", "0001_initial")]
    operations = [
        migrations.RunSQL(
            sql=";\n".join(INDEX_SQL) + ";",
            reverse_sql=";\n".join(
                f"DROP INDEX IF EXISTS {name}"
                for name in [
                    "idx_email_codes_lookup",
                    "idx_email_verification_codes_email_purpose_expires",
                    "idx_admin_accounts_email_unique",
                    "idx_users_verified_email_unique",
                ]
            ) + ";",
        )
    ]
