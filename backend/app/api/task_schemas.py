"""Pydantic schemas for Task API request/response models."""

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, field_validator, model_validator

from app.core.scheduling import normalize_scheduled_datetime
from app.core.utcnow import utcnow

_VALID_TASK_MODES = ("execute", "plan")


class RetryTaskRequest(BaseModel):
    """Optional request body for retrying a task.

    If scheduled_datetime is provided, the task will be retried at that time
    instead of being queued immediately.
    """

    scheduled_datetime: Optional[datetime] = None


class RescheduleTaskRequest(BaseModel):
    """Request model for updating an existing task's scheduled time."""

    scheduled_datetime: datetime

    @model_validator(mode="after")
    def validate_schedule_is_future(self) -> "RescheduleTaskRequest":
        normalized_scheduled = normalize_scheduled_datetime(self.scheduled_datetime)
        if normalized_scheduled is None or normalized_scheduled <= utcnow():
            raise ValueError("Scheduled datetime must be in the future for manual tasks")
        return self


class UpdateTaskRequest(BaseModel):
    """Request model for updating a pending/queued task's editable fields.

    Only fields explicitly included in the request body are applied.
    Use ``model_fields_set`` to distinguish "not provided" from "explicitly null".

    Fields:
        user_prompt: New prompt text. Must be non-empty if provided.
            Cannot be null — omit the key to leave unchanged.
        priority: Task priority (0 = low, 1 = normal, 2 = high).
        provider_id: AI provider ID. Pass ``null`` / ``None`` to clear the
            provider (revert to system default).  Omit the key entirely to
            leave the current value unchanged.
        require_changes: Whether the task must produce file changes.
            Cannot be null — omit the key to leave unchanged.
        task_mode: Execution mode — 'execute' (default) or 'plan'.
            Cannot be null — omit the key to leave unchanged.
            Setting task_mode='plan' automatically forces require_changes=False.
    """

    user_prompt: Optional[str] = None
    priority: Optional[int] = None
    provider_id: Optional[int] = None  # None = system default / clear
    require_changes: Optional[bool] = None
    task_mode: Optional[Literal["execute", "plan"]] = None

    @field_validator("user_prompt", mode="before")
    @classmethod
    def user_prompt_not_null(cls, v: Any) -> Any:
        if v is None:
            raise ValueError("user_prompt cannot be null; omit the key to leave it unchanged")
        return v

    @field_validator("require_changes", mode="before")
    @classmethod
    def require_changes_not_null(cls, v: Any) -> Any:
        if v is None:
            raise ValueError("require_changes cannot be null; omit the key to leave it unchanged")
        return v

    @field_validator("task_mode", mode="before")
    @classmethod
    def task_mode_not_null(cls, v: Any) -> Any:
        if v is None:
            raise ValueError("task_mode cannot be null; omit the key to leave it unchanged")
        return v


class CreateTaskRequest(BaseModel):
    """Request model for creating a task under an Issue."""

    issue_id: int
    user_prompt: Optional[str] = None  # If None, uses Issue.description
    priority: int = 0
    delay_seconds: Optional[int] = None
    scheduled_datetime: Optional[datetime] = None
    provider_id: int
    require_changes: Optional[bool] = True
    task_mode: Literal["execute", "plan"] = "execute"

    @model_validator(mode="after")
    def validate_schedule_is_future(self) -> "CreateTaskRequest":
        """Tasks can only be scheduled in the future."""
        if self.delay_seconds is not None and self.delay_seconds <= 0:
            raise ValueError("Delay seconds must be greater than 0")

        if self.scheduled_datetime is None:
            return self

        normalized_scheduled = normalize_scheduled_datetime(self.scheduled_datetime)
        if normalized_scheduled is not None and normalized_scheduled <= utcnow():
            raise ValueError("Scheduled datetime must be in the future")

        return self

    @property
    def effective_require_changes(self) -> bool:
        """Plan mode never requires code changes."""
        if self.task_mode == "plan":
            return False
        return self.require_changes if self.require_changes is not None else True
