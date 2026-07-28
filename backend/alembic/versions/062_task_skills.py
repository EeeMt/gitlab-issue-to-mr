"""add globally managed skills and task snapshots

Revision ID: 062_task_skills
Revises: 061_task_run_archive_retention
Create Date: 2026-07-28
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "062_task_skills"
down_revision: Union[str, None] = "061_task_run_archive_retention"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "skill_versions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("skill_md", sa.Text(), nullable=False),
        sa.Column("files", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("package_size_bytes", sa.Integer(), nullable=False),
        sa.Column("digest", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_skill_versions_digest",
        "skill_versions",
        ["digest"],
        unique=False,
    )
    op.create_table(
        "skills",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("current_version_id", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["current_version_id"],
            ["skill_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index(
        "ix_skills_current_version_id",
        "skills",
        ["current_version_id"],
        unique=False,
    )
    op.create_table(
        "worker_profile_skills",
        sa.Column("worker_profile_id", sa.Integer(), nullable=False),
        sa.Column("skill_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["skill_id"],
            ["skills.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["worker_profile_id"],
            ["worker_profiles.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("worker_profile_id", "skill_id"),
    )
    op.create_index(
        "ix_worker_profile_skills_skill_id",
        "worker_profile_skills",
        ["skill_id"],
        unique=False,
    )
    op.create_table(
        "task_skill_version_references",
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("skill_id", sa.Integer(), nullable=True),
        sa.Column("skill_version_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "position >= 0",
            name="ck_task_skill_version_reference_position",
        ),
        sa.ForeignKeyConstraint(
            ["skill_id"],
            ["skills.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["skill_version_id"],
            ["skill_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["task_worker_profile_snapshots.task_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("task_id", "position"),
    )
    op.create_index(
        "ix_task_skill_version_references_skill_id",
        "task_skill_version_references",
        ["skill_id"],
        unique=False,
    )
    op.create_index(
        "ix_task_skill_version_references_skill_version_id",
        "task_skill_version_references",
        ["skill_version_id"],
        unique=False,
    )
    op.add_column(
        "task_worker_profile_snapshots",
        sa.Column(
            "skill_selection_source",
            sa.String(length=16),
            server_default=sa.text("'profile'"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("task_worker_profile_snapshots", "skill_selection_source")
    op.drop_index(
        "ix_task_skill_version_references_skill_version_id",
        table_name="task_skill_version_references",
    )
    op.drop_index(
        "ix_task_skill_version_references_skill_id",
        table_name="task_skill_version_references",
    )
    op.drop_table("task_skill_version_references")
    op.drop_index("ix_worker_profile_skills_skill_id", table_name="worker_profile_skills")
    op.drop_table("worker_profile_skills")
    op.drop_index("ix_skills_current_version_id", table_name="skills")
    op.drop_table("skills")
    op.drop_index("ix_skill_versions_digest", table_name="skill_versions")
    op.drop_table("skill_versions")
