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
    default_harness_key: Mapped[str | None] = mapped_column(String(32), nullable=True)
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

    harness_sessions: Mapped[list["IssueHarnessSession"]] = relationship(
        "IssueHarnessSession",
        back_populates="issue",
        cascade="all, delete-orphan",
    )


class IssueHarnessSession(Base):
    """Per-issue, per-harness, per-namespace session lineage pointer."""

    __tablename__ = "issue_harness_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    issue_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("issues.id", ondelete="CASCADE"), nullable=False, index=True
    )
    harness_key: Mapped[str] = mapped_column(String(64), nullable=False)
    session_namespace: Mapped[str] = mapped_column(String(128), nullable=False)
    session_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lineage_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    session_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        UniqueConstraint(
            "issue_id",
            "harness_key",
            "session_namespace",
            name="uq_issue_harness_session",
        ),
    )

    issue: Mapped["Issue"] = relationship("Issue", back_populates="harness_sessions")


class IssueSessionLineage(Base):
    """Per-issue, per-generation actual session facts for the new scheduler.

    One row per ``(issue_id, lineage_generation)``. ``session_id`` is only
    backfilled from a completed Task's ``output_session_id`` in the same
    generation; generation ``0`` may also import an exactly matching legacy
    ``IssueHarnessSession``. ``reset_task_id`` points at the fresh/compat-reset
    Task that established the generation (null for generation ``0``).
    """

    __tablename__ = "issue_session_lineages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    issue_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("issues.id", ondelete="CASCADE"), nullable=False, index=True
    )
    lineage_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    harness_key: Mapped[str] = mapped_column(String(64), nullable=False)
    session_namespace: Mapped[str] = mapped_column(String(128), nullable=False)
    reset_task_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("tasks.id", ondelete="SET NULL"),
        nullable=True,
    )
    session_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_output_task_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("tasks.id", ondelete="SET NULL"),
        nullable=True,
    )
    last_output_issue_sequence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lineage_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lineage_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        UniqueConstraint(
            "issue_id",
            "lineage_generation",
            name="uq_issue_session_lineage_generation",
        ),
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
    provider_kind: Mapped[str] = mapped_column(
        String(32), nullable=False, default="anthropic_compatible"
    )
    # ``model_protocol`` is the V2 wire-protocol name. Only three values are
    # allowed: anthropic_messages / openai_responses / openai_chat_completions.
    model_protocol: Mapped[str] = mapped_column(
        String(32), nullable=False, default="anthropic_messages"
    )
    # Describes known differences of an OpenAI-compatible service; backend
    # allowlist, unknown values rejected at Task creation.
    compat_profile: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider_options: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    credential_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)

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


