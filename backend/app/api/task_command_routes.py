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

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.task_operations import get_task_with_access_check
from app.core.harness_protocol import normalize_command_id
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

COMMAND_STATUS_TERMINAL = {"delivered", "rejected", "outcome_unknown"}
PUBLIC_COMMAND_TYPES = frozenset({"steer", "follow_up"})
PUBLIC_COMMAND_STATUSES = frozenset(
    {"queued", "dispatching", "delivered", "rejected", "outcome_unknown"}
)

# The persisted reason can come from a container bridge or an exception path.
# It is diagnostic data, not an HTTP contract: never expose it to a task viewer.
PUBLIC_REJECTION_MESSAGES = {
    "existing_conflict": "This command ID is already in use.",
    "task_not_running": "The task is not running.",
    "attempt_mismatch": "The current attempt does not support commands.",
    "unsupported_harness": "The current runtime does not support this command.",
    "control_gate_closed": "The command channel is not accepting commands.",
    "payload_too_large": "The command content exceeds the allowed length.",
    "invalid_command_id": "The command ID format is invalid.",
    "invalid_command_type": "The command type is invalid.",
    "not_authorized": "You are not authorized to send this command.",
    "wrong_attempt": "The command does not belong to the active attempt.",
    "container_unreachable": "Command delivery is temporarily unavailable.",
    "container_missing": "Command delivery is temporarily unavailable.",
    "delivery_outcome_unknown": "The command delivery outcome is unknown.",
}
PUBLIC_FALLBACK_REJECTION_CODE = "command_rejected"
PUBLIC_FALLBACK_REJECTION_MESSAGE = "The command was rejected."
PUBLIC_PROJECTION_ERROR_CODE = "command_projection_unavailable"
PUBLIC_PROJECTION_ERROR_MESSAGE = "Command history is temporarily unavailable."


class ProjectionError(Exception):
    """Raised when persisted command data cannot be safely projected publicly."""

    def __init__(self) -> None:
        # Do not retain the invalid value: this exception may cross an HTTP boundary.
        super().__init__(PUBLIC_PROJECTION_ERROR_CODE)


class CreateCommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = Field(..., pattern="^(steer|follow_up)$")
    # UTF-16 code units, rather than Python code points, are the frozen limit.
    # It is checked through the shared core helper before any DB access below.
    text: str


def _created_by(current_user: User | None) -> str:
    if current_user is None:
        return "anonymous"
    return getattr(current_user, "username", None) or f"user:{current_user.id}"


def _public_rejection(rejection_code: str | None) -> tuple[str | None, str | None]:
    """Return the stable, non-diagnostic rejection projection for viewers."""
    if rejection_code is None:
        return None, None
    message = PUBLIC_REJECTION_MESSAGES.get(rejection_code)
    if message is not None:
        return rejection_code, message
    return PUBLIC_FALLBACK_REJECTION_CODE, PUBLIC_FALLBACK_REJECTION_MESSAGE


def _command_dict(cmd: TaskHarnessCommand) -> dict:
    if not isinstance(cmd.command_type, str) or cmd.command_type not in PUBLIC_COMMAND_TYPES:
        raise ProjectionError()
    if not isinstance(cmd.status, str) or cmd.status not in PUBLIC_COMMAND_STATUSES:
        raise ProjectionError()

    # The terminal state itself is authoritative.  Do not expose a persisted
    # diagnostic (or a missing code) for an unknown delivery outcome.
    rejection_code, rejection_message = _public_rejection(
        "delivery_outcome_unknown" if cmd.status == "outcome_unknown" else cmd.rejection_code
    )
    return {
        "command_id": cmd.command_id,
        "sequence_no": cmd.sequence_no,
        "type": cmd.command_type,
        "status": cmd.status,
        "created_at": cmd.created_at.isoformat() if cmd.created_at else None,
        "dispatch_started_at": cmd.dispatch_started_at.isoformat() if cmd.dispatch_started_at else None,
        "native_ack_at": cmd.native_ack_at.isoformat() if cmd.native_ack_at else None,
        "outcome_unknown_at": cmd.outcome_unknown_at.isoformat() if cmd.outcome_unknown_at else None,
        "delivered_at": cmd.delivered_at.isoformat() if cmd.delivered_at else None,
        "rejected_at": cmd.rejected_at.isoformat() if cmd.rejected_at else None,
        "rejection_code": rejection_code,
        "rejection_message": rejection_message,
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
        "invalid_command_id": status.HTTP_422_UNPROCESSABLE_CONTENT,
        "invalid_command_type": status.HTTP_422_UNPROCESSABLE_CONTENT,
        "not_authorized": status.HTTP_403_FORBIDDEN,
    }
    rejection_code, rejection_message = _public_rejection(result.rejection_code)
    return HTTPException(
        status_code=mapped_status.get(result.rejection_code, status.HTTP_409_CONFLICT),
        detail={
            "code": rejection_code,
            "message": rejection_message,
            "command_id": command_id,
        },
    )


def _projection_http_error() -> HTTPException:
    """Return the stable fail-closed error for unsafe persisted command data."""
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail={
            "code": PUBLIC_PROJECTION_ERROR_CODE,
            "message": PUBLIC_PROJECTION_ERROR_MESSAGE,
        },
    )


@router.put("/tasks/{task_id}/commands/{command_id}")
async def put_command(
    task_id: int,
    command_id: str,
    request: CreateCommandRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_current_user),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    """Idempotently create a queued command (201 created / 200 existing)."""
    command_id = normalize_command_id(command_id)
    if command_id is None:
        # The outer preflight rejects this before any auth/DB work.  Retain a
        # fail-closed guard for direct invocation and future router changes.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "invalid_command_id",
                "message": "The command ID format is invalid.",
            },
        )
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
        rejection_code, rejection_message = _public_rejection(result.rejection_code)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": rejection_code,
                "message": rejection_message,
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
    # Frozen contract: first creation is 201, an idempotent replay is 200.
    response.status_code = status.HTTP_201_CREATED if result.created else status.HTTP_200_OK
    try:
        command = _command_dict(cmd)
    except ProjectionError:
        raise _projection_http_error() from None
    return {"command": command, "created": result.created, "outcome": result.outcome}


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
    try:
        projected = [_command_dict(c) for c in commands]
    except ProjectionError:
        raise _projection_http_error() from None
    return {"commands": projected}


@router.get("/tasks/{task_id}/commands/{command_id}")
async def get_command(
    task_id: int,
    command_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_current_user),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    """Fetch a single command by id (scoped to the task)."""
    command_id = normalize_command_id(command_id)
    if command_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "invalid_command_id",
                "message": "The command ID format is invalid.",
            },
        )
    await get_task_with_access_check(task_id, db, access_scope, current_user)
    cmd = await _load_command(db, task_id=task_id, command_id=command_id)
    if cmd is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="command not found",
        )
    try:
        return _command_dict(cmd)
    except ProjectionError:
        raise _projection_http_error() from None
