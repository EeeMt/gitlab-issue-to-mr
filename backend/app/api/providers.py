"""AI Provider CRUD API endpoints."""

import logging
import re

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config_crypto import (
    ConfigEncryptionError,
    decrypt_config_secret,
    encrypt_config_secret,
)
from app.core.harness_registry import compatible_harness_keys
from app.core.model_credentials import (
    CredentialError,
    create_model_credential,
    get_credential,
    soft_retire_credential,
)
from app.core.model_endpoints import COMPAT_PROFILES
from app.database import get_db
from app.dependencies.auth import require_admin_user
from app.models import AIProvider, Task, TaskStatus, User

logger = logging.getLogger(__name__)
router = APIRouter()

_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,99}$")

# Model-protocol / provider-kind allowlist. Claude consumes anthropic_messages;
# Codex consumes openai_responses. Chat Completions is not silently converted.
VALID_PROVIDER_KINDS = frozenset({"anthropic_compatible", "openai_compatible"})
VALID_MODEL_PROTOCOLS = frozenset(
    {"anthropic_messages", "openai_responses", "openai_chat_completions"}
)
KIND_PROTOCOLS: dict[str, frozenset[str]] = {
    "anthropic_compatible": frozenset({"anthropic_messages"}),
    "openai_compatible": frozenset(
        {"openai_responses", "openai_chat_completions"}
    ),
}
PROVIDER_DRIVER_PROTOCOLS: dict[str, frozenset[str]] = {
    # OpenRouter exposes the same model through all three supported wire
    # protocols. Keep this exception explicit instead of widening every
    # OpenAI-compatible endpoint to an unverified Anthropic Messages path.
    "openrouter": frozenset(VALID_MODEL_PROTOCOLS),
}


def _validate_kind_protocol(
    provider_kind: str,
    model_protocol: str,
    provider_options: dict,
    provider_driver: str | None = None,
) -> None:
    if provider_kind not in VALID_PROVIDER_KINDS:
        raise ValueError(f"unknown provider_kind: {provider_kind!r}")
    if model_protocol not in VALID_MODEL_PROTOCOLS:
        raise ValueError(f"unknown model_protocol: {model_protocol!r}")
    allowed_protocols = KIND_PROTOCOLS[provider_kind]
    if provider_driver in PROVIDER_DRIVER_PROTOCOLS:
        allowed_protocols = PROVIDER_DRIVER_PROTOCOLS[provider_driver]
    if model_protocol not in allowed_protocols:
        raise ValueError(
            f"provider_kind {provider_kind!r} cannot consume model_protocol "
            f"{model_protocol!r}"
        )
    if not isinstance(provider_options, dict):
        raise ValueError("provider_options must be an object")


# ── Schemas ────────────────────────────────────────────────────────────────────

class ProviderResponse(BaseModel):
    id: int
    name: str
    base_url: str
    api_key_configured: bool
    model: str
    max_turns: int
    system_prompt: str | None
    provider_kind: str
    model_protocol: str
    compat_profile: str | None
    provider_driver: str | None
    provider_options: dict
    credential_ref: str | None
    credential_status: str | None
    is_default: bool
    is_disabled: bool
    created_at: str
    updated_at: str


