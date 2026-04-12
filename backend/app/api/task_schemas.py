"""Pydantic schemas for Task API request/response models."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, model_validator

from app.core.scheduling import normalize_scheduled_datetime
from app.core.utcnow import utcnow


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


class CreateTaskRequest(BaseModel):
    """Request model for creating a task under an Issue."""

    issue_id: int
    user_prompt: Optional[str] = None  # If None, uses Issue.description
    priority: int = 0
    delay_seconds: Optional[int] = None
    scheduled_datetime: Optional[datetime] = None

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