class ModelCredential(Base):
    """Persistent, independently-rotatable model credential referenced by Task snapshots.

    Task snapshots keep only a stable ``credential_ref``; the secret lives here.
    Deleting a Provider does not cascade-delete a credential: referenced
    credentials can only be soft-retired, never hard-deleted.
    """

    __tablename__ = "model_credentials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    ref: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    secret_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="api_key")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    provider_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    version_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
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
    runtime_bundle_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("worker_runtime_bundles.id", ondelete="RESTRICT"),
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

    # Issue input-stream ordering. ``issue_sequence`` is the immutable turn number
    # within the Issue and the single source of truth for execution order. It is
    # nullable only during the 068 compatibility window so legacy writers can keep
    # inserting rows; the Scheduler and append service always backfill/allocate it
    # and fail closed while an active NULL exists.
    issue_sequence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Projected lineage frozen at creation time (harness, session namespace,
    # generation and the fresh/reset task that established this generation).
    # Kept nullable for the same 068 compatibility window.
    projected_harness_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    projected_session_namespace: Mapped[str | None] = mapped_column(String(128), nullable=True)
    projected_lineage_generation: Mapped[int | None] = mapped_column(Integer, nullable=True)
    projected_reset_task_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey(
            "tasks.id",
            ondelete="NO ACTION",
            deferrable=True,
            initially="DEFERRED",
        ),
        nullable=True,
    )
    # Why this lineage projection was chosen: initial / inherited / fresh /
    # legacy_namespace_change. ``input_lineage_reason`` records the actual
    # execution-time resume decision (fresh / resumed / fresh_no_match) and is
    # never derived from the projection fields.
    lineage_projection_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    input_lineage_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Container tracking
    container_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Results
    commit_sha: Mapped[str | None] = mapped_column(String(40), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Change statistics
    additions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deletions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_changes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Non-null once a trusted writer persisted valid change stats (including real
    # zeros). Lets lifecycle statistics distinguish "zero changes" from
    # "not collected"; see system lifecycle statistics design §6.4.
    change_stats_recorded_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )

    # Token usage (populated from Claude CLI output)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Require code changes for success (relevant when issue has target_branch)
    require_changes: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Execution mode: 'execute' (default) makes code changes; 'plan' only
    # analyses and outputs a proposal; 'freeform' uses only the user prompt and
    # never requires code changes.
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
    runtime_bundle: Mapped["WorkerRuntimeBundle | None"] = relationship(
        "WorkerRuntimeBundle",
        back_populates="tasks",
    )
    harness_attempts: Mapped[list["TaskHarnessAttempt"]] = relationship(
        "TaskHarnessAttempt",
        back_populates="task",
        order_by="TaskHarnessAttempt.attempt_no",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    harness_commands: Mapped[list["TaskHarnessCommand"]] = relationship(
        "TaskHarnessCommand",
        back_populates="task",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    ci_failure_run: Mapped[Optional["CIFailureRun"]] = relationship(
        "CIFailureRun",
        foreign_keys=[ci_failure_run_id],
        back_populates="repair_tasks",
    )

    # Indexes for querying tasks
    __table_args__ = (
        CheckConstraint(
            "lineage_projection_reason IS NULL OR lineage_projection_reason IN "
            "('initial', 'inherited', 'fresh', 'legacy_namespace_change')",
            name="ck_tasks_lineage_projection_reason",
        ),
        CheckConstraint(
            "input_lineage_reason IS NULL OR input_lineage_reason IN "
            "('fresh', 'resumed', 'fresh_no_match')",
            name="ck_tasks_input_lineage_reason",
        ),
        Index("ix_tasks_status_created", "status", "created_at"),
        Index("ix_tasks_status_priority", "status", "priority", "scheduled_at"),
        Index("ix_tasks_issue_id_status", "issue_id", "status"),
        Index("ix_tasks_issue_trigger_source", "issue_id", "trigger_source"),
        Index("ix_tasks_created_at_project", "created_at", "project_id"),
        Index("ix_tasks_created_at_status", "created_at", "status"),
        # Issue input-stream ordering: ``issue_sequence`` is unique per issue
        # (partial while the 068 compatibility window allows legacy NULL rows).
        Index(
            "uq_tasks_issue_sequence",
            "issue_id",
            "issue_sequence",
            unique=True,
            postgresql_where=text("issue_sequence IS NOT NULL"),
            sqlite_where=text("issue_sequence IS NOT NULL"),
        ),
        Index("ix_tasks_issue_status_sequence", "issue_id", "status", "issue_sequence"),
        Index(
            "ix_tasks_issue_generation_sequence",
            "issue_id",
            "projected_lineage_generation",
            "issue_sequence",
        ),
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


class WorkerRuntimeBundle(Base):
    """Content-addressed orchestration and Harness Adapter runtime source."""

    __tablename__ = "worker_runtime_bundles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    digest: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    bundle_bytes: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, deferred=True)
    contract_version: Mapped[str] = mapped_column(String(64), nullable=False)
    orchestration_version: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest: Mapped[dict] = mapped_column(JSON, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

    tasks: Mapped[list[Task]] = relationship("Task", back_populates="runtime_bundle")


class TaskHarnessAttempt(Base):
    """Immutable execution-attempt identity and canonical ingest state."""

    __tablename__ = "task_harness_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    attempt_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    task_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    event_schema: Mapped[str] = mapped_column(String(64), nullable=False)
    harness_key: Mapped[str] = mapped_column(String(64), nullable=False)
    adapter_version: Mapped[str] = mapped_column(String(64), nullable=False)
    cli_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # V2 command control gate (disabled/starting/accepting/closing/closed).
    control_state: Mapped[str] = mapped_column(
        String(16), nullable=False, default="disabled"
    )
    # A follow_up was ACKed while draining but Pi has not emitted the next
    # native turn-start evidence.  It blocks closing the owner prematurely.
    awaiting_follow_up_turn: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    pending_follow_up_command_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pending_follow_up_native_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    force_close_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Next attempt-scoped command sequence to allocate (>= 1).
    next_command_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # Command dispatch lease (worker/container id + expiry) — single dispatcher.
    command_dispatch_owner: Mapped[str | None] = mapped_column(String(64), nullable=True)
    command_dispatch_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    last_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    terminal_event_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    terminal_event_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    terminal_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
    )

    task: Mapped[Task] = relationship("Task", back_populates="harness_attempts")
    ingest_cursors: Mapped[list["TaskIngestCursor"]] = relationship(
        "TaskIngestCursor",
        back_populates="attempt",
    )
    event_receipts: Mapped[list["TaskHarnessEventReceipt"]] = relationship(
        "TaskHarnessEventReceipt",
        back_populates="attempt",
        order_by="TaskHarnessEventReceipt.seq",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        UniqueConstraint("task_id", "attempt_no", name="uq_task_harness_attempt_no"),
        CheckConstraint("attempt_no >= 1", name="ck_task_harness_attempt_no"),
        CheckConstraint("last_seq >= 0", name="ck_task_harness_attempt_last_seq"),
        CheckConstraint(
            "terminal_event_type IS NULL OR terminal_event_type IN ('run.completed', 'run.failed')",
            name="ck_task_harness_attempt_terminal_type",
        ),
        CheckConstraint(
            "control_state IN ('disabled','starting','accepting','closing','closed')",
            name="ck_task_harness_attempt_control_state",
        ),
        CheckConstraint(
            "next_command_sequence >= 1",
            name="ck_task_harness_attempt_next_command_sequence",
        ),
    )


class TaskHarnessEventReceipt(Base):
    """Canonical event receipt used for exact idempotency and conflict detection."""

    __tablename__ = "task_harness_event_receipts"

    attempt_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("task_harness_attempts.attempt_id", ondelete="CASCADE"),
        primary_key=True,
    )
    seq: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    event_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    event: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

    attempt: Mapped[TaskHarnessAttempt] = relationship(
        "TaskHarnessAttempt",
        back_populates="event_receipts",
    )

    __table_args__ = (
        CheckConstraint("seq >= 1", name="ck_task_harness_event_receipt_seq"),
    )


class TaskHarnessCommand(Base):
    """V2 control command queued for an in-flight Harness attempt.

    ``queued -> dispatching -> delivered|rejected|outcome_unknown`` transitions
    are written only by the command pump via CAS. ``outcome_unknown`` is
    terminal and must never be replayed after owner recovery.
    Command lifecycle stats never feed Issue lifecycle statistics.
    """

    __tablename__ = "task_harness_commands"

    command_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    attempt_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("task_harness_attempts.attempt_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    command_type: Mapped[str] = mapped_column(String(16), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    payload_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    delivery_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    dispatch_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    native_request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    native_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    native_ack_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    outcome_unknown_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rejection_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rejection_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    task: Mapped[Task] = relationship("Task", back_populates="harness_commands")
    attempt: Mapped["TaskHarnessAttempt"] = relationship("TaskHarnessAttempt")

    __table_args__ = (
        CheckConstraint(
            "sequence_no >= 1", name="ck_task_harness_command_sequence_no"
        ),
        CheckConstraint(
            "command_type IN ('steer','follow_up')",
            name="ck_task_harness_command_type",
        ),
        CheckConstraint(
            "status IN ('queued','dispatching','delivered','rejected','outcome_unknown')",
            name="ck_task_harness_command_status",
        ),
        CheckConstraint(
            "(status IN ('queued','dispatching','outcome_unknown')) = (delivered_at IS NULL AND rejected_at IS NULL)",
            name="ck_task_harness_command_queued_consistency",
        ),
        CheckConstraint(
            "(status = 'delivered') = (delivered_at IS NOT NULL)",
            name="ck_task_harness_command_delivered_consistency",
        ),
        CheckConstraint(
            "(status = 'rejected') = (rejected_at IS NOT NULL)",
            name="ck_task_harness_command_rejected_consistency",
        ),
        CheckConstraint(
            "(status = 'outcome_unknown') = (outcome_unknown_at IS NOT NULL)",
            name="ck_task_harness_command_unknown_consistency",
        ),
        UniqueConstraint(
            "attempt_id", "sequence_no", name="uq_task_harness_command_attempt_seq"
        ),
        Index(
            "ix_task_harness_commands_attempt_status",
            "attempt_id",
            "status",
        ),
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


class WorkerSharedConfiguration(Base):
    """Administrator-maintained system-wide worker configuration singleton."""

    __tablename__ = "worker_shared_configurations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    runtime_mode: Mapped[str] = mapped_column(
        String(32), nullable=False, default="baked_image"
    )
    worker_kit_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    worker_kit_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    volume_mounts: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    pre_script: Mapped[str | None] = mapped_column(Text, nullable=True)
    post_script: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_execute_run_instruction_template: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    default_plan_run_instruction_template: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    ci_auto_repair_run_instruction_template: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
    )

    environment_variables: Mapped[list["WorkerSharedEnvironmentVariable"]] = relationship(
        "WorkerSharedEnvironmentVariable",
        back_populates="shared_configuration",
        cascade="all, delete-orphan",
        order_by="WorkerSharedEnvironmentVariable.key",
    )


class WorkerSharedEnvironmentVariable(Base):
    """Environment variable inherited from the system shared configuration."""

    __tablename__ = "worker_shared_environment_variables"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    worker_shared_configuration_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("worker_shared_configurations.id", ondelete="CASCADE"),
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

    shared_configuration: Mapped[WorkerSharedConfiguration] = relationship(
        "WorkerSharedConfiguration",
        back_populates="environment_variables",
    )

    __table_args__ = (
        Index(
            "uq_worker_shared_environment_key",
            "worker_shared_configuration_id",
            "key",
            unique=True,
        ),
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
    worker_kit_source: Mapped[str] = mapped_column(
        String(16), nullable=False, default="profile", server_default=text("'profile'")
    )
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
    volume_mount_masks: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    pre_script: Mapped[str | None] = mapped_column(Text, nullable=True)
    post_script: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_execute_run_instruction_template: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    default_plan_run_instruction_template: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    ci_auto_repair_run_instruction_template: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    verified_runtime_configuration_digest: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    enabled_harnesses: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    default_harness_key: Mapped[str] = mapped_column(
        String(32), nullable=False, default="claude", server_default=text("'claude'")
    )
    harness_constraints: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # V2 namespaced per-harness options, e.g. {"pi":{...},"opencode":{...}}.
    harness_options: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    image_digest: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Non-secret daemon image evidence for explicit harness/v2 task snapshots.
    # Kept as JSON so the snapshot can freeze the exact validated identity.
    v2_worker_image_identity: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    v2_worker_image_identity_generation: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    # Evidence is keyed by the eligible V2 Harness key.  One image may be
    # verified for several Harnesses, but success for (say) Claude must never
    # authorize a Pi task without Pi's own strict verification.
    v2_harness_verification_evidence: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Content-addressed Worker Kit identity (codify.worker.kit-identity/v1)
    # recorded by the last verified Kit installation; its generation
    # invalidates stale verification evidence like the image generation does.
    worker_kit_identity: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    worker_kit_identity_generation: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    harness_runtimes: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
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
    operation: Mapped[str] = mapped_column(
        String(16), nullable=False, default="set", server_default=text("'set'")
    )
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    shared_configuration_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    effective_configuration_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    runtime_locator_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
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
    harness_key: Mapped[str | None] = mapped_column(String(32), nullable=True)
    harness_adapter_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    harness_adapter_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    harness_config_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    model_endpoint_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    credential_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    cli_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    cli_executable_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    cli_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    cli_binary_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    image_digest: Mapped[str | None] = mapped_column(String(128), nullable=True)
    runtime_contract_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    orchestration_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    runtime_bundle_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
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


class WorkerRuntimeReadiness(Base):
    """Deterministic runtime readiness observation keyed by locator and scope.

    The primary key is the historical locator fingerprint for the V1 probe, or
    a scoped derivative for V2's full content-inventory probe. This keeps
    readiness shared by Profiles and historical Task snapshots without letting
    a stricter V2 conclusion contaminate the V1 dual-canary path. ``status=ready``
    is only effective while ``ready_until > now``; a missing row, ``unknown``, or
    an expired ``ready`` all read as ``unknown``. ``unavailable`` never
    auto-expires and requires a successful re-check to be replaced.
    """

    __tablename__ = "worker_runtime_readiness"

    runtime_locator_fingerprint: Mapped[str] = mapped_column(String(64), primary_key=True)
    docker_daemon_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    runtime_mode: Mapped[str | None] = mapped_column(String(32), nullable=True)
    worker_kit_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    worker_kit_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ready_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    check_generation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Observed Kit harness inventory (availability/reason per key) and the
    # manifest content identity from the last committed probe.
    harness_inventory: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    kit_identity: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    check_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
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
    attempt_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("task_harness_attempts.attempt_id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    stream_name: Mapped[str] = mapped_column(String(50), nullable=False)
    last_offset: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_sequence_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        UniqueConstraint("task_id", "stream_name", name="uq_task_ingest_cursor"),
        UniqueConstraint("attempt_id", "stream_name", name="uq_attempt_ingest_cursor"),
    )

    attempt: Mapped[TaskHarnessAttempt | None] = relationship(
        "TaskHarnessAttempt",
        back_populates="ingest_cursors",
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


# Lifecycle statistics schema version. Bump only when an existing archive row's
# read contract changes in a way that older readers would misinterpret.
LIFECYCLE_STATISTICS_SCHEMA_VERSION = 1


class DeletedTaskStatistics(Base):
    """Lightweight snapshot of a Task archived immediately before its deletion.

    Each row corresponds to one deleted Task. No FK is kept to ``tasks``, the
    User, AIProvider or WorkerProfile so the archive survives business-data
    cleanup. Whitelisted fields only — never Prompts, logs, secrets or error
    bodies. See system lifecycle statistics design §6.1.
    """

    __tablename__ = "deleted_task_statistics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_task_id: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    source_issue_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    project_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    initiator_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    provider_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    provider_name_snapshot: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_model_snapshot: Mapped[str | None] = mapped_column(String(128), nullable=True)

    harness_key: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    adapter_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cli_version: Mapped[str | None] = mapped_column(String(128), nullable=True)

    worker_profile_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    worker_profile_name_snapshot: Mapped[str | None] = mapped_column(String(100), nullable=True)

    task_mode: Mapped[str | None] = mapped_column(String(16), nullable=True)
    trigger_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    priority: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_retry: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    last_status: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    deleted_before_terminal: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_manually_overridden: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    terminal_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)

    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)

    additions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    deletions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_changes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    change_data_available: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    source_deleted_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, index=True
    )
    deletion_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    deleted_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    schema_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=LIFECYCLE_STATISTICS_SCHEMA_VERSION
    )
    archived_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow
    )


class DeletedIssueStatistics(Base):
    """Lightweight snapshot of an Issue archived immediately before its deletion.

    Task counts, tokens and code changes are not duplicated here — they are
    aggregated from ``deleted_task_statistics`` by ``source_issue_id``. See
    system lifecycle statistics design §6.2.
    """

    __tablename__ = "deleted_issue_statistics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_issue_id: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    project_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    initiator_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(32), nullable=True)

    had_merge_request: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    source_deleted_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, index=True
    )
    deletion_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    deleted_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    forced_with_active_tasks: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    schema_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=LIFECYCLE_STATISTICS_SCHEMA_VERSION
    )
    archived_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow
    )


class SystemStatisticsMetadata(Base):
    """Single-row lifecycle-statistics metadata.

    ``capture_started_at`` is the deployment-gated point from which deletions
    via the standard entry points are guaranteed archived. It stays NULL after
    migration 069 and is set by the deployment step (§12.2). See design §6.3.
    """

    __tablename__ = "system_statistics_metadata"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    capture_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    schema_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=LIFECYCLE_STATISTICS_SCHEMA_VERSION
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
    )