class CreateProviderRequest(BaseModel):
    name: str
    base_url: str
    api_key: str | None = None
    model: str
    max_turns: int = 20
    system_prompt: str | None = None
    provider_kind: str = "anthropic_compatible"
    model_protocol: str = "anthropic_messages"
    compat_profile: str | None = None
    provider_driver: str | None = None
    provider_options: dict = {}
    is_disabled: bool = False

    @model_validator(mode="after")
    def validate_kind_protocol(self) -> "CreateProviderRequest":
        _validate_kind_protocol(
            self.provider_kind,
            self.model_protocol,
            self.provider_options,
            self.provider_driver,
        )
        return self

    @field_validator("compat_profile")
    @classmethod
    def validate_compat_profile(cls, v: str | None) -> str | None:
        if v is not None and v not in COMPAT_PROFILES:
            raise ValueError(f"unknown compat_profile: {v!r}")
        return v

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not _NAME_RE.match(v):
            raise ValueError(
                "Name must be 1-100 characters, alphanumeric/hyphens/underscores, "
                "starting with alphanumeric"
            )
        return v

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("Base URL must start with http:// or https://")
        return v

    @field_validator("model")
    @classmethod
    def validate_model(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Model name cannot be empty")
        return v.strip()

    @field_validator("max_turns")
    @classmethod
    def validate_max_turns(cls, v: int) -> int:
        if v < 1 or v > 1000:
            raise ValueError("Max turns must be between 1 and 1000")
        return v

    @field_validator("system_prompt")
    @classmethod
    def validate_system_prompt(cls, v: str | None) -> str | None:
        if v is not None and len(v) > 10000:
            raise ValueError("System prompt must be 10000 characters or fewer")
        return v


class UpdateProviderRequest(BaseModel):
    name: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    clear_api_key: bool = False
    model: str | None = None
    max_turns: int | None = None
    system_prompt: str | None = None
    clear_system_prompt: bool = False
    provider_kind: str | None = None
    model_protocol: str | None = None
    compat_profile: str | None = None
    clear_compat_profile: bool = False
    provider_driver: str | None = None
    provider_options: dict | None = None
    is_disabled: bool | None = None

    @model_validator(mode="after")
    def validate_kind_protocol(self) -> "UpdateProviderRequest":
        if self.provider_kind is not None and self.model_protocol is not None:
            _validate_kind_protocol(
                self.provider_kind,
                self.model_protocol,
                self.provider_options or {},
                self.provider_driver,
            )
        elif self.provider_kind is not None and self.provider_kind not in VALID_PROVIDER_KINDS:
            raise ValueError(f"unknown provider_kind: {self.provider_kind!r}")
        elif self.model_protocol is not None and self.model_protocol not in VALID_MODEL_PROTOCOLS:
            raise ValueError(f"unknown model_protocol: {self.model_protocol!r}")
        return self

    @field_validator("compat_profile")
    @classmethod
    def validate_compat_profile(cls, v: str | None) -> str | None:
        if v is not None and v not in COMPAT_PROFILES:
            raise ValueError(f"unknown compat_profile: {v!r}")
        return v

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str | None) -> str | None:
        if v is not None and not _NAME_RE.match(v):
            raise ValueError(
                "Name must be 1-100 characters, alphanumeric/hyphens/underscores, "
                "starting with alphanumeric"
            )
        return v

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, v: str | None) -> str | None:
        if v is not None and not v.startswith(("http://", "https://")):
            raise ValueError("Base URL must start with http:// or https://")
        return v

    @field_validator("model")
    @classmethod
    def validate_model(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("Model name cannot be empty")
        return v.strip() if v else v

    @field_validator("max_turns")
    @classmethod
    def validate_max_turns(cls, v: int | None) -> int | None:
        if v is not None and (v < 1 or v > 1000):
            raise ValueError("Max turns must be between 1 and 1000")
        return v

    @field_validator("system_prompt")
    @classmethod
    def validate_system_prompt(cls, v: str | None) -> str | None:
        if v is not None and len(v) > 10000:
            raise ValueError("System prompt must be 10000 characters or fewer")
        return v


# ── Helpers ────────────────────────────────────────────────────────────────────

async def _resolve_credential_status(
    db: AsyncSession, credential_ref: str | None
) -> str | None:
    if not credential_ref:
        return None
    credential = await get_credential(db, credential_ref)
    return credential.status if credential else None


def _serialize_provider(
    provider: AIProvider, credential_status: str | None = None
) -> dict:
    return {
        "id": provider.id,
        "name": provider.name,
        "base_url": provider.base_url,
        "api_key_configured": (
            getattr(provider, "credential_ref", None) is not None
            or (provider.api_key is not None and provider.api_key != "")
        ),
        "model": provider.model,
        "max_turns": provider.max_turns,
        "system_prompt": provider.system_prompt,
        "provider_kind": getattr(provider, "provider_kind", "anthropic_compatible"),
        "model_protocol": getattr(provider, "model_protocol", "anthropic_messages"),
        "compat_profile": getattr(provider, "compat_profile", None),
        "compatible_harnesses": compatible_harness_keys(
            getattr(provider, "model_protocol", "anthropic_messages")
        ),
        "provider_driver": getattr(provider, "provider_driver", None),
        "provider_options": getattr(provider, "provider_options", None) or {},
        "credential_ref": getattr(provider, "credential_ref", None),
        "credential_status": credential_status,
        "is_default": provider.is_default,
        "is_disabled": provider.is_disabled,
        "created_at": provider.created_at.isoformat(),
        "updated_at": provider.updated_at.isoformat(),
    }


def _decrypt_provider_api_key(provider: AIProvider) -> str:
    """Decrypt a provider's stored API key. Returns empty string if none."""
    if not provider.api_key:
        return ""
    try:
        return decrypt_config_secret(provider.api_key)
    except ConfigEncryptionError:
        # If decryption fails, the value might be stored in plaintext (legacy migration)
        return provider.api_key


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/providers")
async def list_providers(db: AsyncSession = Depends(get_db)):
    """List all AI providers."""
    result = await db.execute(
        select(AIProvider).order_by(AIProvider.is_default.desc(), AIProvider.id)
    )
    providers = result.scalars().all()
    serialized = []
    for provider in providers:
        credential_status = await _resolve_credential_status(
            db, getattr(provider, "credential_ref", None)
        )
        serialized.append(_serialize_provider(provider, credential_status))
    return serialized


@router.get("/providers/{provider_id}")
async def get_provider(provider_id: int, db: AsyncSession = Depends(get_db)):
    """Get a single AI provider."""
    provider = await db.get(AIProvider, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    credential_status = await _resolve_credential_status(
        db, getattr(provider, "credential_ref", None)
    )
    return _serialize_provider(provider, credential_status)


@router.post("/providers", status_code=status.HTTP_201_CREATED)
async def create_provider(
    request: CreateProviderRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin_user),
):
    """Create a new AI provider."""
    # Check name uniqueness
    existing = await db.execute(
        select(AIProvider).where(AIProvider.name == request.name)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Provider with name '{request.name}' already exists",
        )

    # Determine if this should be the default (first provider)
    count_result = await db.execute(select(func.count(AIProvider.id)))
    is_first = count_result.scalar() == 0
    if is_first and request.is_disabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Default provider cannot be disabled",
        )

    # Create an independent ModelCredential for the key; provider.api_key stays
    # as a legacy transition value until the worker resolves via credential_ref.
    encrypted_key = None
    credential_ref = None
    if request.api_key:
        try:
            encrypted_key = encrypt_config_secret(request.api_key)
            credential = await create_model_credential(
                db,
                name=f"{request.name} credential",
                secret=request.api_key,
                provider_kind=request.provider_kind,
            )
            credential_ref = credential.ref
        except ConfigEncryptionError as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to encrypt API key: {e}",
            )

    provider = AIProvider(
        name=request.name,
        base_url=request.base_url,
        api_key=encrypted_key,
        model=request.model,
        max_turns=request.max_turns,
        system_prompt=request.system_prompt,
        provider_kind=request.provider_kind,
        model_protocol=request.model_protocol,
        compat_profile=request.compat_profile,
        provider_driver=request.provider_driver,
        provider_options=request.provider_options,
        credential_ref=credential_ref,
        is_default=is_first,
        is_disabled=request.is_disabled,
    )
    db.add(provider)
    await db.commit()
    await db.refresh(provider)

    logger.info(f"Created AI provider '{provider.name}' (id={provider.id}, default={provider.is_default})")
    credential_status = await _resolve_credential_status(db, credential_ref)
    return _serialize_provider(provider, credential_status)


