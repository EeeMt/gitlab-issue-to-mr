"""Database models for the application."""

from datetime import date, datetime
from enum import Enum
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy import (
    Enum as SQLEnum,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.core.utcnow import utcnow


class Base(DeclarativeBase):
    """Base class for all database models."""

    pass


class IssueStatus(str, Enum):
    """Issue status enumeration."""

    OPEN = "open"
    IN_PROGRESS = "in_progress"
    IN_REVIEW = "in_review"
    CLOSED = "closed"


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


class Issue(Base):
    """Issue model — requirement container that groups Tasks. One Issue = one branch + one MR."""

    __tablename__ = "issues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    project_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), default=IssueStatus.OPEN.value, nullable=False)
    closed_via: Mapped[str | None] = mapped_column(String(30), nullable=True)

    # Branch & MR (promoted from Task)
    branch_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    base_branch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    target_branch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Branch deletion policy
    delete_branch_on_close: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true"), nullable=False
    )
    branch_deleted: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    merge_request_iid: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    merge_request_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    ci_auto_repair_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    worker_profile_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("worker_profiles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    default_provider_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("ai_providers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Repository bootstrap policy. ``None`` keeps the existing full-clone behavior.
    git_clone_depth: Mapped[int | None] = mapped_column(Integer, nullable=True)
    git_clone_filter: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Claude session persistence
    claude_session_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    session_storage_path: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # The workspace lives on the Issue's pinned Docker daemon. These fields let the
    # scheduler drive cleanup from database state instead of scanning a shared filesystem.
    workspace_last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    workspace_delete_attempted_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    workspace_deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    workspace_delete_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Creator
    initiator_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    initiator_username: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )

    # Relationships
    tasks: Mapped[list["Task"]] = relationship(
        "Task",
        back_populates="issue",
        order_by="Task.created_at",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    worker_profile: Mapped["WorkerProfile"] = relationship(
        "WorkerProfile",
        foreign_keys=[worker_profile_id],
    )
    default_provider: Mapped["AIProvider | None"] = relationship(
        "AIProvider",
        foreign_keys=[default_provider_id],
        back_populates="default_for_issues",
    )

    __table_args__ = (
        CheckConstraint(
            "git_clone_depth IS NULL OR git_clone_depth BETWEEN 1 AND 10000",
            name="ck_issues_git_clone_depth",
        ),
        CheckConstraint(
            "git_clone_filter IS NULL OR git_clone_filter = 'blob:none'",
            name="ck_issues_git_clone_filter",
        ),
        Index("ix_issues_status_created", "status", "created_at"),
        Index("ix_issues_project_status", "project_id", "status"),
    )


class AIProvider(Base):
    """Named AI provider configuration."""

    __tablename__ = "ai_providers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    api_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    max_turns: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_disabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )

    tasks: Mapped[list["Task"]] = relationship("Task", back_populates="provider")
    default_for_issues: Mapped[list["Issue"]] = relationship(
        "Issue",
        back_populates="default_provider",
        foreign_keys="Issue.default_provider_id",
    )


class Task(Base):
    """Task model — one execution unit (one `claude -p` call). Belongs to an Issue."""

    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Parent issue
    issue_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("issues.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    # AI Provider
    provider_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("ai_providers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    worker_profile_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("worker_profiles.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Task details
    user_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    run_instruction_template: Mapped[str | None] = mapped_column(Text, nullable=True)
    rendered_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    rendered_prompt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    session_mode: Mapped[str] = mapped_column(
        String(16), default="continue", server_default=text("'continue'"), nullable=False
    )
    input_session_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    output_session_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_runtime_snapshot: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        deferred=True,
    )
    worker_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    initiator_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    initiator_gitlab_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    initiator_username: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    initiator_display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    initiator_email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Retry tracking
    is_retry: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    retry_source_task_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True
    )
    trigger_source: Mapped[str] = mapped_column(
        String(32), default="manual", server_default=text("'manual'"), nullable=False, index=True
    )
    ci_failure_run_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("ci_failure_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Status
    status: Mapped[TaskStatus] = mapped_column(
        task_status_enum,
        nullable=False,
        default=TaskStatus.PENDING,
    )

    # Scheduling
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)

    # Container tracking
    container_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Results
    commit_sha: Mapped[str | None] = mapped_column(String(40), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Change statistics
    additions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deletions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_changes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Token usage (populated from Claude CLI output)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Require code changes for success (relevant when issue has target_branch)
    require_changes: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Execution mode: 'execute' (default) makes code changes; 'plan' only analyses and outputs a proposal
    task_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="execute")

    # AI model used for this task (populated from structured system_init events)
    model_name: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # MR title generated by AI post-execution (populated from structured finalization events)
    commit_message: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # Manual status override
    is_manually_overridden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    overridden_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    overridden_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    raw_logs_finalized_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Relationships
    issue: Mapped["Issue"] = relationship("Issue", back_populates="tasks")
    retry_source: Mapped[Optional["Task"]] = relationship(
        "Task", remote_side="Task.id", foreign_keys=[retry_source_task_id]
    )
    provider: Mapped[Optional["AIProvider"]] = relationship("AIProvider", back_populates="tasks")
    worker_profile: Mapped["WorkerProfile | None"] = relationship(
        "WorkerProfile",
        foreign_keys=[worker_profile_id],
    )
    worker_profile_snapshot: Mapped["TaskWorkerProfileSnapshot | None"] = relationship(
        "TaskWorkerProfileSnapshot",
        back_populates="task",
        uselist=False,
        cascade="all, delete-orphan",
    )
    ci_failure_run: Mapped[Optional["CIFailureRun"]] = relationship(
        "CIFailureRun",
        foreign_keys=[ci_failure_run_id],
        back_populates="repair_tasks",
    )

    # Indexes for querying tasks
    __table_args__ = (
        Index("ix_tasks_status_created", "status", "created_at"),
        Index("ix_tasks_status_priority", "status", "priority", "scheduled_at"),
        Index("ix_tasks_issue_id_status", "issue_id", "status"),
        Index("ix_tasks_issue_trigger_source", "issue_id", "trigger_source"),
        Index("ix_tasks_created_at_project", "created_at", "project_id"),
        Index("ix_tasks_created_at_status", "created_at", "status"),
    )


class IssueExecutionLock(Base):
    """Authoritative lock ensuring only one task per issue executes at a time."""

    __tablename__ = "issue_execution_locks"

    issue_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("issues.id", ondelete="CASCADE"),
        primary_key=True,
    )
    task_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    acquired_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=utcnow,
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


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

    # Structured log support: log_type distinguishes plain output from structured entries.
    # Supported types: 'thinking', 'assistant_text', 'tool_call', 'context_compact', 'system_init'.
    log_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    log_metadata: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow
    )


