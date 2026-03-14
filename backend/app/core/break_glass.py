"""Helpers for emergency break-glass authentication."""

from __future__ import annotations

import hmac
from hashlib import pbkdf2_hmac, sha256


def get_break_glass_identity(username: str) -> tuple[str, int]:
    """Return a deterministic synthetic identity for the emergency admin user."""
    normalized = username.strip()
    oidc_sub = f"break_glass:{normalized}"
    digest = sha256(oidc_sub.encode("utf-8")).digest()
    derived_id = int.from_bytes(digest[:4], "big")
    return oidc_sub, -(derived_id or 1)


def verify_break_glass_password(password: str, stored_hash: str) -> bool:
    """Verify a password against a configured break-glass hash.

    Supported formats:
    - ``sha256$<hex_digest>``
    - ``pbkdf2_sha256$<iterations>$<salt_hex>$<digest_hex>``
    """
    if not stored_hash:
        return False

    if stored_hash.startswith("sha256$"):
        expected = stored_hash.partition("$")[2]
        actual = sha256(password.encode("utf-8")).hexdigest()
        return hmac.compare_digest(actual, expected)

    if stored_hash.startswith("pbkdf2_sha256$"):
        try:
            _scheme, iterations_text, salt_hex, digest_hex = stored_hash.split("$", 3)
            iterations = int(iterations_text)
            actual = pbkdf2_hmac(
                "sha256",
                password.encode("utf-8"),
                bytes.fromhex(salt_hex),
                iterations,
            ).hex()
        except (ValueError, TypeError):
            return False
        return hmac.compare_digest(actual, digest_hex)

    return False
