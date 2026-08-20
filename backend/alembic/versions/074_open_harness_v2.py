"""open-harness v2: model_protocol rename, command plane tables

Revision ID: 074_open_harness_v2
Revises: 073_task_freeform_mode
Create Date: 2026-08-21

Roll-forward V2 control plane foundation, per Phase 1 responsibility area 1
(open-harness-v2-phase1-design.md §1). Physical-only, no data translation:

- ``ai_providers.wire_protocol`` -> ``model_protocol`` via RENAME COLUMN (values
  unchanged, no legacy alias) plus a new nullable ``compat_profile``.
- ``worker_profiles.harness_options`` namespaced JSON column (default ``{}``).
- ``task_harness_attempts`` gains control gate / sequence / lease columns,
  backfilling ``control_state='disabled'`` for historical V1 attempts.
- New ``task_harness_commands`` table with attempt-scoped unique sequence and
  status/consistency checks; cascades on Task/attempt delete.

Existing V1 snapshots/attempts/receipts/archives are not rewritten. V1
PENDING/QUEUED idempotent rejection on handover is handled at runtime by the
execution policy, not by data transform here.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "074_open_harness_v2"
down_revision: Union[str, None] = "073_task_freeform_mode"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1.1 ai_providers: rename column (no data change) + new compat_profile.
    op.alter_column(
        "ai_providers",
        "wire_protocol",
        new_column_name="model_protocol",
        existing_type=sa.String(length=32),
        existing_nullable=False,
    )
    op.add_column(
        "ai_providers",
        sa.Column("compat_profile", sa.String(length=64), nullable=True),
    )

    # 1.2 worker_profiles: namespaced harness options.
    op.add_column(
        "worker_profiles",
        sa.Column(
            "harness_options",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )

    # 1.3 task_harness_attempts: control/sequence/lease columns.
    op.add_column(
        "task_harness_attempts",
        sa.Column("control_state", sa.String(length=16), nullable=False, server_default="disabled"),
    )
    op.add_column(
        "task_harness_attempts",
        sa.Column("next_command_sequence", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "task_harness_attempts",
        sa.Column("command_dispatch_owner", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "task_harness_attempts",
        sa.Column("command_dispatch_expires_at", sa.DateTime(), nullable=True),
    )
    op.create_check_constraint(
        "ck_task_harness_attempt_control_state",
        "task_harness_attempts",
        "control_state IN ('disabled','starting','accepting','closing','closed')",
    )
    op.create_check_constraint(
        "ck_task_harness_attempt_next_command_sequence",
        "task_harness_attempts",
        "next_command_sequence >= 1",
    )

    # 1.4 new task_harness_commands table.
    op.create_table(
        "task_harness_commands",
        sa.Column("command_id", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("attempt_id", sa.String(length=64), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("command_type", sa.String(length=16), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("payload_digest", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="queued"),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("delivery_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
        sa.Column("rejected_at", sa.DateTime(), nullable=True),
        sa.Column("rejection_code", sa.String(length=64), nullable=True),
        sa.Column("rejection_message", sa.Text(), nullable=True),
        sa.CheckConstraint("sequence_no >= 1", name="ck_task_harness_command_sequence_no"),
        sa.CheckConstraint(
            "command_type IN ('steer','follow_up')",
            name="ck_task_harness_command_type",
        ),
        sa.CheckConstraint(
            "status IN ('queued','delivered','rejected')",
            name="ck_task_harness_command_status",
        ),
        sa.CheckConstraint(
            "(status = 'queued') = (delivered_at IS NULL AND rejected_at IS NULL)",
            name="ck_task_harness_command_queued_consistency",
        ),
        sa.CheckConstraint(
            "(status = 'delivered') = (delivered_at IS NOT NULL)",
            name="ck_task_harness_command_delivered_consistency",
        ),
        sa.CheckConstraint(
            "(status = 'rejected') = (rejected_at IS NOT NULL)",
            name="ck_task_harness_command_rejected_consistency",
        ),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["task_harness_attempts.attempt_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("command_id"),
        sa.UniqueConstraint(
            "attempt_id", "sequence_no", name="uq_task_harness_command_attempt_seq"
        ),
    )
    op.create_index(
        "ix_task_harness_commands_task_id",
        "task_harness_commands",
        ["task_id"],
        unique=False,
    )
    op.create_index(
        "ix_task_harness_commands_attempt_id",
        "task_harness_commands",
        ["attempt_id"],
        unique=False,
    )
    op.create_index(
        "ix_task_harness_commands_attempt_status",
        "task_harness_commands",
        ["attempt_id", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_task_harness_commands_attempt_status",
        table_name="task_harness_commands",
    )
    op.drop_index(
        "ix_task_harness_commands_attempt_id",
        table_name="task_harness_commands",
    )
    op.drop_index(
        "ix_task_harness_commands_task_id",
        table_name="task_harness_commands",
    )
    op.drop_table("task_harness_commands")

    op.drop_constraint(
        "ck_task_harness_attempt_next_command_sequence",
        "task_harness_attempts",
        type_="check",
    )
    op.drop_constraint(
        "ck_task_harness_attempt_control_state",
        "task_harness_attempts",
        type_="check",
    )
    op.drop_column("task_harness_attempts", "command_dispatch_expires_at")
    op.drop_column("task_harness_attempts", "command_dispatch_owner")
    op.drop_column("task_harness_attempts", "next_command_sequence")
    op.drop_column("task_harness_attempts", "control_state")

    op.drop_column("worker_profiles", "harness_options")

    op.drop_column("ai_providers", "compat_profile")
    op.alter_column(
        "ai_providers",
        "model_protocol",
        new_column_name="wire_protocol",
        existing_type=sa.String(length=32),
        existing_nullable=False,
    )