@router.patch("/providers/{provider_id}")
async def update_provider(
    provider_id: int,
    request: UpdateProviderRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin_user),
):
    """Update an existing AI provider."""
    provider = await db.get(AIProvider, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    # Validate the merged endpoint state before mutating the ORM object.  The
    # PATCH schema can only validate fields supplied in one request; a
    # protocol-only update must still be checked against the provider's
    # existing kind (and vice versa).  Otherwise an Anthropic provider could
    # be persisted with an OpenAI protocol, leaving a fail-open gap between
    # Provider configuration and the frozen worker contract.
    current_provider_kind = (
        getattr(provider, "provider_kind", None) or "anthropic_compatible"
    )
    current_model_protocol = (
        getattr(provider, "model_protocol", None) or "anthropic_messages"
    )
    current_provider_options = getattr(provider, "provider_options", None)
    if not isinstance(current_provider_options, dict):
        current_provider_options = {}
    next_provider_kind = request.provider_kind or current_provider_kind
    next_model_protocol = request.model_protocol or current_model_protocol
    next_provider_options = (
        request.provider_options
        if request.provider_options is not None
        else current_provider_options
    )
    next_provider_driver = request.provider_driver or getattr(
        provider, "provider_driver", None
    )
    try:
        _validate_kind_protocol(
            next_provider_kind,
            next_model_protocol,
            next_provider_options,
            next_provider_driver,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Check name uniqueness if changing
    if request.name is not None and request.name != provider.name:
        existing = await db.execute(
            select(AIProvider).where(AIProvider.name == request.name)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Provider with name '{request.name}' already exists",
            )
        provider.name = request.name

    if request.base_url is not None:
        provider.base_url = request.base_url

    if request.model is not None:
        provider.model = request.model

    if request.max_turns is not None:
        provider.max_turns = request.max_turns

    if request.is_disabled is True and provider.is_default:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Default provider cannot be disabled",
        )

    if request.is_disabled is not None:
        provider.is_disabled = request.is_disabled

    if request.provider_kind is not None:
        provider.provider_kind = request.provider_kind
    if request.model_protocol is not None:
        provider.model_protocol = request.model_protocol
    if request.compat_profile is not None:
        provider.compat_profile = request.compat_profile
    elif request.clear_compat_profile:
        provider.compat_profile = None
    if request.provider_driver is not None:
        provider.provider_driver = request.provider_driver
    if request.provider_options is not None:
        provider.provider_options = request.provider_options

    # Handle API key update/clear with independent credential rotation.
    old_ref = getattr(provider, "credential_ref", None)
    if request.clear_api_key:
        if old_ref:
            try:
                await soft_retire_credential(db, old_ref)
            except CredentialError:
                pass
        provider.api_key = None
        provider.credential_ref = None
    elif request.api_key is not None:
        try:
            provider.api_key = encrypt_config_secret(request.api_key)
            credential = await create_model_credential(
                db,
                name=f"{provider.name} credential",
                secret=request.api_key,
                provider_kind=request.provider_kind or provider.provider_kind,
            )
            provider.credential_ref = credential.ref
            if old_ref and old_ref != credential.ref:
                try:
                    await soft_retire_credential(db, old_ref)
                except CredentialError:
                    pass
        except ConfigEncryptionError as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to encrypt API key: {e}",
            )

    # Handle system_prompt update/clear
    if request.clear_system_prompt:
        provider.system_prompt = None
    elif request.system_prompt is not None:
        provider.system_prompt = request.system_prompt

    await db.commit()
    await db.refresh(provider)

    logger.info(f"Updated AI provider '{provider.name}' (id={provider.id})")
    credential_status = await _resolve_credential_status(
        db, getattr(provider, "credential_ref", None)
    )
    return _serialize_provider(provider, credential_status)


