"""Global Claude Code skill management API."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.skills import (
    MAX_SKILL_FILE_BASE64_LENGTH,
    MAX_SKILL_FILE_PATH_LENGTH,
    MAX_SKILL_FILES,
    MAX_SKILL_MARKDOWN_LENGTH,
    SkillValidationError,
    acquire_worker_profile_skill_package_lock,
    build_skill_download_archive,
    build_skill_version,
    delete_unreferenced_skill_versions,
    validate_worker_profile_skill_package_limits,
)
from app.database import get_db
from app.dependencies.auth import require_admin_user
from app.models import Skill, SkillVersion

router = APIRouter()


class SkillFilePayload(BaseModel):
    path: str = Field(max_length=MAX_SKILL_FILE_PATH_LENGTH)
    content_base64: str = Field(max_length=MAX_SKILL_FILE_BASE64_LENGTH)
    executable: bool = False


class SkillCreateRequest(BaseModel):
    name: str = Field(max_length=64)
    skill_md: str = Field(max_length=MAX_SKILL_MARKDOWN_LENGTH)
    files: list[SkillFilePayload] = Field(default_factory=list, max_length=MAX_SKILL_FILES)
    enabled: bool = True


class SkillUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=64)
    skill_md: str | None = Field(default=None, max_length=MAX_SKILL_MARKDOWN_LENGTH)
    files: list[SkillFilePayload] = Field(default_factory=list, max_length=MAX_SKILL_FILES)
    enabled: bool | None = None


class SkillSummaryResponse(BaseModel):
    id: int
    name: str
    description: str
    enabled: bool
    created_at: datetime
    updated_at: datetime


class SkillResponse(SkillSummaryResponse):
    skill_md: str
    files: list[SkillFilePayload]


class SkillOptionResponse(BaseModel):
    id: int
    name: str
    description: str
    version_id: int


def _skill_response(skill: Skill) -> SkillResponse:
    version = skill.current_version
    return SkillResponse(
        id=skill.id,
        name=skill.name,
        description=skill.description,
        skill_md=version.skill_md,
        files=[SkillFilePayload(**item) for item in version.files],
        enabled=skill.enabled,
        created_at=skill.created_at,
        updated_at=skill.updated_at,
    )


def _skill_summary_response(skill: Skill) -> SkillSummaryResponse:
    return SkillSummaryResponse(
        id=skill.id,
        name=skill.name,
        description=skill.description,
        enabled=skill.enabled,
        created_at=skill.created_at,
        updated_at=skill.updated_at,
    )


def _skill_http_error(exc: SkillValidationError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))


async def _skill_or_404(
    db: AsyncSession,
    skill_id: int,
    *,
    for_update: bool = False,
    include_package: bool = False,
) -> Skill:
    query = select(Skill).where(Skill.id == skill_id)
    if include_package:
        query = query.options(
            selectinload(Skill.current_version)
            .undefer(SkillVersion.skill_md)
            .undefer(SkillVersion.files)
        )
    if for_update:
        query = query.with_for_update()
    skill = (await db.execute(query)).scalar_one_or_none()
    if skill is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill not found")
    return skill


async def _commit_or_name_conflict(db: AsyncSession, name: str) -> None:
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Skill with name '{name}' already exists",
        ) from exc


async def _commit_skill_update_or_name_conflict(db: AsyncSession, name: str) -> None:
    try:
        await db.flush()
        await delete_unreferenced_skill_versions(db)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Skill with name '{name}' already exists",
        ) from exc


@router.get("/skills", response_model=list[SkillOptionResponse])
async def list_enabled_skills(db: AsyncSession = Depends(get_db)):
    """List lightweight options available for new task selections."""
    result = await db.execute(
        select(Skill.id, Skill.name, Skill.description, Skill.current_version_id)
        .where(Skill.enabled.is_(True))
        .order_by(Skill.name.asc())
    )
    return [
        SkillOptionResponse(
            id=skill_id,
            name=name,
            description=description,
            version_id=version_id,
        )
        for skill_id, name, description, version_id in result.all()
    ]


@router.get("/skills/admin", response_model=list[SkillSummaryResponse])
async def list_all_skills(
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_admin_user),
):
    result = await db.execute(select(Skill).order_by(Skill.name.asc()))
    return [_skill_summary_response(skill) for skill in result.scalars().all()]


@router.get("/skills/{skill_id}/admin", response_model=SkillResponse)
async def get_skill_for_admin(
    skill_id: int,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_admin_user),
):
    return _skill_response(await _skill_or_404(db, skill_id, include_package=True))


@router.get("/skills/{skill_id}/download", response_class=Response)
async def download_skill(
    skill_id: int,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_admin_user),
) -> Response:
    """Download the current immutable Skill package as a ZIP archive."""
    skill = await _skill_or_404(db, skill_id, include_package=True)
    try:
        archive = build_skill_download_archive(
            name=skill.name,
            skill_md=skill.current_version.skill_md,
            files=skill.current_version.files,
        )
    except SkillValidationError as exc:
        raise _skill_http_error(exc) from exc
    return Response(
        content=archive,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{skill.name}.zip"',
            "Cache-Control": "no-store",
        },
    )


@router.post("/skills", response_model=SkillResponse, status_code=status.HTTP_201_CREATED)
async def create_skill(
    request: SkillCreateRequest,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_admin_user),
):
    try:
        version = build_skill_version(
            name=request.name,
            skill_md=request.skill_md,
            files=(file.model_dump() for file in request.files),
        )
        skill = Skill(
            name=version.name,
            description=version.description,
            current_version=version,
            enabled=request.enabled,
        )
    except SkillValidationError as exc:
        raise _skill_http_error(exc) from exc
    db.add(skill)
    await _commit_or_name_conflict(db, skill.name)
    return _skill_response(await _skill_or_404(db, skill.id, include_package=True))


@router.patch("/skills/{skill_id}", response_model=SkillResponse)
async def update_skill(
    skill_id: int,
    request: SkillUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_admin_user),
):
    await acquire_worker_profile_skill_package_lock(db)
    skill = await _skill_or_404(db, skill_id, for_update=True, include_package=True)
    fields = request.model_fields_set
    try:
        current = skill.current_version
        version = build_skill_version(
            name=(request.name if "name" in fields and request.name is not None else current.name),
            skill_md=(
                request.skill_md
                if "skill_md" in fields and request.skill_md is not None
                else current.skill_md
            ),
            files=(
                (file.model_dump() for file in request.files)
                if "files" in fields
                else current.files
            ),
        )
        next_enabled = (
            request.enabled
            if "enabled" in fields and request.enabled is not None
            else skill.enabled
        )
        if next_enabled and (version.digest != current.digest or not skill.enabled):
            await validate_worker_profile_skill_package_limits(
                db,
                skill,
                version,
                target_enabled=True,
            )
        if version.digest != current.digest:
            db.add(version)
            skill.current_version = version
        skill.name = version.name
        skill.description = version.description
        if "enabled" in fields and request.enabled is not None:
            skill.enabled = request.enabled
    except SkillValidationError as exc:
        await db.rollback()
        raise _skill_http_error(exc) from exc
    await _commit_skill_update_or_name_conflict(db, skill.name)
    return _skill_response(skill)


@router.post("/skills/{skill_id}/disable", response_model=SkillSummaryResponse)
async def disable_skill(
    skill_id: int,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_admin_user),
):
    skill = await _skill_or_404(db, skill_id, for_update=True)
    skill.enabled = False
    await db.commit()
    return _skill_summary_response(skill)


@router.post("/skills/{skill_id}/enable", response_model=SkillSummaryResponse)
async def enable_skill(
    skill_id: int,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_admin_user),
):
    await acquire_worker_profile_skill_package_lock(db)
    skill = await _skill_or_404(db, skill_id, for_update=True, include_package=True)
    try:
        await validate_worker_profile_skill_package_limits(
            db,
            skill,
            skill.current_version,
            target_enabled=True,
        )
        skill.enabled = True
    except SkillValidationError as exc:
        await db.rollback()
        raise _skill_http_error(exc) from exc
    await db.commit()
    return _skill_summary_response(skill)


@router.delete("/skills/{skill_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_skill(
    skill_id: int,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_admin_user),
) -> None:
    skill = await _skill_or_404(db, skill_id, for_update=True)
    await db.delete(skill)
    await db.flush()
    await delete_unreferenced_skill_versions(db)
    await db.commit()
