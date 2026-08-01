from django.contrib.auth.base_user import BaseUserManager


class UserManager(BaseUserManager):
    use_in_migrations = True

    def get_by_natural_key(self, username):
        return self.get(username__iexact=username)

    def create_user(self, username, password=None, **extra_fields):
        if not username:
            raise ValueError("username is required")
        user = self.model(username=username.strip(), **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, username, password=None, **extra_fields):
        user = self.create_user(username, password, **extra_fields)
        from .models import AdminAccount
        AdminAccount.objects.update_or_create(
            username=user.username,
            defaults={
                "password_hash": user.password,
                "email": user.email,
                "created_at": user.created_at,
                "created_by": user.username,
                "is_super": 1,
                "admin_level": 3,
            },
        )
        return user