@router.delete("/providers/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provider(
    provider_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin_user),
):
    """Delete an AI provider."""
    provider = await db.get(AIProvider, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    # Check if this is the last provider
    count_result = await db.execute(select(func.count(AIProvider.id)))
    total = count_result.scalar()
    if total <= 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete the only provider — at least one must exist",
        )

    # Check for active tasks using this provider
    active_count_result = await db.execute(
        select(func.count(Task.id)).where(
            Task.provider_id == provider_id,
            Task.status.in_([TaskStatus.PENDING, TaskStatus.QUEUED, TaskStatus.RUNNING]),
        )
    )
    active_count = active_count_result.scalar()
    if active_count > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot delete provider — {active_count} active task(s) reference it",
        )

    was_default = provider.is_default
    new_default = None
    if was_default:
        result = await db.execute(
            select(AIProvider)
            .where(AIProvider.id != provider_id, AIProvider.is_disabled == False)
            .order_by(AIProvider.id)
            .limit(1)
        )
        new_default = result.scalar_one_or_none()
        if not new_default:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot delete default provider — no enabled provider remains",
            )

    # Deleting a Provider removes only the Endpoint config. The independent
    # credential is soft-retired (never hard-deleted) so existing retryable
    # Task snapshots can still resolve it.
    credential_ref = getattr(provider, "credential_ref", None)
    if credential_ref:
        try:
            await soft_retire_credential(db, credential_ref)
        except CredentialError:
            pass

    await db.delete(provider)

    # If we deleted the default, promote the lowest-ID enabled provider.
    if new_default:
        new_default.is_default = True
        logger.info(f"Promoted provider '{new_default.name}' to default after deletion")

    await db.commit()
    logger.info(f"Deleted AI provider id={provider_id}")


@router.post("/providers/{provider_id}/set-default")
async def set_default_provider(
    provider_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin_user),
):
    """Set a provider as the system default."""
    provider = await db.get(AIProvider, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    if provider.is_disabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Disabled provider cannot be set as default",
        )

    if provider.is_default:
        return _serialize_provider(provider)

    # Clear all defaults
    result = await db.execute(select(AIProvider).where(AIProvider.is_default == True))
    for p in result.scalars().all():
        p.is_default = False

    provider.is_default = True
    await db.commit()
    await db.refresh(provider)

    logger.info(f"Set provider '{provider.name}' (id={provider.id}) as default")
    return _serialize_provider(provider)
