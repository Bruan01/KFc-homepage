"""Password hasher compatible with both legacy and Django PBKDF2 encodings."""
from __future__ import annotations

import hashlib
import hmac

from django.contrib.auth.hashers import PBKDF2PasswordHasher, mask_hash
from django.utils.crypto import constant_time_compare


class LegacyHexPBKDF2PasswordHasher(PBKDF2PasswordHasher):
    """Write Django's standard PBKDF2 format while accepting legacy hex hashes.

    Both formats use the ``pbkdf2_sha256`` algorithm prefix. The legacy
    application encoded a 16-byte salt and digest as hexadecimal; Django uses
    a textual salt and base64 digest. Detection therefore happens inside this
    single registered hasher.
    """

    def verify(self, password, encoded):
        if not self._is_legacy(encoded):
            return super().verify(password, encoded)
        try:
            algorithm, iterations, salt_hex, expected_hex = encoded.split("$", 3)
            salt = bytes.fromhex(salt_hex)
            expected = bytes.fromhex(expected_hex)
            actual = hashlib.pbkdf2_hmac(
                "sha256",
                password.encode("utf-8"),
                salt,
                int(iterations),
            )
        except (TypeError, ValueError):
            return False
        return hmac.compare_digest(actual, expected)

    def must_update(self, encoded):
        if self._is_legacy(encoded):
            return True
        return super().must_update(encoded)

    def safe_summary(self, encoded):
        if not self._is_legacy(encoded):
            return super().safe_summary(encoded)
        algorithm, iterations, salt, digest = encoded.split("$", 3)
        return {
            "algorithm": algorithm,
            "iterations": iterations,
            "salt": mask_hash(salt),
            "hash": mask_hash(digest),
        }

    @staticmethod
    def _is_legacy(encoded):
        try:
            algorithm, _iterations, salt, digest = encoded.split("$", 3)
            if algorithm != "pbkdf2_sha256" or len(salt) != 32 or len(digest) != 64:
                return False
            bytes.fromhex(salt)
            bytes.fromhex(digest)
        except (AttributeError, TypeError, ValueError):
            return False
        return True
