"""Persist Pi native command dispatch/recovery evidence.

Revision ID: 075_pi_command_dispatch_journal
Revises: 074_open_harness_v2
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "075_pi_command_dispatch_journal"
down_revision: Union[str, None] = "074_open_harness_v2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "task_harness_attempts",
        sa.Column("awaiting_follow_up_turn", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("task_harness_attempts", sa.Column("pending_follow_up_command_id", sa.String(64)))
    op.add_column("task_harness_attempts", sa.Column("pending_follow_up_native_id", sa.String(128)))
    op.add_column(
        "task_harness_attempts",
        sa.Column("force_close_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "task_harness_commands", sa.Column("dispatch_started_at", sa.DateTime(), nullable=True)
    )
    op.add_column(
        "task_harness_commands",
        sa.Column("native_request_id", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "task_harness_commands", sa.Column("native_sent_at", sa.DateTime(), nullable=True)
    )
    op.add_column("task_harness_commands", sa.Column("native_ack_at", sa.DateTime(), nullable=True))
    op.add_column(
        "task_harness_commands", sa.Column("outcome_unknown_at", sa.DateTime(), nullable=True)
    )
    op.drop_constraint("ck_task_harness_command_status", "task_harness_commands", type_="check")
    op.drop_constraint(
        "ck_task_harness_command_queued_consistency", "task_harness_commands", type_="check"
    )
    op.create_check_constraint(
        "ck_task_harness_command_status",
        "task_harness_commands",
        "status IN ('queued','dispatching','delivered','rejected','outcome_unknown')",
    )
    op.alter_column("task_harness_attempts", "awaiting_follow_up_turn", server_default=None)
    op.alter_column("task_harness_attempts", "force_close_requested", server_default=None)
    op.create_check_constraint(
        "ck_task_harness_command_queued_consistency",
        "task_harness_commands",
        "(status IN ('queued','dispatching','outcome_unknown')) = (delivered_at IS NULL AND rejected_at IS NULL)",
    )
    op.create_check_constraint(
        "ck_task_harness_command_unknown_consistency",
        "task_harness_commands",
        "(status = 'outcome_unknown') = (outcome_unknown_at IS NOT NULL)",
    )


def downgrade() -> None:
    raise RuntimeError("075_pi_command_dispatch_journal is roll-forward-only; restore from backup to downgrade")
