"""AI Provider CRUD API endpoints."""

import logging
import re
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config_crypto import decrypt_config_secret, encrypt_config_secret, ConfigEncryptionError
from app.database import get_db
from app.models import AIProvider, Task, TaskStatus

logger = logging.getLogger(__name__)
router = APIRouter()

_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,99}$")


# ── Schemas ────────────────────────────────────────────────────────────────────

class ProviderResponse(BaseModel):
    id: int
    name: str
    base_url: str
    api_key_configured: bool
    model: str
    max_turns: int
    system_prompt: Optional[str]
    is_default: bool
    created_at: str
    updated_at: str


class CreateProviderRequest(BaseModel):
    name: str
    base_url: str
    api_key: Optional[str] = None
    model: str
    max_turns: int = 20
    system_prompt: Optional[str] = None

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
    def validate_system_prompt(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and len(v) > 10000:
            raise ValueError("System prompt must be 10000 characters or fewer")
        return v


class UpdateProviderRequest(BaseModel):
    name: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    clear_api_key: bool = False
    model: Optional[str] = None
    max_turns: Optional[int] = None
    system_prompt: Optional[str] = None
    clear_system_prompt: bool = False

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not _NAME_RE.match(v):
            raise ValueError(
                "Name must be 1-100 characters, alphanumeric/hyphens/underscores, "
                "starting with alphanumeric"
            )
        return v

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.startswith(("http://", "https://")):
            raise ValueError("Base URL must start with http:// or https://")
        return v

    @field_validator("model")
    @classmethod
    def validate_model(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.strip():
            raise ValueError("Model name cannot be empty")
        return v.strip() if v else v

    @field_validator("max_turns")
    @classmethod
    def validate_max_turns(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and (v < 1 or v > 1000):
            raise ValueError("Max turns must be between 1 and 1000")
        return v

    @field_validator("system_prompt")
    @classmethod
    def validate_system_prompt(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and len(v) > 10000:
            raise ValueError("System prompt must be 10000 characters or fewer")
        return v


# ── Helpers ────────────────────────────────────────────────────────────────────

def _serialize_provider(provider: AIProvider) -> dict:
    return {
        "id": provider.id,
        "name": provider.name,
        "base_url": provider.base_url,
        "api_key_configured": provider.api_key is not None and provider.api_key != "",
        "model": provider.model,
        "max_turns": provider.max_turns,
        "system_prompt": provider.system_prompt,
        "is_default": provider.is_default,
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
    return [_serialize_provider(p) for p in providers]


@router.get("/providers/{provider_id}")
async def get_provider(provider_id: int, db: AsyncSession = Depends(get_db)):
    """Get a single AI provider."""
    provider = await db.get(AIProvider, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    return _serialize_provider(provider)


@router.post("/providers", status_code=status.HTTP_201_CREATED)
async def create_provider(
    request: CreateProviderRequest,
    db: AsyncSession = Depends(get_db),
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

    # Encrypt API key if provided
    encrypted_key = None
    if request.api_key:
        try:
            encrypted_key = encrypt_config_secret(request.api_key)
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
        is_default=is_first,
    )
    db.add(provider)
    await db.commit()
    await db.refresh(provider)

    logger.info(f"Created AI provider '{provider.name}' (id={provider.id}, default={provider.is_default})")
    return _serialize_provider(provider)


@router.patch("/providers/{provider_id}")
async def update_provider(
    provider_id: int,
    request: UpdateProviderRequest,
    db: AsyncSession = Depends(get_db),
):
    """Update an existing AI provider."""
    provider = await db.get(AIProvider, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

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

    # Handle API key update/clear
    if request.clear_api_key:
        provider.api_key = None
    elif request.api_key is not None:
        try:
            provider.api_key = encrypt_config_secret(request.api_key)
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
    return _serialize_provider(provider)


@router.delete("/providers/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provider(
    provider_id: int,
    db: AsyncSession = Depends(get_db),
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
    await db.delete(provider)

    # If we deleted the default, promote the lowest-ID remaining provider
    if was_default:
        result = await db.execute(
            select(AIProvider).order_by(AIProvider.id).limit(1)
        )
        new_default = result.scalar_one_or_none()
        if new_default:
            new_default.is_default = True
            logger.info(f"Promoted provider '{new_default.name}' to default after deletion")

    await db.commit()
    logger.info(f"Deleted AI provider id={provider_id}")


@router.post("/providers/{provider_id}/set-default")
async def set_default_provider(
    provider_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Set a provider as the system default."""
    provider = await db.get(AIProvider, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

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
