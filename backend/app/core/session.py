"""Server-side session helpers for dashboard authentication."""

from __future__ import annotations

import hmac
import secrets
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_effective_settings, get_settings
from app.core.config_crypto import decrypt_config_secret, encrypt_config_secret
from app.core.utcnow import utcnow
from app.models import User, UserSession

SESSION_RETENTION_DAYS = 30  # kept for backward compat (tests); runtime uses get_effective_settings()

# Backward-compatible alias for tests that import the old private helper.
_utcnow = utcnow

# Throttle last_seen_at writes: only update in DB once per this many seconds per session.
# This prevents the SSE log stream (which keeps a DB session open for its lifetime)
# from holding a row-level lock on user_sessions indefinitely.
_LAST_SEEN_WRITE_INTERVAL_SECONDS = 60
_last_seen_written_at: dict[str, float] = {}


@dataclass
class SessionAuthResult:
    """Resolved user/session pair plus an optional authentication failure detail."""

    user: User | None
    session: UserSession | None
    failure_detail: str | None = None


def hash_session_token(token: str) -> str:
    """Hash a session token before persisting it."""
    secret = get_settings().session_secret.encode("utf-8")
    return hmac.new(secret, token.encode("utf-8"), sha256).hexdigest()


def generate_session_token() -> str:
    return secrets.token_urlsafe(48)


