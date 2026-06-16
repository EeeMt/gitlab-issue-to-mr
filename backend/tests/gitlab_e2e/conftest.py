"""Shared fixtures for GitLab E2E tests.

Session-scoped autouse fixture that guarantees all test users exist in the
Codify database, regardless of whether the system was already initialized
by another test suite (e.g. UI E2E).
"""

import hashlib
import logging
import os

import psycopg2
import pytest
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

log = logging.getLogger(__name__)

# Database URL — prefer the E2E-specific env var, fall back to DATABASE_URL.
_POSTGRES_URL = os.getenv(
    "E2E_POSTGRES_URL",
    os.getenv("DATABASE_URL", "postgresql://codify:codify_password@postgres:5432/codify"),
)
# Strip async driver prefix if present (asyncpg → psycopg2 expects plain postgresql://)
if _POSTGRES_URL.startswith("postgresql+asyncpg://"):
    _POSTGRES_URL = _POSTGRES_URL.replace("postgresql+asyncpg://", "postgresql://", 1)

# All test users across GitLab E2E files — (username, password)
_TEST_PASSWORD = "SecurePass123!"
_ALL_TEST_USERS = [
    "test_admin_manual_e2e",   # test_manual_task.py
    "test_admin_gitlab_e2e",   # test_task_execution.py
]


def _hash_password(password: str, salt: str = "gitlab_e2e_salt") -> str:
    """Generate a PBKDF2-HMAC-SHA256 hash compatible with the backend."""
    iterations = 1
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations
    ).hex()
    return f"pbkdf2_sha256${iterations}${salt}${digest}"


def _ensure_test_users() -> None:
    """Insert all test users directly into the database.

    Uses ``ON CONFLICT DO NOTHING`` so it's safe to call repeatedly.
    Also ensures ``system_bootstrap.initialized = TRUE``.
    """
    hashed = _hash_password(_TEST_PASSWORD)

    try:
        conn = psycopg2.connect(_POSTGRES_URL)
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cur = conn.cursor()

        # Ensure the system is marked as initialized
        cur.execute("UPDATE system_bootstrap SET initialized = TRUE WHERE id = 1")

        for username in _ALL_TEST_USERS:
            cur.execute("""
                INSERT INTO users (username, display_name, email, local_password_hash,
                                   auth_provider, platform_role, platform_role_source,
                                   state, created_at, updated_at)
                VALUES (%s, %s, %s, %s, 'local', 'platform_admin', 'bootstrap', 'active',
                        NOW(), NOW())
                ON CONFLICT (username) DO NOTHING
            """, (username, username, f"{username}@test.example.com", hashed))

        cur.close()
        conn.close()
        log.info("Ensured %d GitLab E2E test users exist in DB", len(_ALL_TEST_USERS))
    except Exception as exc:
        log.warning("Failed to ensure test users via DB (tests may skip): %s", exc)


@pytest.fixture(scope="session", autouse=True)
def gitlab_e2e_test_users():
    """Session fixture: create all GitLab E2E test users before any test runs."""
    _ensure_test_users()
