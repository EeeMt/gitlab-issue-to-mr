"""pin each issue to one worker and track remote workspace state

Revision ID: 058_issue_worker_affinity
Revises: 057_task_session_mode
Create Date: 2026-07-16
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "058_issue_worker_affinity"
down_revision: Union[str, None] = "057_task_session_mode"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    conflicting_running_issue_count = conn.execute(
        sa.text(
            "SELECT count(*) FROM ("
            "SELECT issue_id FROM tasks WHERE status = 'running' "
            "AND worker_profile_id IS NOT NULL GROUP BY issue_id "
            "HAVING count(DISTINCT worker_profile_id) > 1"
            ") AS conflicts"
        )
    ).scalar_one()
    if conflicting_running_issue_count:
        raise RuntimeError(
            "Cannot pin issues: multiple running workers exist for the same issue"
        )

    unassignable_running_task_count = conn.execute(
        sa.text(
            "SELECT count(*) FROM tasks WHERE status = 'running' AND ("
            "worker_profile_id IS NULL OR NOT EXISTS ("
            "SELECT 1 FROM worker_profiles "
            "WHERE worker_profiles.id = tasks.worker_profile_id))"
        )
    ).scalar_one()
    if unassignable_running_task_count:
        raise RuntimeError("Cannot pin issues: a running task has no available worker profile")

    # A mutable legacy default is not proof of where the Issue workspace lives.
    # Remove only unavailable defaults first; the execution-history steps below
    # may deliberately choose a disabled profile that owns an existing workspace.
    conn.execute(
        sa.text(
            "UPDATE issues SET default_worker_profile_id = NULL "
            "WHERE default_worker_profile_id IS NOT NULL AND NOT EXISTS ("
            "SELECT 1 FROM worker_profiles "
            "WHERE worker_profiles.id = issues.default_worker_profile_id "
            "AND worker_profiles.enabled = true)"
        )
    )

    # A currently running task is the strongest ownership signal. The conflict
    # guard above guarantees that all running tasks for one Issue use one Worker.
    conn.execute(
        sa.text(
            "UPDATE issues SET default_worker_profile_id = ("
            "SELECT tasks.worker_profile_id FROM tasks "
            "WHERE tasks.issue_id = issues.id AND tasks.status = 'running' "
            "AND tasks.worker_profile_id IS NOT NULL "
            "ORDER BY tasks.started_at DESC NULLS LAST, tasks.id DESC LIMIT 1"
            ") WHERE EXISTS (SELECT 1 FROM tasks WHERE tasks.issue_id = issues.id "
            "AND tasks.status = 'running' AND tasks.worker_profile_id IS NOT NULL)"
        )
    )

    # Otherwise preserve the daemon that most recently ran work for the Issue.
    # This takes precedence over the mutable legacy default and is the best
    # available owner signal for existing repo/Claude/shared directories.
    conn.execute(
        sa.text(
            "UPDATE issues SET default_worker_profile_id = ("
            "SELECT tasks.worker_profile_id FROM tasks "
            "WHERE tasks.issue_id = issues.id AND tasks.worker_profile_id IS NOT NULL "
            "AND EXISTS (SELECT 1 FROM worker_profiles "
            "WHERE worker_profiles.id = tasks.worker_profile_id) "
            "AND tasks.started_at IS NOT NULL "
            "ORDER BY tasks.started_at DESC, tasks.id DESC LIMIT 1"
            ") WHERE NOT EXISTS ("
            "SELECT 1 FROM tasks WHERE tasks.issue_id = issues.id "
            "AND tasks.status = 'running' AND tasks.worker_profile_id IS NOT NULL"
            ") AND EXISTS ("
            "SELECT 1 FROM tasks WHERE tasks.issue_id = issues.id "
            "AND tasks.worker_profile_id IS NOT NULL AND tasks.started_at IS NOT NULL "
            "AND EXISTS (SELECT 1 FROM worker_profiles "
            "WHERE worker_profiles.id = tasks.worker_profile_id))"
        )
    )

    # Issues without execution history use the first queued/pending Worker so the
    # oldest already-planned task remains executable. Any other pending Worker is
    # failed below instead of silently violating the new affinity invariant.
    conn.execute(
        sa.text(
            "UPDATE issues SET default_worker_profile_id = ("
            "SELECT tasks.worker_profile_id FROM tasks "
            "WHERE tasks.issue_id = issues.id AND tasks.worker_profile_id IS NOT NULL "
            "AND tasks.status IN ('pending', 'queued') "
            "AND EXISTS (SELECT 1 FROM worker_profiles "
            "WHERE worker_profiles.id = tasks.worker_profile_id) "
            "ORDER BY CASE WHEN tasks.status = 'queued' THEN 0 ELSE 1 END, tasks.id ASC "
            "LIMIT 1) WHERE NOT EXISTS ("
            "SELECT 1 FROM tasks WHERE tasks.issue_id = issues.id "
            "AND tasks.status = 'running' AND tasks.worker_profile_id IS NOT NULL) "
            "AND NOT EXISTS ("
            "SELECT 1 FROM tasks WHERE tasks.issue_id = issues.id "
            "AND tasks.worker_profile_id IS NOT NULL AND tasks.started_at IS NOT NULL "
            "AND EXISTS (SELECT 1 FROM worker_profiles "
            "WHERE worker_profiles.id = tasks.worker_profile_id)) "
            "AND EXISTS (SELECT 1 FROM tasks WHERE tasks.issue_id = issues.id "
            "AND tasks.worker_profile_id IS NOT NULL "
            "AND tasks.status IN ('pending', 'queued') "
            "AND EXISTS (SELECT 1 FROM worker_profiles "
            "WHERE worker_profiles.id = tasks.worker_profile_id))"
        )
    )
    unpinned_issue_count = conn.execute(
        sa.text("SELECT count(*) FROM issues WHERE default_worker_profile_id IS NULL")
    ).scalar_one()
    if unpinned_issue_count:
        fallback_worker_id = conn.execute(
            sa.text(
                "SELECT id FROM worker_profiles WHERE enabled = true "
                "ORDER BY is_default DESC, id ASC LIMIT 1"
            )
        ).scalar()
        if fallback_worker_id is None:
            raise RuntimeError("Cannot pin existing issues: no enabled worker profile exists")
        conn.execute(
            sa.text(
                "UPDATE issues SET default_worker_profile_id = :worker_id "
                "WHERE default_worker_profile_id IS NULL"
            ),
            {"worker_id": fallback_worker_id},
        )

    conn.execute(
        sa.text(
            "UPDATE tasks SET status = 'failed', "
            "error_message = 'Worker differs from the Issue affinity selected during upgrade; "
            "retry this task to use the pinned Worker', "
            "completed_at = COALESCE(completed_at, CURRENT_TIMESTAMP), "
            "updated_at = CURRENT_TIMESTAMP FROM issues "
            "WHERE tasks.issue_id = issues.id "
            "AND tasks.status IN ('pending', 'queued') "
            "AND tasks.worker_profile_id IS DISTINCT FROM issues.default_worker_profile_id"
        )
    )

    op.drop_index("ix_issues_default_worker_profile_id", table_name="issues")
    op.drop_constraint(
        "issues_default_worker_profile_id_fkey",
        "issues",
        type_="foreignkey",
    )
    op.alter_column(
        "issues",
        "default_worker_profile_id",
        new_column_name="worker_profile_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.create_foreign_key(
        "issues_worker_profile_id_fkey",
        "issues",
        "worker_profiles",
        ["worker_profile_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_issues_worker_profile_id", "issues", ["worker_profile_id"])

    op.add_column("issues", sa.Column("workspace_last_used_at", sa.DateTime(), nullable=True))
    op.add_column(
        "issues", sa.Column("workspace_delete_attempted_at", sa.DateTime(), nullable=True)
    )
    op.add_column("issues", sa.Column("workspace_deleted_at", sa.DateTime(), nullable=True))
    op.add_column("issues", sa.Column("workspace_delete_error", sa.Text(), nullable=True))
    op.add_column("tasks", sa.Column("worker_metadata", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("tasks", "worker_metadata")
    op.drop_column("issues", "workspace_delete_error")
    op.drop_column("issues", "workspace_deleted_at")
    op.drop_column("issues", "workspace_delete_attempted_at")
    op.drop_column("issues", "workspace_last_used_at")

    op.drop_index("ix_issues_worker_profile_id", table_name="issues")
    op.drop_constraint("issues_worker_profile_id_fkey", "issues", type_="foreignkey")
    op.alter_column(
        "issues",
        "worker_profile_id",
        new_column_name="default_worker_profile_id",
        existing_type=sa.Integer(),
        nullable=True,
    )
    op.create_foreign_key(
        "issues_default_worker_profile_id_fkey",
        "issues",
        "worker_profiles",
        ["default_worker_profile_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_issues_default_worker_profile_id",
        "issues",
        ["default_worker_profile_id"],
    )
