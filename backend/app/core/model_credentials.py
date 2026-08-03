"""Persistent model credential lifecycle and reference protection.

Provider and credential lifecycles are decoupled: deleting a Provider deletes
only its Endpoint config. A credential referenced by any retryable Task
snapshot can only be soft-retired, never hard-deleted.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config_crypto import decrypt_config_secret, encrypt_config_secret
from app.models import ModelCredential, TaskWorkerProfileSnapshot


class CredentialError(ValueError):
    """Credential resolution or lifecycle violation."""


def new_credential_ref() -> str:
    return f"cred-{uuid4().hex[:16]}"


async def create_model_credential(
    db: AsyncSession,
    *,
    name: str,
    secret: str,
    kind: str = "api_key",
    provider_kind: str | None = None,
) -> ModelCredential:
    credential = ModelCredential(
        name=name,
        ref=new_credential_ref(),
        secret_encrypted=encrypt_config_secret(secret),
        kind=kind,
        status="active",
        provider_kind=provider_kind,
    )
    db.add(credential)
    await db.flush()
    return credential


async def get_credential(
    db: AsyncSession, ref: str
) -> ModelCredential | None:
    return (
        await db.execute(
            select(ModelCredential).where(ModelCredential.ref == ref)
        )
    ).scalar_one_or_none()


def credential_secret(credential: ModelCredential) -> str:
    return decrypt_config_secret(credential.secret_encrypted)


async def soft_retire_credential(db: AsyncSession, ref: str) -> None:
    credential = await get_credential(db, ref)
    if credential is None:
        raise CredentialError(f"credential not found: {ref}")
    if credential.status == "revoked":
        raise CredentialError(f"credential {ref} is revoked; cannot be retired")
    credential.status = "retired"
    credential.retired_at = datetime.now(UTC)
    await db.flush()


async def assert_credential_not_hard_referenced(
    db: AsyncSession, ref: str
) -> None:
    """Refuse hard-deletion while any retryable Task snapshot references it."""
    referenced = (
        await db.execute(
            select(TaskWorkerProfileSnapshot.task_id)
            .where(TaskWorkerProfileSnapshot.credential_ref == ref)
            .limit(1)
        )
    ).scalar_one_or_none()
    if referenced is not None:
        raise CredentialError(
            f"credential {ref} is referenced by Task snapshot and cannot be "
            "hard-deleted; retire it instead"
        )


async def resolve_task_credential(
    db: AsyncSession, ref: str, *, allow_retired: bool = False
) -> dict[str, Any]:
    """Resolve a credential for execution.

    ``active`` is always resolvable; ``retired`` is resolvable only for an
    existing Task retry (``allow_retired``); ``revoked`` always fails closed.
    """
    credential = await get_credential(db, ref)
    if credential is None:
        raise CredentialError(f"credential not found: {ref}")
    if credential.status == "revoked":
        raise CredentialError(
            f"credential {ref} is revoked; execution blocked (audit required)"
        )
    if credential.status == "retired" and not allow_retired:
        raise CredentialError(
            f"credential {ref} is retired; new selection blocked"
        )
    return {
        "ref": credential.ref,
        "status": credential.status,
        "kind": credential.kind,
        "provider_kind": credential.provider_kind,
        "secret": credential_secret(credential),
        "version_metadata": credential.version_metadata,
    }
