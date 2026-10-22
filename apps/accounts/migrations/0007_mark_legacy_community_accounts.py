import re

from django.db import migrations


def mark_legacy_accounts(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    AdminAccount = apps.get_model("accounts", "AdminAccount")
    alias = schema_editor.connection.alias
    rows = User.objects.using(alias).filter(username__startswith="community_guest_", email="", email_verified_at__isnull=True)
    admin_names = set(AdminAccount.objects.using(alias).values_list("username", flat=True))
    ids = [user.pk for user in rows.iterator() if re.fullmatch(r"community_guest_[0-9]{8}", user.username) and user.username not in admin_names]
    User.objects.using(alias).filter(pk__in=ids).update(is_system_generated=True)


class Migration(migrations.Migration):
    dependencies = [("accounts", "0006_user_is_system_generated_userfollow_is_managed_and_more")]
    operations = [migrations.RunPython(mark_legacy_accounts, migrations.RunPython.noop)]
