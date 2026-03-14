#!/usr/bin/env python3
"""Unit tests for break-glass auth helpers."""

import os
import sys
import unittest
from hashlib import pbkdf2_hmac, sha256

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.core.break_glass import get_break_glass_identity, verify_break_glass_password


class BreakGlassTests(unittest.TestCase):
    def test_break_glass_identity_is_deterministic(self) -> None:
        oidc_sub, gitlab_user_id = get_break_glass_identity("emergency-admin")

        self.assertEqual(oidc_sub, "break_glass:emergency-admin")
        self.assertLess(gitlab_user_id, 0)
        self.assertEqual((oidc_sub, gitlab_user_id), get_break_glass_identity("emergency-admin"))

    def test_verify_break_glass_password_supports_sha256(self) -> None:
        stored_hash = f"sha256${sha256(b'super-secret').hexdigest()}"

        self.assertTrue(verify_break_glass_password("super-secret", stored_hash))
        self.assertFalse(verify_break_glass_password("wrong-password", stored_hash))

    def test_verify_break_glass_password_supports_pbkdf2(self) -> None:
        salt = bytes.fromhex("00112233445566778899aabbccddeeff")
        digest = pbkdf2_hmac("sha256", b"super-secret", salt, 600000).hex()
        stored_hash = f"pbkdf2_sha256$600000${salt.hex()}${digest}"

        self.assertTrue(verify_break_glass_password("super-secret", stored_hash))
        self.assertFalse(verify_break_glass_password("wrong-password", stored_hash))


if __name__ == "__main__":
    unittest.main()
