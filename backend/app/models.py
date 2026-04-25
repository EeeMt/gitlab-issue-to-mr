"""Database models for the application."""

from datetime import datetime
from enum import Enum
from typing import Optional, List

from sqlalchemy import Boolean, DateTime, Enum as SQLEnum, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


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
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    project_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), default=IssueStatus.OPEN.value, nullable=False)
    closed_via: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)

    # Branch & MR (promoted from Task)
    branch_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    base_branch: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    target_branch: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    merge_request_iid: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    merge_request_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    # Claude session persistence
    claude_session_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    session_storage_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    # Creator
    initiator_user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    initiator_username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    tasks: Mapped[List["Task"]] = relationship("Task", back_populates="issue", order_by="Task.created_at")

    __table_args__ = (
        Index("ix_issues_status_created", "status", "created_at"),
        Index("ix_issues_project_status", "project_id", "status"),
    )


class AIProvider(Base):
    """Named AI provider configuration."""

    __tablename__ = "ai_providers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    api_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    max_turns: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    system_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    tasks: Mapped[List["Task"]] = relationship("Task", back_populates="provider")


class Task(Base):
    """Task model — one execution unit (one `claude -p` call). Belongs to an Issue."""

    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Parent issue
    issue_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("issues.id", ondelete="SET NULL"), nullable=True, index=True
    )
    project_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    # AI Provider
    provider_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("ai_providers.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Task details
    user_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    initiator_user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    initiator_gitlab_user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    initiator_username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    initiator_display_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    initiator_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Retry tracking
    is_retry: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    retry_source_task_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("tasks.id"), nullable=True
    )

    # Status
    status: Mapped[TaskStatus] = mapped_column(
        task_status_enum,
        nullable=False,
        default=TaskStatus.PENDING,
    )

    # Scheduling
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)

    # Container tracking
    container_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # Results
    commit_sha: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Change statistics
    additions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deletions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_changes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Token usage (populated from Claude CLI output)
    input_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # AI model used for this task (populated from CODIFY_SYSTEM_INIT marker)
    model_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    # MR title generated by AI post-execution (populated from CODIFY_MR_TITLE marker)
    merge_request_title: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Relationships
    issue: Mapped[Optional["Issue"]] = relationship("Issue", back_populates="tasks")
    retry_source: Mapped[Optional["Task"]] = relationship(
        "Task", remote_side="Task.id", foreign_keys=[retry_source_task_id]
    )
    provider: Mapped[Optional["AIProvider"]] = relationship("AIProvider", back_populates="tasks")

    # Indexes for querying tasks
    __table_args__ = (
        Index("ix_tasks_status_created", "status", "created_at"),
        Index("ix_tasks_status_priority", "status", "priority", "scheduled_at"),
        Index("ix_tasks_issue_id_status", "issue_id", "status"),
        Index("ix_tasks_created_at_project", "created_at", "project_id"),
        Index("ix_tasks_created_at_status", "created_at", "status"),
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
    # 'tool_calls_json' entries store a JSON array of {name, input, output, error} in log_metadata.
    log_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    log_metadata: Mapped[str | None] = mapped_column(Text, nullable=True)

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


class WorkerEnvironmentVariable(Base):
    """Persisted custom environment variable injected into worker containers."""

    __tablename__ = "worker_environment_variables"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(255), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    is_secret: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        Index("ix_worker_environment_variables_key", "key", unique=True),
    )


class PromptTemplate(Base):
    """Reusable prompt templates for task creation."""

    __tablename__ = "prompt_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    variable_tips: Mapped[Optional[dict[str, str]]] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class ProjectWebhookConfig(Base):
    """Per-project webhook configuration managed by this system."""

    __tablename__ = "project_webhook_config"

    project_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    secret_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class MattermostNotificationProfile(Base):
    """Notification profile for Mattermost task updates."""

    __tablename__ = "mattermost_notification_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    channel_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    mention_in_channel: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    event_types_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    field_keys_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class MattermostUserMapping(Base):
    """Cached mapping from GitLab/dashboard users to Mattermost users."""

    __tablename__ = "mattermost_user_mappings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    gitlab_user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    gitlab_username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    mattermost_user_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    mattermost_username: Mapped[str] = mapped_column(String(255), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="username")
    last_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
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
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )


class User(Base):
    """Dashboard user supporting both local and GitLab OIDC authentication."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    oidc_sub: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, unique=True)
    gitlab_user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, unique=True, index=True)
    username: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    display_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    avatar_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    
    # Authentication provider: 'local' or 'gitlab_oidc'
    auth_provider: Mapped[str] = mapped_column(
        String(32), nullable=False, default="local", index=True
    )
    # Hashed password for local authentication (NULL for OIDC-only users)
    local_password_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    
    platform_role: Mapped[str] = mapped_column(String(32), nullable=False, default="platform_user")
    platform_role_source: Mapped[str] = mapped_column(
        String(32), nullable=False, default="bootstrap"
    )
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class UserSession(Base):
    """Server-side session for an authenticated dashboard user."""

    __tablename__ = "user_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_token_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    gitlab_access_token_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    gitlab_refresh_token_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )


class AuthAuditLog(Base):
    """Audit trail for authentication-related security events."""

    __tablename__ = "auth_audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, index=True
    )


class SystemBootstrap(Base):
    """System bootstrap state tracking - ensures single-row state table."""

    __tablename__ = "system_bootstrap"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    initialized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    initial_admin_user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    initialized_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )


class WebhookEvent(Base):
    """Log entry for a received GitLab webhook event."""

    __tablename__ = "webhook_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    event_action: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    project_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    merge_request_iid: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    issue_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("issues.id", ondelete="SET NULL"), nullable=True
    )
    source_ip: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    result: Mapped[str] = mapped_column(String(50), nullable=False)
    result_detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    payload_summary: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )

    issue: Mapped[Optional["Issue"]] = relationship("Issue")

    __table_args__ = (
        Index("ix_webhook_events_project_created", "project_id", "created_at"),
    )
