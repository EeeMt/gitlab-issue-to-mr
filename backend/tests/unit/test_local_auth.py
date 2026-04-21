#!/usr/bin/env python3
"""Unit tests for local_auth helpers (password hashing and verification)."""

import hashlib
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.core.local_auth import hash_password, is_password_hash_valid, verify_password


class HashPasswordTests(unittest.TestCase):
    """Tests for hash_password function."""

    def test_hash_password_returns_pbkdf2_format(self) -> None:
        """hash_password should return a string in pbkdf2_sha256$600000$... format."""
        result = hash_password("mypassword")
        parts = result.split("$")
        self.assertEqual(parts[0], "pbkdf2_sha256")
        self.assertEqual(parts[1], "600000")
        self.assertEqual(len(parts), 4)

    def test_hash_password_unique_salts(self) -> None:
        """Two calls with same password should produce different salts."""
        hash1 = hash_password("samepassword")
        hash2 = hash_password("samepassword")
        salt1 = hash1.split("$")[2]
        salt2 = hash2.split("$")[2]
        self.assertNotEqual(salt1, salt2)


class VerifyPasswordTests(unittest.TestCase):
    """Tests for verify_password function."""

    def test_verify_password_correct_pbkdf2(self) -> None:
        """Hash then verify with same password should return True."""
        password = "correctpassword"
        hashed = hash_password(password)
        self.assertTrue(verify_password(password, hashed))

    def test_verify_password_wrong_password(self) -> None:
        """Verifying with wrong password should return False."""
        hashed = hash_password("abc")
        self.assertFalse(verify_password("xyz", hashed))

    def test_verify_password_sha256_format(self) -> None:
        """Should verify passwords stored in sha256$<digest> format."""
        password = "pass"
        digest = hashlib.sha256(password.encode("utf-8")).hexdigest()
        sha256_hash = f"sha256${digest}"
        self.assertTrue(verify_password(password, sha256_hash))

    def test_verify_password_sha256_wrong_password(self) -> None:
        """sha256 format with wrong password should return False."""
        password = "pass"
        digest = hashlib.sha256(password.encode("utf-8")).hexdigest()
        sha256_hash = f"sha256${digest}"
        self.assertFalse(verify_password("wrongpass", sha256_hash))

    def test_verify_password_empty_hash(self) -> None:
        """Empty hash string should return False."""
        self.assertFalse(verify_password("pass", ""))

    def test_verify_password_none_hash(self) -> None:
        """None hash should return False (guarded by 'if not password_hash')."""
        self.assertFalse(verify_password("pass", None))

    def test_verify_password_invalid_format(self) -> None:
        """Non-hash string should return False."""
        self.assertFalse(verify_password("pass", "not-a-hash"))

    def test_verify_password_invalid_iterations(self) -> None:
        """pbkdf2 hash with non-integer iterations should return False."""
        self.assertFalse(verify_password("pass", "pbkdf2_sha256$notanint$somesalt$somedigest"))


class IsPasswordHashValidTests(unittest.TestCase):
    """Tests for is_password_hash_valid function."""

    def test_is_password_hash_valid_pbkdf2(self) -> None:
        """A valid pbkdf2 hash should return True."""
        valid_hash = hash_password("somepassword")
        self.assertTrue(is_password_hash_valid(valid_hash))

    def test_is_password_hash_valid_sha256(self) -> None:
        """A valid sha256 hash string should return True."""
        digest = hashlib.sha256(b"somepassword").hexdigest()
        self.assertTrue(is_password_hash_valid(f"sha256${digest}"))

    def test_is_password_hash_valid_empty(self) -> None:
        """Empty string should return False."""
        self.assertFalse(is_password_hash_valid(""))

    def test_is_password_hash_valid_invalid_format(self) -> None:
        """Garbage string should return False."""
        self.assertFalse(is_password_hash_valid("garbage-string"))

    def test_is_password_hash_valid_bad_iterations(self) -> None:
        """pbkdf2 hash with non-integer iterations should return False."""
        self.assertFalse(is_password_hash_valid("pbkdf2_sha256$notint$salt$digest"))


if __name__ == "__main__":
    unittest.main()
