import hashlib

from django.contrib.auth.hashers import check_password, make_password
from django.test import TestCase

from .models import User


def legacy_hash(password: str, *, iterations: int = 240000) -> str:
    salt = bytes.fromhex("00112233445566778899aabbccddeeff")
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


class PasswordCompatibilityTests(TestCase):
    def test_legacy_hex_hash_is_accepted_and_upgraded_on_user_check(self):
        user = User.objects.create(
            username="legacy-user",
            password=legacy_hash("secret-pass"),
            email="legacy@example.com",
            created_at="2026-08-01T00:00:00+00:00",
        )

        self.assertTrue(user.check_password("secret-pass"))
        user.refresh_from_db()
        self.assertTrue(check_password("secret-pass", user.password))
        self.assertNotEqual(len(user.password.split("$", 3)[2]), 32)

    def test_new_password_uses_django_standard_encoding(self):
        encoded = make_password("new-password")
        algorithm, _iterations, salt, digest = encoded.split("$", 3)
        self.assertEqual(algorithm, "pbkdf2_sha256")
        self.assertFalse(len(salt) == 32 and all(ch in "0123456789abcdef" for ch in salt))
        self.assertTrue(check_password("new-password", encoded))
