"""HTTP surface for the V2 harness command plane.

Implements the frozen REST contract (open-harness-v2-schemas.md §4):
``PUT /tasks/{task_id}/commands/{command_id}`` (idempotent create),
``GET /tasks/{task_id}/commands`` (ordered recovery) and
``GET /tasks/{task_id}/commands/{command_id}``. No update/delete/reorder in
the first release. Creation delegates to ``task_harness_commands.create_command``
so idempotency, digest, sequence allocation and rejection semantics live in one
place and are exercised by the unit tests.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.task_operations import get_task_with_access_check
from app.core.task_harness_commands import (
    CommandCreateResult,
    create_command,
    list_commands,
)
from app.database import get_db
from app.dependencies.auth import get_optional_current_user
from app.dependencies.project_access import (
    ProjectAccessScope,
    require_project_access_scope,
)
from app.models import TaskHarnessCommand, User

logger = logging.getLogger(__name__)
router = APIRouter()

COMMAND_STATUS_TERMINAL = {"delivered", "rejected"}


class CreateCommandRequest(BaseModel):
    type: str = Field(..., pattern="^(steer|follow_up)$")
    text: str = Field(..., max_length=4000)


def _created_by(current_user: User | None) -> str:
    if current_user is None:
        return "anonymous"
    return getattr(current_user, "username", None) or f"user:{current_user.id}"


def _command_dict(cmd: TaskHarnessCommand) -> dict:
    return {
        "command_id": cmd.command_id,
        "task_id": cmd.task_id,
        "attempt_id": cmd.attempt_id,
        "sequence_no": cmd.sequence_no,
        "type": cmd.command_type,
        "payload": cmd.payload,
        "payload_digest": cmd.payload_digest,
        "status": cmd.status,
        "created_by": cmd.created_by,
        "created_at": cmd.created_at.isoformat() if cmd.created_at else None,
        "delivery_attempts": cmd.delivery_attempts,
        "last_attempt_at": cmd.last_attempt_at.isoformat() if cmd.last_attempt_at else None,
        "delivered_at": cmd.delivered_at.isoformat() if cmd.delivered_at else None,
        "rejected_at": cmd.rejected_at.isoformat() if cmd.rejected_at else None,
        "rejection_code": cmd.rejection_code,
        "rejection_message": cmd.rejection_message,
    }


async def _load_command(
    db: AsyncSession, *, task_id: int, command_id: str
) -> TaskHarnessCommand | None:
    return (
        await db.execute(
            select(TaskHarnessCommand)
            .where(
                TaskHarnessCommand.task_id == task_id,
                TaskHarnessCommand.command_id == command_id,
            )
        )
    ).scalar_one_or_none()


def _reject_http(result: CommandCreateResult, *, command_id: str) -> HTTPException:
    mapped_status = {
        "task_not_running": status.HTTP_409_CONFLICT,
        "attempt_mismatch": status.HTTP_409_CONFLICT,
        "unsupported_harness": status.HTTP_409_CONFLICT,
        "control_gate_closed": status.HTTP_409_CONFLICT,
        "payload_too_large": status.HTTP_422_UNPROCESSABLE_CONTENT,
        "invalid_command_type": status.HTTP_422_UNPROCESSABLE_CONTENT,
        "not_authorized": status.HTTP_403_FORBIDDEN,
    }
    return HTTPException(
        status_code=mapped_status.get(result.rejection_code, status.HTTP_409_CONFLICT),
        detail={
            "code": result.rejection_code,
            "message": result.rejection_message,
            "command_id": command_id,
        },
    )


@router.put("/tasks/{task_id}/commands/{command_id}")
async def put_command(
    task_id: int,
    command_id: str,
    request: CreateCommandRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_current_user),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    """Idempotently create a queued command (201 created / 200 existing)."""
    # Access check before mutating; loading the task also anchors task_id.
    await get_task_with_access_check(task_id, db, access_scope, current_user)
    result = await create_command(
        db,
        task_id=task_id,
        command_id=command_id,
        command_type=request.type,
        payload={"text": request.text},
        created_by=_created_by(current_user),
    )
    if result.outcome == "existing_conflict":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "existing_conflict",
                "message": "command_id already exists with a different payload",
                "command_id": command_id,
            },
        )
    if result.rejection_code is not None and not result.created:
        raise _reject_http(result, command_id=command_id)
    await db.commit()
    cmd = await _load_command(db, task_id=task_id, command_id=command_id)
    if cmd is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="command row missing after creation",
        )
    return {
        "command": _command_dict(cmd),
        "created": result.created,
        "outcome": result.outcome,
    }


@router.get("/tasks/{task_id}/commands")
async def get_commands(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_current_user),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    """List a task's commands ordered by attempt/sequence for recovery."""
    await get_task_with_access_check(task_id, db, access_scope, current_user)
    commands = await list_commands(db, task_id=task_id)
    return {"commands": [_command_dict(c) for c in commands]}


@router.get("/tasks/{task_id}/commands/{command_id}")
async def get_command(
    task_id: int,
    command_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_current_user),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    """Fetch a single command by id (scoped to the task)."""
    await get_task_with_access_check(task_id, db, access_scope, current_user)
    cmd = await _load_command(db, task_id=task_id, command_id=command_id)
    if cmd is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="command not found",
        )
    return _command_dict(cmd)
