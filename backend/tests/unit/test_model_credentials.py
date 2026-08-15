"""Tests for persistent model credential lifecycle and reference protection."""

from __future__ import annotations

import os

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

os.environ.setdefault("CONFIG_ENCRYPTION_KEY", "unit-test-key")
from app.config import get_settings  # noqa: E402

# Another test may have cached settings with the default (rejected) key before
# we set CONFIG_ENCRYPTION_KEY; force a re-read so encrypt/decrypt are stable.
get_settings.cache_clear()

from app.core.model_credentials import (  # noqa: E402
    CredentialError,
    assert_credential_not_hard_referenced,
    create_model_credential,
    get_credential,
    resolve_task_credential,
    soft_retire_credential,
)
from app.models import (  # noqa: E402
    Base,
    ModelCredential,
    Task,
    TaskWorkerProfileSnapshot,
)


async def test_legacy_plaintext_secret_resolves_like_encrypted(session_factory):
    # migration 064 copies ai_providers.api_key verbatim; keys stored before
    # encryption existed are plaintext in secret_encrypted. credential_secret
    # must fall back to the raw value instead of failing to decrypt.
    async with session_factory() as db:
        credential = ModelCredential(
            name="legacy provider credential",
            ref="cred-legacy-plain",
            secret_encrypted="sk-legacy-plaintext-key",
            kind="api_key",
            status="active",
        )
        db.add(credential)
        await db.flush()
        resolved = await resolve_task_credential(db, credential.ref)
        assert resolved["secret"] == "sk-legacy-plaintext-key"


@pytest_asyncio.fixture
async def session_factory():
    # Another test may have removed CONFIG_ENCRYPTION_KEY from the env and
    # cached a default-key settings object; hard-set and re-read so the Fernet
    # key used to encrypt/decrypt is stable within this test.
    os.environ["CONFIG_ENCRYPTION_KEY"] = "unit-test-key"
    get_settings.cache_clear()
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", poolclass=StaticPool
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


async def test_create_and_resolve_active_credential(session_factory):
    async with session_factory() as db:
        credential = await create_model_credential(
            db, name="ds key", secret="sk-real-secret", provider_kind="anthropic_compatible"
        )
        resolved = await resolve_task_credential(db, credential.ref)
        assert resolved["secret"] == "sk-real-secret"
        assert resolved["status"] == "active"


async def test_retired_credential_blocks_new_selection_but_allows_retry(session_factory):
    async with session_factory() as db:
        credential = await create_model_credential(db, name="ds key", secret="sk-x")
        await soft_retire_credential(db, credential.ref)
        with pytest.raises(CredentialError):
            await resolve_task_credential(db, credential.ref)
        resolved = await resolve_task_credential(db, credential.ref, allow_retired=True)
        assert resolved["status"] == "retired"
        assert resolved["secret"] == "sk-x"


async def test_revoked_credential_fails_closed_even_for_retry(session_factory):
    async with session_factory() as db:
        credential = await create_model_credential(db, name="k", secret="sk-y")
        credential.status = "revoked"
        await db.flush()
        with pytest.raises(CredentialError):
            await resolve_task_credential(db, credential.ref, allow_retired=True)


async def test_missing_credential_raises(session_factory):
    async with session_factory() as db:
        with pytest.raises(CredentialError):
            await resolve_task_credential(db, "cred-does-not-exist")


async def test_hard_delete_refused_while_referenced_by_snapshot(session_factory):
    async with session_factory() as db:
        credential = await create_model_credential(db, name="k", secret="sk-z")
        task = Task(issue_id=1, project_id=1, user_prompt="p")
        db.add(task)
        await db.flush()
        db.add(
            TaskWorkerProfileSnapshot(
                task_id=task.id,
                profile_name="p",
                image="img",
                default_execute_run_instruction_template="x",
                default_plan_run_instruction_template="y",
                ci_auto_repair_run_instruction_template="z",
                harness_key="claude",
                credential_ref=credential.ref,
            )
        )
        await db.flush()
        with pytest.raises(CredentialError):
            await assert_credential_not_hard_referenced(db, credential.ref)


async def test_hard_delete_allowed_when_unreferenced(session_factory):
    async with session_factory() as db:
        credential = await create_model_credential(db, name="k", secret="sk-w")
        # No exception means hard-delete is permitted.
        await assert_credential_not_hard_referenced(db, credential.ref)
        assert (await get_credential(db, credential.ref)).ref == credential.ref