async def create_user_session(
    db: AsyncSession,
    user: User,
    ip_address: str | None = None,
    user_agent: str | None = None,
    gitlab_access_token: str | None = None,
    gitlab_refresh_token: str | None = None,
    max_expires_at: datetime | None = None,
) -> str:
    """Create a new session row and return the raw session token."""
    settings = get_effective_settings()
    raw_token = generate_session_token()
    expires_at = utcnow() + timedelta(seconds=settings.session_ttl_seconds)
    if max_expires_at is not None and max_expires_at < expires_at:
        expires_at = max_expires_at
    session = UserSession(
        id=str(uuid.uuid4()),
        user_id=user.id,
        session_token_hash=hash_session_token(raw_token),
        gitlab_access_token_encrypted=(
            encrypt_config_secret(gitlab_access_token) if gitlab_access_token else None
        ),
        gitlab_refresh_token_encrypted=(
            encrypt_config_secret(gitlab_refresh_token) if gitlab_refresh_token else None
        ),
        expires_at=expires_at,
        last_seen_at=utcnow(),
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.add(session)
    await db.flush()
    return raw_token


async def resolve_session_authentication(
    db: AsyncSession, token: str | None
) -> SessionAuthResult:
    """Resolve a user and session row from a raw session token."""
    if not token:
        return SessionAuthResult(user=None, session=None)

    token_hash = hash_session_token(token)
    result = await db.execute(
        select(User, UserSession)
        .join(UserSession, UserSession.user_id == User.id)
        .where(
            UserSession.session_token_hash == token_hash,
            UserSession.revoked_at.is_(None),
        )
    )
    row = result.first()
    if not row:
        return SessionAuthResult(
            user=None,
            session=None,
            failure_detail="Session not found or already signed out. Please sign in again.",
        )

    user, session = row
    now = utcnow()
    if session.expires_at <= now:
        session.revoked_at = now
        await db.flush()
        return SessionAuthResult(
            user=None,
            session=None,
            failure_detail="Your dashboard session expired. Please sign in again.",
        )

    if user.state != "active":
        session.revoked_at = now
        await db.flush()
        return SessionAuthResult(
            user=None,
            session=None,
            failure_detail="Your dashboard account is disabled.",
        )

    session.last_seen_at = now
    now_ts = time.time()
    last_write = _last_seen_written_at.get(session.id, 0.0)
    if now_ts - last_write >= _LAST_SEEN_WRITE_INTERVAL_SECONDS:
        # Commit immediately so the row lock is released before the request
        # handler runs. Without this, a long-lived SSE streaming response would
        # hold the lock for its entire lifetime, blocking all polling requests
        # from the same user.
        await db.commit()
        _last_seen_written_at[session.id] = now_ts
    return SessionAuthResult(user=user, session=session)


async def get_user_and_session_from_session_token(
    db: AsyncSession, token: str | None
) -> tuple[User | None, UserSession | None]:
    """Resolve a user and session row from a raw session token."""
    result = await resolve_session_authentication(db, token)
    return result.user, result.session


async def get_user_from_session_token(db: AsyncSession, token: str | None) -> User | None:
    """Resolve a user from a raw session token."""
    user, _session = await get_user_and_session_from_session_token(db, token)
    return user


def get_gitlab_access_token_from_session(session: UserSession) -> str | None:
    """Decrypt the GitLab access token stored for a session, if present."""
    if not session.gitlab_access_token_encrypted:
        return None
    return decrypt_config_secret(session.gitlab_access_token_encrypted)


def get_gitlab_refresh_token_from_session(session: UserSession) -> str | None:
    """Decrypt the GitLab refresh token stored for a session, if present."""
    if not session.gitlab_refresh_token_encrypted:
        return None
    return decrypt_config_secret(session.gitlab_refresh_token_encrypted)


async def update_session_gitlab_tokens(
    db: AsyncSession,
    session: UserSession,
    *,
    gitlab_access_token: str | None,
    gitlab_refresh_token: str | None = None,
    max_expires_at: datetime | None = None,
) -> None:
    """Update encrypted GitLab tokens and optional session expiry."""
    session.gitlab_access_token_encrypted = (
        encrypt_config_secret(gitlab_access_token) if gitlab_access_token else None
    )
    if gitlab_refresh_token is not None:
        session.gitlab_refresh_token_encrypted = (
            encrypt_config_secret(gitlab_refresh_token) if gitlab_refresh_token else None
        )
    if max_expires_at is not None and max_expires_at < session.expires_at:
        session.expires_at = max_expires_at
    session.last_seen_at = utcnow()
    await db.flush()


async def revoke_session_token(db: AsyncSession, token: str | None) -> None:
    """Revoke one session token if it exists."""
    if not token:
        return

    token_hash = hash_session_token(token)
    result = await db.execute(
        select(UserSession).where(UserSession.session_token_hash == token_hash)
    )
    session = result.scalar_one_or_none()
    if session and session.revoked_at is None:
        session.revoked_at = utcnow()
        await db.flush()


async def revoke_user_sessions(db: AsyncSession, user_id: int) -> int:
    """Revoke all active sessions for a user and return the number revoked."""
    result = await db.execute(
        select(UserSession).where(
            UserSession.user_id == user_id,
            UserSession.revoked_at.is_(None),
        )
    )
    sessions = list(result.scalars().all())
    now = utcnow()
    revoked_count = 0
    for session in sessions:
        session.revoked_at = now
        revoked_count += 1
    if sessions:
        await db.flush()
    return revoked_count


async def revoke_session_by_id(db: AsyncSession, session_id: str) -> bool:
    """Revoke one session by its database id."""
    result = await db.execute(select(UserSession).where(UserSession.id == session_id))
    session = result.scalar_one_or_none()
    if session is None or session.revoked_at is not None:
        return False
    session.revoked_at = utcnow()
    await db.flush()
    return True


async def cleanup_stale_sessions(
    db: AsyncSession,
    *,
    retention_days: int | None = None,
) -> int:
    """Delete sessions that expired or were revoked before the retention cutoff."""
    if retention_days is None:
        retention_days = get_effective_settings().session_retention_days
    cutoff = utcnow() - timedelta(days=retention_days)
    result = await db.execute(
        delete(UserSession).where(
            func.coalesce(UserSession.revoked_at, UserSession.expires_at) < cutoff
        )
    )
    return result.rowcount or 0
