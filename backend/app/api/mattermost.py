"""Mattermost notification configuration API endpoints."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_effective_settings
from app.core.config_crypto import ConfigEncryptionError
from app.core.mattermost_notifications import (
    MATTERMOST_EVENT_TYPE_SET,
    MATTERMOST_FIELD_KEY_SET,
    MATTERMOST_TARGET_TYPE_CHANNEL,
    MATTERMOST_TARGET_TYPE_INITIATOR_DM,
    MATTERMOST_TARGET_TYPES,
    MattermostClient,
    MattermostNotificationError,
    normalize_string_list,
    serialize_profile,
    serialize_string_list,
    test_mattermost_connection,
)
from app.database import get_db
from app.dependencies.auth import require_admin_user
from app.models import MattermostNotificationProfile
from app.runtime_config import (
    load_runtime_config_from_db,
    reset_runtime_config_override,
    save_runtime_config_override,
)

logger = logging.getLogger(__name__)
router = APIRouter()


class MattermostIntegrationConfigSection(BaseModel):
    """Mattermost integration settings in the config response."""
    mattermost_server_url: str
    mattermost_bot_token_configured: bool


class MattermostIntegrationUpdate(BaseModel):
    """Request model for updating Mattermost integration settings."""
    mattermost_server_url: Optional[str] = None
    mattermost_bot_token: Optional[str] = None
    clear_mattermost_bot_token: bool = False


class MattermostConnectionTestRequest(BaseModel):
    """Request model for testing Mattermost connection."""
    integration: MattermostIntegrationUpdate


class MattermostConnectionTestResponse(BaseModel):
    """Response model for Mattermost connection test."""
    server_url: str
    username: str


class MattermostNotificationProfileResponse(BaseModel):
    """Response model for a Mattermost notification profile."""
    id: int
    name: str
    enabled: bool
    target_type: str
    channel_id: Optional[str] = None
    mention_in_channel: bool
    event_types: list[str]
    field_keys: list[str]
    created_at: datetime
    updated_at: datetime


class MattermostNotificationProfileInput(BaseModel):
    """Request model for creating/updating a Mattermost notification profile."""
    name: str
    enabled: bool = True
    target_type: str
    channel_id: Optional[str] = None
    mention_in_channel: bool = False
    event_types: list[str] = Field(default_factory=list)
    field_keys: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_profile(self) -> "MattermostNotificationProfileInput":
        self.name = self.name.strip()
        self.target_type = self.target_type.strip()
        self.channel_id = self.channel_id.strip() if self.channel_id else None

        if not self.name:
            raise ValueError("Profile name cannot be empty")

        if self.target_type not in MATTERMOST_TARGET_TYPES:
            raise ValueError(f"target_type must be one of: {', '.join(sorted(MATTERMOST_TARGET_TYPES))}")

        self.event_types = normalize_string_list(self.event_types, MATTERMOST_EVENT_TYPE_SET)
        self.field_keys = normalize_string_list(self.field_keys, MATTERMOST_FIELD_KEY_SET)
        if not self.event_types:
            raise ValueError("At least one event type must be selected")
        if not self.field_keys:
            raise ValueError("At least one field must be selected")

        if self.target_type == MATTERMOST_TARGET_TYPE_CHANNEL:
            if not self.channel_id:
                raise ValueError("Channel notifications require channel_id")
        else:
            self.channel_id = None
            self.mention_in_channel = False

        return self


class MattermostResolveChannelRequest(BaseModel):
    """Request model for resolving a channel target by current names."""

    team_name: str
    channel_name: str

    @model_validator(mode="after")
    def validate_payload(self) -> "MattermostResolveChannelRequest":
        self.team_name = self.team_name.strip()
        self.channel_name = self.channel_name.strip()
        if not self.team_name:
            raise ValueError("Mattermost team_name cannot be empty")
        if not self.channel_name:
            raise ValueError("Mattermost channel_name cannot be empty")
        return self


class MattermostChannelTargetResponse(BaseModel):
    """Resolved Mattermost channel target details for UI display."""

    channel_id: str
    team_name: str
    team_display_name: str
    channel_name: str
    channel_display_name: str


def _create_mattermost_client(settings: Settings) -> MattermostClient:
    server_url = settings.mattermost_server_url.strip()
    bot_token = settings.mattermost_bot_token.strip()
    if not server_url or not bot_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Mattermost integration must be configured before resolving channel targets.",
        )
    return MattermostClient(server_url, bot_token)


def _serialize_channel_target(channel: dict[str, Any], team: dict[str, Any]) -> MattermostChannelTargetResponse:
    channel_id = str(channel.get("id", "")).strip()
    team_id = str(channel.get("team_id", "")).strip()
    team_name = str(team.get("name", "")).strip()
    channel_name = str(channel.get("name", "")).strip()
    if not channel_id or not team_id or not team_name or not channel_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Mattermost returned incomplete channel target data.",
        )

    team_display_name = str(team.get("display_name", "")).strip() or team_name
    channel_display_name = str(channel.get("display_name", "")).strip() or channel_name
    return MattermostChannelTargetResponse(
        channel_id=channel_id,
        team_name=team_name,
        team_display_name=team_display_name,
        channel_name=channel_name,
        channel_display_name=channel_display_name,
    )


async def _resolve_channel_target_by_name(payload: MattermostResolveChannelRequest) -> MattermostChannelTargetResponse:
    settings = get_effective_settings()
    client = _create_mattermost_client(settings)
    try:
        channel = await client.get_channel_by_name(payload.team_name, payload.channel_name)
        team_id = str(channel.get("team_id", "")).strip()
        if not team_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Mattermost returned a channel without team_id.",
            )
        team = await client.get_team(team_id)
        return _serialize_channel_target(channel, team)
    except HTTPException:
        raise
    except MattermostNotificationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to resolve Mattermost channel target: {exc}",
        ) from exc
    finally:
        await client.close()


async def _resolve_channel_target_by_id(channel_id: str) -> MattermostChannelTargetResponse:
    normalized_channel_id = channel_id.strip()
    if not normalized_channel_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="channel_id cannot be empty",
        )

    settings = get_effective_settings()
    client = _create_mattermost_client(settings)
    try:
        channel = await client.get_channel(normalized_channel_id)
        team_id = str(channel.get("team_id", "")).strip()
        if not team_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Mattermost returned a channel without team_id.",
            )
        team = await client.get_team(team_id)
        return _serialize_channel_target(channel, team)
    except HTTPException:
        raise
    except MattermostNotificationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to fetch Mattermost channel target: {exc}",
        ) from exc
    finally:
        await client.close()


class MattermostNotificationConfigResponse(BaseModel):
    """Response model for full Mattermost notification config."""
    integration: MattermostIntegrationConfigSection
    profiles: list[MattermostNotificationProfileResponse]


class DeleteResponse(BaseModel):
    """Generic delete response."""
    status: str


def _normalize_updates(updates: dict[str, Any]) -> dict[str, Any]:
    """Normalize and validate config updates before saving."""
    normalized = {}
    for key, value in updates.items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        else:
            normalized[key] = value
    return normalized


async def _serialize_mattermost_notification_config(
    db: AsyncSession,
) -> MattermostNotificationConfigResponse:
    """Serialize Mattermost notification configuration."""
    settings = get_effective_settings()
    result = await db.execute(
        select(MattermostNotificationProfile).order_by(MattermostNotificationProfile.id.asc())
    )
    profiles = result.scalars().all()
    return MattermostNotificationConfigResponse(
        integration=MattermostIntegrationConfigSection(
            mattermost_server_url=settings.mattermost_server_url,
            mattermost_bot_token_configured=bool(settings.mattermost_bot_token),
        ),
        profiles=[
            MattermostNotificationProfileResponse.model_validate(serialize_profile(profile))
            for profile in profiles
        ],
    )


@router.get("/config/notifications", response_model=MattermostNotificationConfigResponse)
async def get_mattermost_notification_config(
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_admin_user),
):
    """Return Mattermost integration settings and notification profiles."""
    await load_runtime_config_from_db(db)
    return await _serialize_mattermost_notification_config(db)


@router.patch("/config/notifications/integration", response_model=MattermostNotificationConfigResponse)
async def update_mattermost_notification_integration(
    request: MattermostIntegrationUpdate,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_admin_user),
):
    """Persist Mattermost integration settings."""
    await load_runtime_config_from_db(db)
    updates = _normalize_updates(request.model_dump(exclude_unset=True))
    clear_bot_token = bool(updates.pop("clear_mattermost_bot_token", False))

    try:
        for key, value in updates.items():
            await save_runtime_config_override(db, key, value)
            logger.info("Updated Mattermost config %s", key)

        if clear_bot_token and "mattermost_bot_token" not in updates:
            await reset_runtime_config_override(db, "mattermost_bot_token")
            logger.info("Cleared stored Mattermost bot token")

        await load_runtime_config_from_db(db)
    except ConfigEncryptionError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    return await _serialize_mattermost_notification_config(db)


@router.post("/config/notifications/test", response_model=MattermostConnectionTestResponse)
async def test_mattermost_notification_integration(
    request: MattermostConnectionTestRequest,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_admin_user),
):
    """Validate Mattermost connectivity with current or unsaved values."""
    import httpx
    from app.core.mattermost_notifications import test_mattermost_connection

    await load_runtime_config_from_db(db)
    updates = _normalize_updates(request.integration.model_dump(exclude_unset=True))
    clear_bot_token = bool(updates.pop("clear_mattermost_bot_token", False))
    settings = get_effective_settings()

    try:
        result = await test_mattermost_connection(
            server_url=str(updates.get("mattermost_server_url", settings.mattermost_server_url)),
            bot_token=(
                str(updates["mattermost_bot_token"])
                if "mattermost_bot_token" in updates
                else ("" if clear_bot_token else settings.mattermost_bot_token)
            ),
        )
    except (MattermostNotificationError, httpx.HTTPError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Mattermost config test failed: {exc}",
        ) from exc

    return MattermostConnectionTestResponse(**result)


@router.post("/config/notifications/channel-targets/resolve", response_model=MattermostChannelTargetResponse)
async def resolve_mattermost_channel_target(
    payload: MattermostResolveChannelRequest,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_admin_user),
):
    """Resolve a Mattermost channel target from team/channel names."""

    await load_runtime_config_from_db(db)
    return await _resolve_channel_target_by_name(payload)


@router.get("/config/notifications/channel-targets/{channel_id}", response_model=MattermostChannelTargetResponse)
async def get_mattermost_channel_target(
    channel_id: str,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_admin_user),
):
    """Fetch the current Mattermost team/channel names for a stored channel_id."""

    await load_runtime_config_from_db(db)
    return await _resolve_channel_target_by_id(channel_id)


@router.post("/config/notifications/profiles", response_model=MattermostNotificationProfileResponse)
async def create_mattermost_notification_profile(
    payload: MattermostNotificationProfileInput,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_admin_user),
):
    """Create a Mattermost notification profile."""
    profile = MattermostNotificationProfile(
        name=payload.name,
        enabled=payload.enabled,
        target_type=payload.target_type,
        channel_id=payload.channel_id,
        mention_in_channel=payload.mention_in_channel,
        event_types_json=serialize_string_list(payload.event_types),
        field_keys_json=serialize_string_list(payload.field_keys),
    )
    db.add(profile)
    await db.commit()
    await db.refresh(profile)
    logger.info("Created Mattermost notification profile %s", profile.id)
    return MattermostNotificationProfileResponse.model_validate(serialize_profile(profile))


@router.patch("/config/notifications/profiles/{profile_id}", response_model=MattermostNotificationProfileResponse)
async def update_mattermost_notification_profile(
    profile_id: int,
    payload: MattermostNotificationProfileInput,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_admin_user),
):
    """Update one Mattermost notification profile."""
    profile = await db.get(MattermostNotificationProfile, profile_id)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Mattermost notification profile {profile_id} not found",
        )

    profile.name = payload.name
    profile.enabled = payload.enabled
    profile.target_type = payload.target_type
    profile.channel_id = payload.channel_id
    profile.mention_in_channel = payload.mention_in_channel
    profile.event_types_json = serialize_string_list(payload.event_types)
    profile.field_keys_json = serialize_string_list(payload.field_keys)
    await db.commit()
    await db.refresh(profile)
    logger.info("Updated Mattermost notification profile %s", profile.id)
    return MattermostNotificationProfileResponse.model_validate(serialize_profile(profile))


@router.delete("/config/notifications/profiles/{profile_id}", response_model=DeleteResponse)
async def delete_mattermost_notification_profile(
    profile_id: int,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_admin_user),
):
    """Delete one Mattermost notification profile."""
    profile = await db.get(MattermostNotificationProfile, profile_id)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Mattermost notification profile {profile_id} not found",
        )
    await db.delete(profile)
    await db.commit()
    logger.info("Deleted Mattermost notification profile %s", profile_id)
    return DeleteResponse(status="success")
