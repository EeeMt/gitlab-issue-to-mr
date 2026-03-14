"""Database models for the application."""

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum as SQLEnum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for all database models."""

    pass


class TaskStatus(str, Enum):
    """Task status enumeration."""

    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


task_status_enum = SQLEnum(
    TaskStatus,
    name="taskstatus",
    values_callable=lambda enum_cls: [item.value for item in enum_cls],
)


class Task(Base):
    """Task model for storing AI code generation tasks."""

    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # GitLab identifiers
    project_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    issue_iid: Mapped[int] = mapped_column(Integer, nullable=True)
    issue_id: Mapped[int] = mapped_column(Integer, nullable=True)
    note_id: Mapped[int] = mapped_column(Integer, nullable=True, unique=True)

    # Manual task flag
    is_manual: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Task details
    user_prompt: Mapped[str] = mapped_column(Text, nullable=False)

    # Branch and MR info
    branch_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    merge_request_iid: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    merge_request_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    # Status
    status: Mapped[TaskStatus] = mapped_column(
        task_status_enum,
        nullable=False,
        default=TaskStatus.PENDING,
    )

    # Scheduling
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Container tracking
    container_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # Branch configuration
    target_branch: Mapped[str] = mapped_column(String(255), nullable=False, default="main")

    # Results
    commit_sha: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Change statistics
    additions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deletions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_changes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Retry tracking
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Indexes for querying tasks
    __table_args__ = (
        Index("ix_tasks_status_created", "status", "created_at"),
        Index("ix_tasks_status_priority", "status", "priority", "scheduled_at"),
        Index("ix_tasks_project_issue", "project_id", "issue_iid"),
    )


class TaskLog(Base):
    """Task log model for storing execution logs."""

    __tablename__ = "task_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Foreign key to task
    task_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Log content
    log_level: Mapped[str] = mapped_column(String(20), nullable=False, default="INFO")
    message: Mapped[str] = mapped_column(Text, nullable=False)

    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )


class SystemConfig(Base):
    """Persisted runtime configuration overrides."""

    __tablename__ = "system_config"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    value_type: Mapped[str] = mapped_column(String(20), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
