# pyright: reportMissingImports=false
"""Django ORM models backed by the legacy account tables."""
from __future__ import annotations

from django.contrib.auth.base_user import AbstractBaseUser
from django.db import models

from .managers import UserManager


class User(AbstractBaseUser):
    id = models.AutoField(primary_key=True)
    username = models.CharField(max_length=150, unique=True)
    email = models.TextField(blank=True, default="")
    email_verified_at = models.TextField(null=True, blank=True)
    created_at = models.TextField()
    display_name = models.CharField(max_length=100, blank=True, default="")
    avatar_url = models.CharField(max_length=500, blank=True, default="")
    bio = models.TextField(blank=True, default="")
    last_login = None

    objects = UserManager()

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        db_table = "users"
        managed = True

    def __str__(self):
        return self.username

    @property
    def admin_account(self):
        return AdminAccount.objects.filter(username=self.username).first()

    @property
    def is_active(self):
        return True

    @property
    def is_staff(self):
        return self.admin_account is not None

    @property
    def is_superuser(self):
        admin = self.admin_account
        return bool(admin and admin.is_super)

    def has_perm(self, perm, obj=None):
        return self.is_superuser

    def has_module_perms(self, app_label):
        return self.is_staff


class AdminAccount(models.Model):
    id = models.AutoField(primary_key=True)
    username = models.CharField(max_length=150, unique=True)
    password_hash = models.TextField()
    email = models.TextField(blank=True, default="")
    created_at = models.TextField()
    created_by = models.TextField(blank=True, default="")
    is_super = models.IntegerField(default=0)
    admin_level = models.IntegerField(default=1)

    class Meta:
        db_table = "admin_accounts"
        managed = True

    def __str__(self):
        return self.username


class LegacySession(models.Model):
    id = models.AutoField(primary_key=True)
    token = models.TextField(unique=True)
    role = models.TextField()
    user = models.ForeignKey(
        User,
        db_column="user_id",
        null=True,
        blank=True,
        on_delete=models.DO_NOTHING,
        db_constraint=False,
        related_name="legacy_sessions",
    )
    username = models.TextField()
    admin_level = models.IntegerField(null=True, blank=True)
    is_super = models.IntegerField(default=0)
    created_ip = models.TextField(null=True, blank=True)
    last_seen_ip = models.TextField(null=True, blank=True)
    exp = models.FloatField()
    created_at = models.TextField()
    updated_at = models.TextField()

    class Meta:
        db_table = "sessions"
        managed = True


class EmailVerificationCode(models.Model):
    id = models.AutoField(primary_key=True)
    email = models.TextField()
    purpose = models.TextField()
    code_hash = models.TextField()
    request_ip = models.TextField(blank=True, default="")
    attempt_count = models.IntegerField(default=0)
    created_at = models.TextField()
    expires_at = models.TextField()
    used_at = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "email_verification_codes"
        managed = True


class AdminRegisterToken(models.Model):
    id = models.AutoField(primary_key=True)
    token = models.TextField(unique=True)
    created_by = models.TextField()
    created_at = models.TextField()
    admin_level = models.IntegerField(default=1)
    used_by_admin = models.ForeignKey(
        AdminAccount,
        db_column="used_by_admin_id",
        null=True,
        blank=True,
        on_delete=models.DO_NOTHING,
        related_name="used_register_tokens",
    )
    used_at = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "admin_register_tokens"
        managed = True


class Subscriber(models.Model):
    id = models.AutoField(primary_key=True)
    email = models.TextField()
    channel = models.TextField(default="email")
    created_at = models.TextField()

    class Meta:
        db_table = "subscribers"
        managed = True
        constraints = [
            models.UniqueConstraint(fields=["email", "channel"], name="uq_subscribers_email_channel"),
        ]


class UserSubscription(models.Model):
    id = models.AutoField(primary_key=True)
    user = models.OneToOneField(
        User,
        db_column="user_id",
        on_delete=models.DO_NOTHING,
        related_name="subscription",
    )
    created_at = models.TextField()

    class Meta:
        db_table = "user_subscriptions"
        managed = True
