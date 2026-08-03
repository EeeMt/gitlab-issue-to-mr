"""Pydantic schemas for Task API request/response models."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, StrictInt, field_validator, model_validator

from app.core.scheduling import normalize_scheduled_datetime
from app.core.skills import MAX_SKILLS_PER_TASK
from app.core.task_prompt import MAX_RUN_INSTRUCTION_TEMPLATE_LENGTH
from app.core.utcnow import utcnow

_VALID_TASK_MODES = ("execute", "plan")


def _validate_skill_ids(value: list[int] | None) -> list[int] | None:
    if value is None:
        return None
    if len(value) > MAX_SKILLS_PER_TASK:
        raise ValueError(f"At most {MAX_SKILLS_PER_TASK} skills can be selected")
    if len(set(value)) != len(value):
        raise ValueError("Duplicate skill IDs are not allowed")
    if any(skill_id <= 0 for skill_id in value):
        raise ValueError("Skill IDs must be positive integers")
    return value


class RetryTaskRequest(BaseModel):
    """Optional request body for retrying a task.

    If scheduled_datetime is provided, the task will be retried at that time
    instead of being queued immediately.
    """

    scheduled_datetime: datetime | None = None

    @model_validator(mode="before")
    @classmethod
    def reject_worker_switch(cls, data: Any) -> Any:
        if isinstance(data, dict) and "worker_profile_id" in data:
            raise ValueError("worker_profile_id is fixed by the parent issue")
        return data


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
        provider_id: AI provider ID. Pass ``null`` / ``None`` to restore the
            issue default (or system default when the issue has none). Omit the
            key entirely to leave the current value unchanged.
        require_changes: Whether the task must produce file changes.
            Cannot be null — omit the key to leave unchanged.
        task_mode: Execution mode — 'execute' (default) or 'plan'.
            Cannot be null — omit the key to leave unchanged.
            Setting task_mode='plan' automatically forces require_changes=False.
    """

    user_prompt: str | None = None
    priority: int | None = None
    provider_id: int | None = None
    require_changes: bool | None = None
    task_mode: Literal["execute", "plan"] | None = None
    run_instruction_template: str | None = Field(
        default=None, max_length=MAX_RUN_INSTRUCTION_TEMPLATE_LENGTH
    )
    skill_ids: list[StrictInt] | None = None

    @field_validator("skill_ids")
    @classmethod
    def validate_skill_ids(cls, value: list[int] | None) -> list[int] | None:
        return _validate_skill_ids(value)

    @model_validator(mode="before")
    @classmethod
    def reject_worker_switch(cls, data: Any) -> Any:
        if isinstance(data, dict) and "worker_profile_id" in data:
            raise ValueError("worker_profile_id is fixed by the parent issue")
        return data

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

    @field_validator("run_instruction_template", mode="before")
    @classmethod
    def run_instruction_template_not_null(cls, v: Any) -> Any:
        if v is None:
            raise ValueError(
                "run_instruction_template cannot be null; omit the key to leave it unchanged"
            )
        return v


class CreateTaskRequest(BaseModel):
    """Request model for creating a task under an Issue."""

    issue_id: int
    user_prompt: str | None = None  # If None, uses Issue.description
    priority: int = 0
    delay_seconds: int | None = None
    scheduled_datetime: datetime | None = None
    provider_id: int | None = None
    harness_key: str | None = None  # Omitted -> Profile default
    require_changes: bool | None = False
    task_mode: Literal["execute", "plan"] = "execute"
    session_mode: Literal["continue", "fresh"] = "continue"
    run_instruction_template: str | None = Field(
        default=None, max_length=MAX_RUN_INSTRUCTION_TEMPLATE_LENGTH
    )
    skill_ids: list[StrictInt] | None = None

    @field_validator("skill_ids")
    @classmethod
    def validate_skill_ids(cls, value: list[int] | None) -> list[int] | None:
        return _validate_skill_ids(value)

    @model_validator(mode="before")
    @classmethod
    def reject_worker_switch(cls, data: Any) -> Any:
        if isinstance(data, dict) and "worker_profile_id" in data:
            raise ValueError("worker_profile_id is fixed by the parent issue")
        return data

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
        return self.require_changes if self.require_changes is not None else False


class RunInstructionTemplatePreviewRequest(BaseModel):
    """Prospective task context used to preview a run-instruction template."""

    issue_id: int
    task_mode: Literal["execute", "plan"] = "execute"
    user_prompt: str
    run_instruction_template: str = Field(max_length=MAX_RUN_INSTRUCTION_TEMPLATE_LENGTH)
    require_changes: bool = False
