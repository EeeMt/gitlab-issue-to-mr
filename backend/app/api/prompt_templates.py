"""Prompt template API endpoints."""

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies.auth import require_admin_user
from app.models import PromptTemplate

logger = logging.getLogger(__name__)
router = APIRouter()


# Request/Response models
class PromptTemplateCreate(BaseModel):
    name: str
    content: str
    is_active: bool = True


class PromptTemplateUpdate(BaseModel):
    name: Optional[str] = None
    content: Optional[str] = None
    is_active: Optional[bool] = None


class PromptTemplateResponse(BaseModel):
    id: int
    name: str
    content: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class DeleteResponse(BaseModel):
    status: str


@router.get("/prompt-templates", response_model=list[PromptTemplateResponse])
async def list_prompt_templates(
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_admin_user),
):
    """List all prompt templates."""
    result = await db.execute(
        select(PromptTemplate).order_by(PromptTemplate.created_at.desc())
    )
    templates = result.scalars().all()
    return [
        PromptTemplateResponse(
            id=t.id,
            name=t.name,
            content=t.content,
            is_active=t.is_active,
            created_at=t.created_at,
            updated_at=t.updated_at,
        )
        for t in templates
    ]


@router.post("/prompt-templates", response_model=PromptTemplateResponse, status_code=status.HTTP_201_CREATED)
async def create_prompt_template(
    template: PromptTemplateCreate,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_admin_user),
):
    """Create a new prompt template."""
    db_template = PromptTemplate(
        name=template.name,
        content=template.content,
        is_active=template.is_active,
    )
    db.add(db_template)
    await db.commit()
    await db.refresh(db_template)
    return PromptTemplateResponse(
        id=db_template.id,
        name=db_template.name,
        content=db_template.content,
        is_active=db_template.is_active,
        created_at=db_template.created_at,
        updated_at=db_template.updated_at,
    )


@router.get("/prompt-templates/{template_id}", response_model=PromptTemplateResponse)
async def get_prompt_template(
    template_id: int,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_admin_user),
):
    """Get a single prompt template by ID."""
    result = await db.execute(
        select(PromptTemplate).where(PromptTemplate.id == template_id)
    )
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Prompt template {template_id} not found",
        )
    return PromptTemplateResponse(
        id=template.id,
        name=template.name,
        content=template.content,
        is_active=template.is_active,
        created_at=template.created_at,
        updated_at=template.updated_at,
    )


@router.put("/prompt-templates/{template_id}", response_model=PromptTemplateResponse)
async def update_prompt_template(
    template_id: int,
    update: PromptTemplateUpdate,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_admin_user),
):
    """Update a prompt template."""
    result = await db.execute(
        select(PromptTemplate).where(PromptTemplate.id == template_id)
    )
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Prompt template {template_id} not found",
        )

    if update.name is not None:
        template.name = update.name
    if update.content is not None:
        template.content = update.content
    if update.is_active is not None:
        template.is_active = update.is_active

    await db.commit()
    await db.refresh(template)
    return PromptTemplateResponse(
        id=template.id,
        name=template.name,
        content=template.content,
        is_active=template.is_active,
        created_at=template.created_at,
        updated_at=template.updated_at,
    )


@router.delete("/prompt-templates/{template_id}", response_model=DeleteResponse)
async def delete_prompt_template(
    template_id: int,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_admin_user),
):
    """Delete a prompt template."""
    result = await db.execute(
        select(PromptTemplate).where(PromptTemplate.id == template_id)
    )
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Prompt template {template_id} not found",
        )

    await db.delete(template)
    await db.commit()
    return DeleteResponse(status="success")
