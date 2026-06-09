"""add task event archive state tables

Revision ID: 034_add_task_event_archive_state
Revises: 033_add_usage_limits
Create Date: 2026-04-27
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "034_add_task_event_archive_state"
down_revision: Union[str, None] = "033_add_usage_limits"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "task_run_archives",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("archive_name", sa.String(length=255), nullable=False),
        sa.Column("archive_path", sa.Text(), nullable=False),
        sa.Column("archive_size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", name="uq_task_run_archives_task_id"),
    )
    op.create_index("ix_task_run_archives_task_id", "task_run_archives", ["task_id"], unique=False)

    op.create_table(
        "task_ingest_cursors",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("stream_name", sa.String(length=50), nullable=False),
        sa.Column("last_offset", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_sequence_no", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "stream_name", name="uq_task_ingest_cursor"),
    )
    op.create_index("ix_task_ingest_cursors_task_id", "task_ingest_cursors", ["task_id"], unique=False)

    op.create_table(
        "task_raw_log_chunks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("encoding", sa.String(length=20), nullable=False, server_default="identity"),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("char_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("byte_count", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "sequence_no", name="uq_task_raw_log_chunk_seq"),
    )
    op.create_index("ix_task_raw_log_chunks_task_id", "task_raw_log_chunks", ["task_id"], unique=False)

    op.create_table(
        "task_payloads",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("payload_kind", sa.String(length=50), nullable=False),
        sa.Column("encoding", sa.String(length=20), nullable=False, server_default="identity"),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("char_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("byte_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_task_payloads_task_id", "task_payloads", ["task_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_task_payloads_task_id", table_name="task_payloads")
    op.drop_table("task_payloads")

    op.drop_index("ix_task_raw_log_chunks_task_id", table_name="task_raw_log_chunks")
    op.drop_table("task_raw_log_chunks")

    op.drop_index("ix_task_ingest_cursors_task_id", table_name="task_ingest_cursors")
    op.drop_table("task_ingest_cursors")

    op.drop_index("ix_task_run_archives_task_id", table_name="task_run_archives")
    op.drop_table("task_run_archives")
