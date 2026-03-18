"""Local authentication helpers for password hashing and verification."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from typing import Tuple


def hash_password(password: str) -> str:
    """
    Hash a password using PBKDF2-HMAC-SHA256.
    
    Format: pbkdf2_sha256$<iterations>$<salt_hex>$<digest_hex>
    
    Args:
        password: Plain text password to hash
        
    Returns:
        Hashed password string
    """
    salt = secrets.token_hex(16)
    iterations = 600000
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    ).hex()
    return f"pbkdf2_sha256${iterations}${salt}${digest}"


def verify_password(password: str, password_hash: str) -> bool:
    """
    Verify a password against a hash.
    
    Supports formats:
    - pbkdf2_sha256$<iterations>$<salt_hex>$<digest_hex>
    - sha256$<hex_digest>
    
    Args:
        password: Plain text password to verify
        password_hash: Stored password hash
        
    Returns:
        True if password matches, False otherwise
    """
    if not password_hash:
        return False
    
    parts = password_hash.split("$")
    
    if len(parts) == 4 and parts[0] == "pbkdf2_sha256":
        # PBKDF2 format: pbkdf2_sha256$iterations$salt$digest
        _, iterations_str, salt, expected_digest = parts
        try:
            iterations = int(iterations_str)
        except ValueError:
            return False
        
        computed_digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            iterations,
        ).hex()
        
        return hmac.compare_digest(computed_digest, expected_digest)
    
    elif len(parts) == 2 and parts[0] == "sha256":
        # Simple SHA256 format: sha256$digest
        _, expected_digest = parts
        computed_digest = hashlib.sha256(password.encode("utf-8")).hexdigest()
        return hmac.compare_digest(computed_digest, expected_digest)
    
    return False


def is_password_hash_valid(password_hash: str) -> bool:
    """
    Check if a password hash has a valid format.
    
    Args:
        password_hash: Hash string to validate
        
    Returns:
        True if format is valid, False otherwise
    """
    if not password_hash:
        return False
    
    parts = password_hash.split("$")
    
    if len(parts) == 4 and parts[0] == "pbkdf2_sha256":
        try:
            int(parts[1])  # iterations
            return True
        except ValueError:
            return False
    
    elif len(parts) == 2 and parts[0] == "sha256":
        return True
    
    return False
