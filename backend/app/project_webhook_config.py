"""Persistence helpers for project-specific GitLab webhook secrets."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config_crypto import decrypt_config_secret, encrypt_config_secret
from app.models import ProjectWebhookConfig


async def get_project_webhook_secret(db: AsyncSession, project_id: int) -> str | None:
    """Return the decrypted webhook secret for one project, if managed locally."""
    record = await db.get(ProjectWebhookConfig, project_id)
    if record is None:
        return None
    return decrypt_config_secret(record.secret_encrypted)


async def has_project_webhook_secret(db: AsyncSession, project_id: int) -> bool:
    """Return whether one project has a locally managed webhook secret."""
    return await db.get(ProjectWebhookConfig, project_id) is not None


async def save_project_webhook_secret(db: AsyncSession, project_id: int, secret: str) -> None:
    """Encrypt and persist one project's webhook secret."""
    secret_encrypted = encrypt_config_secret(secret)
    record = await db.get(ProjectWebhookConfig, project_id)
    if record is None:
        db.add(ProjectWebhookConfig(project_id=project_id, secret_encrypted=secret_encrypted))
    else:
        record.secret_encrypted = secret_encrypted
    await db.flush()
