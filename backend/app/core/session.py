"""Server-side session helpers for dashboard authentication."""

from __future__ import annotations

import hmac
import secrets
import uuid
from datetime import datetime, timedelta
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_effective_settings, get_settings
from app.core.config_crypto import decrypt_config_secret, encrypt_config_secret
from app.models import User, UserSession


def _utcnow() -> datetime:
    return datetime.utcnow()


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
    max_expires_at: datetime | None = None,
) -> str:
    """Create a new session row and return the raw session token."""
    settings = get_effective_settings()
    raw_token = generate_session_token()
    expires_at = _utcnow() + timedelta(seconds=settings.session_ttl_seconds)
    if max_expires_at is not None and max_expires_at < expires_at:
        expires_at = max_expires_at
    session = UserSession(
        id=str(uuid.uuid4()),
        user_id=user.id,
        session_token_hash=hash_session_token(raw_token),
        gitlab_access_token_encrypted=(
            encrypt_config_secret(gitlab_access_token) if gitlab_access_token else None
        ),
        expires_at=expires_at,
        last_seen_at=_utcnow(),
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.add(session)
    await db.flush()
    return raw_token


async def get_user_and_session_from_session_token(
    db: AsyncSession, token: str | None
) -> tuple[User | None, UserSession | None]:
    """Resolve a user and session row from a raw session token."""
    if not token:
        return None, None

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
        return None, None

    user, session = row
    now = _utcnow()
    if session.expires_at <= now or user.state != "active":
        session.revoked_at = now
        await db.flush()
        return None, None

    session.last_seen_at = now
    await db.flush()
    return user, session


async def get_user_from_session_token(db: AsyncSession, token: str | None) -> User | None:
    """Resolve a user from a raw session token."""
    user, _session = await get_user_and_session_from_session_token(db, token)
    return user


def get_gitlab_access_token_from_session(session: UserSession) -> str | None:
    """Decrypt the GitLab access token stored for a session, if present."""
    if not session.gitlab_access_token_encrypted:
        return None
    return decrypt_config_secret(session.gitlab_access_token_encrypted)


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
        session.revoked_at = _utcnow()
        await db.flush()
