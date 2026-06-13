"""ci failure auto repair

Revision ID: 046_ci_failure_auto_repair
Revises: 045_add_prompt_template_tags
Create Date: 2026-06-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "046_ci_failure_auto_repair"
down_revision: Union[str, None] = "045_add_prompt_template_tags"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "issues",
        sa.Column(
            "ci_auto_repair_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    op.create_table(
        "ci_failure_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("webhook_event_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("issue_id", sa.Integer(), nullable=True),
        sa.Column("merge_request_iid", sa.Integer(), nullable=True),
        sa.Column("source_branch", sa.String(length=255), nullable=True),
        sa.Column("target_branch", sa.String(length=255), nullable=True),
        sa.Column("pipeline_id", sa.Integer(), nullable=False),
        sa.Column("pipeline_sha", sa.String(length=40), nullable=False),
        sa.Column("pipeline_ref", sa.String(length=255), nullable=True),
        sa.Column("pipeline_status", sa.String(length=32), nullable=False),
        sa.Column("pipeline_url", sa.String(length=512), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("root_cause_strategy", sa.String(length=64), nullable=False),
        sa.Column("bundle_path", sa.Text(), nullable=True),
        sa.Column("repair_task_id", sa.Integer(), nullable=True),
        sa.Column("ignored_reason", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("collection_attempts", sa.Integer(), nullable=False),
        sa.Column("locked_at", sa.DateTime(), nullable=True),
        sa.Column("locked_by", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["issue_id"], ["issues.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["repair_task_id"], ["tasks.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["webhook_event_id"], ["webhook_events.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "pipeline_id", name="uq_ci_failure_runs_project_pipeline"),
    )
    op.create_index("ix_ci_failure_runs_issue_created", "ci_failure_runs", ["issue_id", "created_at"])
    op.create_index("ix_ci_failure_runs_status", "ci_failure_runs", ["status"])
    op.create_index("ix_ci_failure_runs_status_locked", "ci_failure_runs", ["status", "locked_at"])

    op.add_column(
        "tasks",
        sa.Column(
            "trigger_source",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'manual'"),
        ),
    )
    op.add_column("tasks", sa.Column("ci_failure_run_id", sa.Integer(), nullable=True))
    op.create_index("ix_tasks_ci_failure_run_id", "tasks", ["ci_failure_run_id"])
    op.create_index("ix_tasks_trigger_source", "tasks", ["trigger_source"])
    op.create_index("ix_tasks_issue_trigger_source", "tasks", ["issue_id", "trigger_source"])
    op.create_foreign_key(
        "fk_tasks_ci_failure_run_id_ci_failure_runs",
        "tasks",
        "ci_failure_runs",
        ["ci_failure_run_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "ci_failure_jobs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("ci_failure_run_id", sa.Integer(), nullable=False),
        sa.Column("gitlab_job_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("stage", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("failure_reason", sa.String(length=128), nullable=True),
        sa.Column("allow_failure", sa.Boolean(), nullable=False),
        sa.Column("web_url", sa.String(length=512), nullable=True),
        sa.Column("trace_path", sa.Text(), nullable=True),
        sa.Column("trace_size_bytes", sa.Integer(), nullable=False),
        sa.Column("is_root_cause", sa.Boolean(), nullable=False),
        sa.Column("is_downstream_suppressed", sa.Boolean(), nullable=False),
        sa.Column("classification", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["ci_failure_run_id"], ["ci_failure_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ci_failure_run_id", "gitlab_job_id", name="uq_ci_failure_jobs_run_job"),
    )
    op.create_index("ix_ci_failure_jobs_ci_failure_run_id", "ci_failure_jobs", ["ci_failure_run_id"])
    op.create_index("ix_ci_failure_jobs_gitlab_job_id", "ci_failure_jobs", ["gitlab_job_id"])

    op.create_table(
        "ci_failure_run_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("ci_failure_run_id", sa.Integer(), nullable=False),
        sa.Column("issue_id", sa.Integer(), nullable=True),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("step", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["ci_failure_run_id"], ["ci_failure_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["issue_id"], ["issues.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ci_failure_run_logs_ci_failure_run_id", "ci_failure_run_logs", ["ci_failure_run_id"])
    op.create_index("ix_ci_failure_run_logs_issue_id", "ci_failure_run_logs", ["issue_id"])
    op.create_index("ix_ci_failure_run_logs_task_id", "ci_failure_run_logs", ["task_id"])
    op.create_index("ix_ci_failure_run_logs_step", "ci_failure_run_logs", ["step"])

    op.alter_column("issues", "ci_auto_repair_enabled", server_default=None)
    op.alter_column("tasks", "trigger_source", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_ci_failure_run_logs_step", table_name="ci_failure_run_logs")
    op.drop_index("ix_ci_failure_run_logs_task_id", table_name="ci_failure_run_logs")
    op.drop_index("ix_ci_failure_run_logs_issue_id", table_name="ci_failure_run_logs")
    op.drop_index("ix_ci_failure_run_logs_ci_failure_run_id", table_name="ci_failure_run_logs")
    op.drop_table("ci_failure_run_logs")

    op.drop_index("ix_ci_failure_jobs_gitlab_job_id", table_name="ci_failure_jobs")
    op.drop_index("ix_ci_failure_jobs_ci_failure_run_id", table_name="ci_failure_jobs")
    op.drop_table("ci_failure_jobs")

    op.drop_constraint("fk_tasks_ci_failure_run_id_ci_failure_runs", "tasks", type_="foreignkey")
    op.drop_index("ix_tasks_issue_trigger_source", table_name="tasks")
    op.drop_index("ix_tasks_trigger_source", table_name="tasks")
    op.drop_index("ix_tasks_ci_failure_run_id", table_name="tasks")
    op.drop_column("tasks", "ci_failure_run_id")
    op.drop_column("tasks", "trigger_source")

    op.drop_index("ix_ci_failure_runs_status_locked", table_name="ci_failure_runs")
    op.drop_index("ix_ci_failure_runs_status", table_name="ci_failure_runs")
    op.drop_index("ix_ci_failure_runs_issue_created", table_name="ci_failure_runs")
    op.drop_table("ci_failure_runs")

    op.drop_column("issues", "ci_auto_repair_enabled")