class UsageLimitPolicy(Base):
    """Quota policy row for system defaults or per-user overrides."""

    __tablename__ = "usage_limit_policies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    daily_tokens_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="custom")
    daily_tokens_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    weekly_tokens_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="custom")
    weekly_tokens_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    daily_tasks_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="custom")
    daily_tasks_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    weekly_tasks_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="custom")
    weekly_tasks_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        UniqueConstraint("user_id", name="uq_usage_limit_policies_user_id"),
        Index(
            "uq_usage_limit_policies_system_default",
            "scope_type",
            unique=True,
            postgresql_where=text("scope_type = 'system_default' AND user_id IS NULL"),
            sqlite_where=text("scope_type = 'system_default' AND user_id IS NULL"),
        ),
    )


class TaskUsageLedger(Base):
    """Task-level usage row used for daily and weekly quota aggregation."""

    __tablename__ = "task_usage_ledger"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    task_status: Mapped[str] = mapped_column(String(32), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    timezone_day: Mapped[date] = mapped_column(Date, nullable=False)
    timezone_week_start: Mapped[date] = mapped_column(Date, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    task_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        UniqueConstraint("task_id", name="uq_task_usage_ledger_task_id"),
        CheckConstraint("task_count = 1", name="ck_task_usage_ledger_task_count_is_one"),
        Index("ix_task_usage_ledger_completed_at", "completed_at"),
        Index("ix_task_usage_ledger_user_day", "user_id", "timezone_day"),
        Index("ix_task_usage_ledger_user_week", "user_id", "timezone_week_start"),
    )


class SystemConfig(Base):
    """Persisted runtime configuration overrides."""

    __tablename__ = "system_config"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    value_type: Mapped[str] = mapped_column(String(20), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )


class WorkerEnvironmentVariable(Base):
    """Persisted custom environment variable injected into worker containers."""

    __tablename__ = "worker_environment_variables"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(255), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    is_secret: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        Index("ix_worker_environment_variables_key", "key", unique=True),
    )


