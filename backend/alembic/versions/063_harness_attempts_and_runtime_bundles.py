"""add Harness attempts and immutable runtime bundles

Revision ID: 063_harness_runtime
Revises: 062_task_skills
Create Date: 2026-08-01
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "063_harness_runtime"
down_revision: Union[str, None] = "062_task_skills"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "worker_runtime_bundles",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("digest", sa.String(length=64), nullable=False),
        sa.Column("bundle_bytes", sa.LargeBinary(), nullable=False),
        sa.Column("contract_version", sa.String(length=64), nullable=False),
        sa.Column("orchestration_version", sa.String(length=64), nullable=False),
        sa.Column("manifest", sa.JSON(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_worker_runtime_bundles_digest",
        "worker_runtime_bundles",
        ["digest"],
        unique=True,
    )
    op.add_column("tasks", sa.Column("runtime_bundle_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_tasks_runtime_bundle_id",
        "tasks",
        "worker_runtime_bundles",
        ["runtime_bundle_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_tasks_runtime_bundle_id", "tasks", ["runtime_bundle_id"], unique=False)
    op.create_table(
        "task_harness_attempts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("attempt_id", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("event_schema", sa.String(length=64), nullable=False),
        sa.Column("harness_key", sa.String(length=64), nullable=False),
        sa.Column("adapter_version", sa.String(length=64), nullable=False),
        sa.Column("cli_version", sa.String(length=128), nullable=True),
        sa.Column("last_seq", sa.Integer(), server_default="0", nullable=False),
        sa.Column("terminal_event_id", sa.String(length=64), nullable=True),
        sa.Column("terminal_event_type", sa.String(length=32), nullable=True),
        sa.Column("terminal_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("attempt_no >= 1", name="ck_task_harness_attempt_no"),
        sa.CheckConstraint("last_seq >= 0", name="ck_task_harness_attempt_last_seq"),
        sa.CheckConstraint(
            "terminal_event_type IS NULL OR terminal_event_type IN ('run.completed', 'run.failed')",
            name="ck_task_harness_attempt_terminal_type",
        ),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "attempt_no", name="uq_task_harness_attempt_no"),
    )
    op.create_index(
        "ix_task_harness_attempts_attempt_id",
        "task_harness_attempts",
        ["attempt_id"],
        unique=True,
    )
    op.create_index(
        "ix_task_harness_attempts_task_id",
        "task_harness_attempts",
        ["task_id"],
        unique=False,
    )
    op.create_table(
        "task_harness_event_receipts",
        sa.Column("attempt_id", sa.String(length=64), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("event_digest", sa.String(length=64), nullable=False),
        sa.Column("event", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("seq >= 1", name="ck_task_harness_event_receipt_seq"),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["task_harness_attempts.attempt_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("attempt_id", "seq"),
    )
    op.create_index(
        "ix_task_harness_event_receipts_event_id",
        "task_harness_event_receipts",
        ["event_id"],
        unique=True,
    )
    op.add_column(
        "task_ingest_cursors",
        sa.Column("attempt_id", sa.String(length=64), nullable=True),
    )
    op.create_foreign_key(
        "fk_task_ingest_cursors_attempt_id",
        "task_ingest_cursors",
        "task_harness_attempts",
        ["attempt_id"],
        ["attempt_id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_task_ingest_cursors_attempt_id",
        "task_ingest_cursors",
        ["attempt_id"],
        unique=False,
    )
    op.create_unique_constraint(
        "uq_attempt_ingest_cursor",
        "task_ingest_cursors",
        ["attempt_id", "stream_name"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_attempt_ingest_cursor", "task_ingest_cursors", type_="unique")
    op.drop_index("ix_task_ingest_cursors_attempt_id", table_name="task_ingest_cursors")
    op.drop_constraint(
        "fk_task_ingest_cursors_attempt_id",
        "task_ingest_cursors",
        type_="foreignkey",
    )
    op.drop_column("task_ingest_cursors", "attempt_id")
    op.drop_index(
        "ix_task_harness_event_receipts_event_id",
        table_name="task_harness_event_receipts",
    )
    op.drop_table("task_harness_event_receipts")
    op.drop_index("ix_task_harness_attempts_task_id", table_name="task_harness_attempts")
    op.drop_index("ix_task_harness_attempts_attempt_id", table_name="task_harness_attempts")
    op.drop_table("task_harness_attempts")
    op.drop_index("ix_tasks_runtime_bundle_id", table_name="tasks")
    op.drop_constraint("fk_tasks_runtime_bundle_id", "tasks", type_="foreignkey")
    op.drop_column("tasks", "runtime_bundle_id")
    op.drop_index("ix_worker_runtime_bundles_digest", table_name="worker_runtime_bundles")
    op.drop_table("worker_runtime_bundles")