class WorkerProfile(Base):
    """Editable worker runtime profile."""

    __tablename__ = "worker_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    image: Mapped[str] = mapped_column(String(255), nullable=False)
    runtime_mode: Mapped[str] = mapped_column(
        String(32), nullable=False, default="baked_image"
    )
    worker_kit_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    worker_kit_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    docker_host: Mapped[str | None] = mapped_column(String(500), nullable=True)
    docker_tls_ca: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    docker_tls_cert: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    docker_tls_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    codegraph_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    volume_mounts: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    pre_script: Mapped[str] = mapped_column(Text, nullable=False, default="")
    post_script: Mapped[str] = mapped_column(Text, nullable=False, default="")
    default_execute_run_instruction_template: Mapped[str] = mapped_column(Text, nullable=False)
    default_plan_run_instruction_template: Mapped[str] = mapped_column(Text, nullable=False)
    ci_auto_repair_run_instruction_template: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
    )

    environment_variables: Mapped[list["WorkerProfileEnvironmentVariable"]] = relationship(
        "WorkerProfileEnvironmentVariable",
        back_populates="profile",
        cascade="all, delete-orphan",
    )
    default_skills: Mapped[list["Skill"]] = relationship(
        "Skill",
        secondary="worker_profile_skills",
        back_populates="worker_profiles",
        order_by="Skill.name",
    )

    __table_args__ = (
        Index(
            "uq_worker_profiles_default",
            "is_default",
            unique=True,
            postgresql_where=text("is_default = true"),
            sqlite_where=text("is_default = true"),
        ),
    )


class SkillVersion(Base):
    """Immutable, task-referenceable contents of one Claude Code skill package."""

    __tablename__ = "skill_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    skill_md: Mapped[str] = mapped_column(Text, nullable=False, deferred=True)
    files: Mapped[list[dict[str, object]]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        server_default=text("'[]'"),
        deferred=True,
    )
    package_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    digest: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class Skill(Base):
    """Administrator-managed identity and current version of a Claude Code skill."""

    __tablename__ = "skills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    current_version_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("skill_versions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
    )
    current_version: Mapped["SkillVersion"] = relationship("SkillVersion", lazy="raise")

    worker_profiles: Mapped[list["WorkerProfile"]] = relationship(
        "WorkerProfile",
        secondary="worker_profile_skills",
        back_populates="default_skills",
    )


class WorkerProfileSkill(Base):
    """Many-to-many assignment of default skills to a worker profile."""

    __tablename__ = "worker_profile_skills"

    worker_profile_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("worker_profiles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    skill_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("skills.id", ondelete="CASCADE"),
        primary_key=True,
    )

    __table_args__ = (Index("ix_worker_profile_skills_skill_id", "skill_id"),)


class TaskSkillVersionReference(Base):
    """Ordered immutable Skill version selected for one task snapshot."""

    __tablename__ = "task_skill_version_references"

    task_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("task_worker_profile_snapshots.task_id", ondelete="CASCADE"),
        primary_key=True,
    )
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    skill_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("skills.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    skill_version_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("skill_versions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    snapshot: Mapped["TaskWorkerProfileSnapshot"] = relationship(
        "TaskWorkerProfileSnapshot",
        back_populates="skill_references",
    )

    __table_args__ = (
        CheckConstraint("position >= 0", name="ck_task_skill_version_reference_position"),
    )


class WorkerProfileEnvironmentVariable(Base):
    """Custom environment variable scoped to one worker profile."""

    __tablename__ = "worker_profile_environment_variables"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    worker_profile_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("worker_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    key: Mapped[str] = mapped_column(String(255), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    is_secret: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
    )

    profile: Mapped[WorkerProfile] = relationship(
        "WorkerProfile",
        back_populates="environment_variables",
    )

    __table_args__ = (
        Index("uq_worker_profile_environment_key", "worker_profile_id", "key", unique=True),
    )


class TaskWorkerProfileSnapshot(Base):
    """Task-level immutable worker runtime configuration snapshot."""

    __tablename__ = "task_worker_profile_snapshots"

    task_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("tasks.id", ondelete="CASCADE"),
        primary_key=True,
    )
    worker_profile_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("worker_profiles.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    profile_name: Mapped[str] = mapped_column(String(100), nullable=False)
    image: Mapped[str] = mapped_column(String(255), nullable=False)
    runtime_mode: Mapped[str] = mapped_column(
        String(32), nullable=False, default="baked_image"
    )
    worker_kit_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    worker_kit_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    docker_host: Mapped[str | None] = mapped_column(String(500), nullable=True)
    docker_tls_ca: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    docker_tls_cert: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    docker_tls_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    codegraph_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    volume_mounts: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    environment_variables: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    skill_selection_source: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="profile",
        server_default=text("'profile'"),
    )
    pre_script: Mapped[str] = mapped_column(Text, nullable=False, default="")
    post_script: Mapped[str] = mapped_column(Text, nullable=False, default="")
    default_execute_run_instruction_template: Mapped[str] = mapped_column(Text, nullable=False)
    default_plan_run_instruction_template: Mapped[str] = mapped_column(Text, nullable=False)
    ci_auto_repair_run_instruction_template: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
    )

    task: Mapped[Task] = relationship("Task", back_populates="worker_profile_snapshot")
    worker_profile: Mapped[WorkerProfile | None] = relationship("WorkerProfile")
    skill_references: Mapped[list[TaskSkillVersionReference]] = relationship(
        "TaskSkillVersionReference",
        back_populates="snapshot",
        order_by="TaskSkillVersionReference.position",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class PromptTemplate(Base):
    """Reusable prompt templates for task creation."""

    __tablename__ = "prompt_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    variable_tips: Mapped[dict[str, str] | None] = mapped_column(JSON, nullable=True)
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )


class ProjectWebhookConfig(Base):
    """Per-project webhook configuration managed by this system."""

    __tablename__ = "project_webhook_config"

    project_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    secret_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )


class MattermostNotificationProfile(Base):
    """Notification profile for Mattermost task updates."""

    __tablename__ = "mattermost_notification_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    channel_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mention_in_channel: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    event_types_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    field_keys_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )


class MattermostUserMapping(Base):
    """Cached mapping from GitLab/dashboard users to Mattermost users."""

    __tablename__ = "mattermost_user_mappings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    gitlab_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    gitlab_username: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    mattermost_user_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    mattermost_username: Mapped[str] = mapped_column(String(255), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="username")
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )


class MattermostNotificationDelivery(Base):
    """Delivery log for task-related Mattermost notifications."""

    __tablename__ = "mattermost_notification_deliveries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    profile_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("mattermost_notification_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    target_summary: Mapped[str] = mapped_column(String(255), nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow
    )


class User(Base):
    """Dashboard user supporting both local and GitLab OIDC authentication."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    oidc_sub: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    gitlab_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, unique=True, index=True)
    username: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    # Authentication provider: 'local' or 'gitlab_oidc'
    auth_provider: Mapped[str] = mapped_column(
        String(32), nullable=False, default="local", index=True
    )
    # Hashed password for local authentication (NULL for OIDC-only users)
    local_password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)

    platform_role: Mapped[str] = mapped_column(String(32), nullable=False, default="platform_user")
    platform_role_source: Mapped[str] = mapped_column(
        String(32), nullable=False, default="bootstrap"
    )
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )


class UserSession(Base):
    """Server-side session for an authenticated dashboard user."""

    __tablename__ = "user_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_token_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    gitlab_access_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    gitlab_refresh_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow
    )


class AuthAuditLog(Base):
    """Audit trail for authentication-related security events."""

    __tablename__ = "auth_audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, index=True
    )


class SystemBootstrap(Base):
    """System bootstrap state tracking - ensures single-row state table."""

    __tablename__ = "system_bootstrap"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    initialized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    initial_admin_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    initialized_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow
    )


class WebhookEvent(Base):
    """Log entry for a received GitLab webhook event."""

    __tablename__ = "webhook_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    event_action: Mapped[str | None] = mapped_column(String(50), nullable=True)
    project_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    merge_request_iid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    issue_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("issues.id", ondelete="SET NULL"), nullable=True
    )
    source_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    result: Mapped[str] = mapped_column(String(50), nullable=False)
    result_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow
    )

    issue: Mapped[Optional["Issue"]] = relationship("Issue")

    __table_args__ = (
        Index("ix_webhook_events_project_created", "project_id", "created_at"),
    )


class CIFailureRun(Base):
    """Durable record for one failed GitLab pipeline accepted for CI evidence collection."""

    __tablename__ = "ci_failure_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    webhook_event_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("webhook_events.id", ondelete="SET NULL"), nullable=True, index=True
    )
    project_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    issue_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("issues.id", ondelete="SET NULL"), nullable=True, index=True
    )
    merge_request_iid: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    source_branch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    target_branch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    pipeline_id: Mapped[int] = mapped_column(Integer, nullable=False)
    pipeline_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    pipeline_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    pipeline_status: Mapped[str] = mapped_column(String(32), nullable=False)
    pipeline_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="collecting", index=True)
    root_cause_strategy: Mapped[str] = mapped_column(
        String(64), nullable=False, default="first_failed_stage"
    )
    bundle_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    repair_task_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True, index=True
    )
    ignored_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    collection_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    locked_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )

    repair_task: Mapped[Optional["Task"]] = relationship(
        "Task",
        foreign_keys=[repair_task_id],
        post_update=True,
    )
    repair_tasks: Mapped[list["Task"]] = relationship(
        "Task",
        foreign_keys="Task.ci_failure_run_id",
        back_populates="ci_failure_run",
    )
    jobs: Mapped[list["CIFailureJob"]] = relationship(
        "CIFailureJob",
        back_populates="ci_failure_run",
        cascade="all, delete-orphan",
    )
    logs: Mapped[list["CIFailureRunLog"]] = relationship(
        "CIFailureRunLog",
        back_populates="ci_failure_run",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("project_id", "pipeline_id", name="uq_ci_failure_runs_project_pipeline"),
        Index("ix_ci_failure_runs_status_locked", "status", "locked_at"),
        Index("ix_ci_failure_runs_issue_created", "issue_id", "created_at"),
    )


class CIFailureJob(Base):
    """Failed or relevant GitLab CI job captured for a CI failure run."""

    __tablename__ = "ci_failure_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ci_failure_run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("ci_failure_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    gitlab_job_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    stage: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    failure_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    allow_failure: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    web_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    trace_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    trace_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_root_cause: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_downstream_suppressed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    classification: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

    ci_failure_run: Mapped["CIFailureRun"] = relationship("CIFailureRun", back_populates="jobs")

    __table_args__ = (
        UniqueConstraint("ci_failure_run_id", "gitlab_job_id", name="uq_ci_failure_jobs_run_job"),
    )


class CIFailureRunLog(Base):
    """Product-visible structured timeline entry for CI failure collection."""

    __tablename__ = "ci_failure_run_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ci_failure_run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("ci_failure_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    issue_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("issues.id", ondelete="SET NULL"), nullable=True, index=True
    )
    task_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True, index=True
    )
    step: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

    ci_failure_run: Mapped["CIFailureRun"] = relationship("CIFailureRun", back_populates="logs")


class TaskRunArchive(Base):
    """One-row-per-task compressed runtime archive."""

    __tablename__ = "task_run_archives"
    __table_args__ = (
        Index("ix_task_run_archives_created_id", "created_at", "id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tasks.id", ondelete="CASCADE"), index=True, unique=True
    )
    archive_name: Mapped[str] = mapped_column(String(255), nullable=False)
    archive_path: Mapped[str] = mapped_column(Text, nullable=False)
    archive_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    cleanup_next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class TaskIngestCursor(Base):
    """Tracks byte offset and sequence number for each tailer stream per task."""

    __tablename__ = "task_ingest_cursors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tasks.id", ondelete="CASCADE"), index=True
    )
    stream_name: Mapped[str] = mapped_column(String(50), nullable=False)
    last_offset: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_sequence_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        UniqueConstraint("task_id", "stream_name", name="uq_task_ingest_cursor"),
    )


class TaskRawLogChunk(Base):
    """Raw console log chunks stored for post-completion browsing."""

    __tablename__ = "task_raw_log_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tasks.id", ondelete="CASCADE"), index=True
    )
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    encoding: Mapped[str] = mapped_column(String(20), nullable=False, default="identity")
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    byte_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("task_id", "sequence_no", name="uq_task_raw_log_chunk_seq"),
    )


class TaskPayload(Base):
    """Full tool input/output and assistant text bodies (replaces inline storage in TaskLog)."""

    __tablename__ = "task_payloads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tasks.id", ondelete="CASCADE"), index=True
    )
    payload_kind: Mapped[str] = mapped_column(String(50), nullable=False)
    encoding: Mapped[str] = mapped_column(String(20), nullable=False, default="identity")
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    byte_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
