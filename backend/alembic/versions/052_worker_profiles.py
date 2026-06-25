"""add worker profiles

Revision ID: 052_worker_profiles
Revises: 051_fix_retry_source_ondelete
Create Date: 2026-06-25
"""

import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import column, table

from app.core.task_prompt import (
    BUILT_IN_CI_AUTO_REPAIR_RUN_INSTRUCTION_TEMPLATE,
    BUILT_IN_EXECUTE_RUN_INSTRUCTION_TEMPLATE,
    BUILT_IN_PLAN_RUN_INSTRUCTION_TEMPLATE,
)


revision: str = "052_worker_profiles"
down_revision: Union[str, None] = "051_fix_retry_source_ondelete"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _config_value(conn, key: str, default: str) -> str:
    result = conn.execute(
        sa.text("SELECT value FROM system_config WHERE key = :key"),
        {"key": key},
    ).scalar()
    return default if result is None else result


def _parse_volume_mounts(raw_mounts: str) -> list[dict]:
    if not raw_mounts:
        return []
    try:
        mounts = json.loads(raw_mounts)
    except json.JSONDecodeError:
        return []
    return mounts if isinstance(mounts, list) else []


def _empty_json_array_default() -> sa.TextClause:
    if op.get_context().dialect.name == "postgresql":
        return sa.text("'[]'::json")
    return sa.text("'[]'")


def upgrade() -> None:
    op.create_table("worker_profiles",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("image", sa.String(length=255), nullable=False),
        sa.Column(
            "volume_mounts",
            sa.JSON(),
            nullable=False,
            server_default=_empty_json_array_default(),
        ),
        sa.Column("pre_script", sa.Text(), nullable=False, server_default=""),
        sa.Column("post_script", sa.Text(), nullable=False, server_default=""),
        sa.Column("default_execute_run_instruction_template", sa.Text(), nullable=False),
        sa.Column("default_plan_run_instruction_template", sa.Text(), nullable=False),
        sa.Column("ci_auto_repair_run_instruction_template", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("name", name="uq_worker_profiles_name"),
    )
    op.create_index(
        "uq_worker_profiles_default",
        "worker_profiles",
        ["is_default"],
        unique=True,
        postgresql_where=sa.text("is_default = true"),
        sqlite_where=sa.text("is_default = true"),
    )

    op.create_table("worker_profile_environment_variables",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("worker_profile_id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("is_secret", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["worker_profile_id"],
            ["worker_profiles.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "uq_worker_profile_environment_key",
        "worker_profile_environment_variables",
        ["worker_profile_id", "key"],
        unique=True,
    )
    op.create_index(
        "ix_worker_profile_environment_variables_worker_profile_id",
        "worker_profile_environment_variables",
        ["worker_profile_id"],
    )

    op.add_column("issues", sa.Column("default_worker_profile_id", sa.Integer(), nullable=True))
    op.add_column("issues", sa.Column("default_provider_id", sa.Integer(), nullable=True))
    op.add_column("tasks", sa.Column("worker_profile_id", sa.Integer(), nullable=True))

    op.create_foreign_key(
        "issues_default_worker_profile_id_fkey",
        "issues",
        "worker_profiles",
        ["default_worker_profile_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "issues_default_provider_id_fkey",
        "issues",
        "ai_providers",
        ["default_provider_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "tasks_worker_profile_id_fkey",
        "tasks",
        "worker_profiles",
        ["worker_profile_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_issues_default_worker_profile_id", "issues", ["default_worker_profile_id"])
    op.create_index("ix_issues_default_provider_id", "issues", ["default_provider_id"])
    op.create_index("ix_tasks_worker_profile_id", "tasks", ["worker_profile_id"])

    op.create_table("task_worker_profile_snapshots",
        sa.Column("task_id", sa.Integer(), primary_key=True),
        sa.Column("worker_profile_id", sa.Integer(), nullable=True),
        sa.Column("profile_name", sa.String(length=100), nullable=False),
        sa.Column("image", sa.String(length=255), nullable=False),
        sa.Column(
            "volume_mounts",
            sa.JSON(),
            nullable=False,
            server_default=_empty_json_array_default(),
        ),
        sa.Column(
            "environment_variables",
            sa.JSON(),
            nullable=False,
            server_default=_empty_json_array_default(),
        ),
        sa.Column("pre_script", sa.Text(), nullable=False, server_default=""),
        sa.Column("post_script", sa.Text(), nullable=False, server_default=""),
        sa.Column("default_execute_run_instruction_template", sa.Text(), nullable=False),
        sa.Column("default_plan_run_instruction_template", sa.Text(), nullable=False),
        sa.Column("ci_auto_repair_run_instruction_template", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["worker_profile_id"], ["worker_profiles.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_task_worker_profile_snapshots_worker_profile_id",
        "task_worker_profile_snapshots",
        ["worker_profile_id"],
    )

    conn = op.get_bind()
    default_provider_id = conn.execute(
        sa.text(
            "SELECT id FROM ai_providers "
            "WHERE is_default = true AND is_disabled = false "
            "LIMIT 1"
        )
    ).scalar()

    worker_profile_table = table(
        "worker_profiles",
        column("name"),
        column("description"),
        column("enabled"),
        column("is_default"),
        column("image"),
        column("volume_mounts"),
        column("pre_script"),
        column("post_script"),
        column("default_execute_run_instruction_template"),
        column("default_plan_run_instruction_template"),
        column("ci_auto_repair_run_instruction_template"),
    )
    raw_mounts = _config_value(conn, "worker_volume_mounts", "")
    conn.execute(
        worker_profile_table.insert().values(
            name="Default Worker",
            description="Migrated default worker profile",
            enabled=True,
            is_default=True,
            image=_config_value(conn, "worker_image", "codify-worker:latest"),
            volume_mounts=_parse_volume_mounts(raw_mounts),
            pre_script=_config_value(conn, "worker_pre_script", ""),
            post_script=_config_value(conn, "worker_post_script", ""),
            default_execute_run_instruction_template=_config_value(
                conn,
                "default_execute_run_instruction_template",
                BUILT_IN_EXECUTE_RUN_INSTRUCTION_TEMPLATE,
            ),
            default_plan_run_instruction_template=_config_value(
                conn,
                "default_plan_run_instruction_template",
                BUILT_IN_PLAN_RUN_INSTRUCTION_TEMPLATE,
            ),
            ci_auto_repair_run_instruction_template=_config_value(
                conn,
                "ci_auto_repair_run_instruction_template",
                BUILT_IN_CI_AUTO_REPAIR_RUN_INSTRUCTION_TEMPLATE,
            ),
        )
    )
    default_worker_id = conn.execute(
        sa.text("SELECT id FROM worker_profiles WHERE is_default = true LIMIT 1")
    ).scalar()

    conn.execute(
        sa.text(
            "INSERT INTO worker_profile_environment_variables "
            "(worker_profile_id, key, value, is_secret, created_at, updated_at) "
            "SELECT :profile_id, key, value, is_secret, created_at, updated_at "
            "FROM worker_environment_variables"
        ),
        {"profile_id": default_worker_id},
    )
    conn.execute(
        sa.text("UPDATE issues SET default_worker_profile_id = :profile_id"),
        {"profile_id": default_worker_id},
    )
    if default_provider_id is not None:
        conn.execute(
            sa.text("UPDATE issues SET default_provider_id = :provider_id"),
            {"provider_id": default_provider_id},
        )


def downgrade() -> None:
    op.drop_index(
        "ix_task_worker_profile_snapshots_worker_profile_id",
        table_name="task_worker_profile_snapshots",
    )
    op.drop_table("task_worker_profile_snapshots")
    op.drop_index("ix_tasks_worker_profile_id", table_name="tasks")
    op.drop_constraint("tasks_worker_profile_id_fkey", "tasks", type_="foreignkey")
    op.drop_column("tasks", "worker_profile_id")
    op.drop_index("ix_issues_default_provider_id", table_name="issues")
    op.drop_index("ix_issues_default_worker_profile_id", table_name="issues")
    op.drop_constraint("issues_default_provider_id_fkey", "issues", type_="foreignkey")
    op.drop_constraint("issues_default_worker_profile_id_fkey", "issues", type_="foreignkey")
    op.drop_column("issues", "default_provider_id")
    op.drop_column("issues", "default_worker_profile_id")
    op.drop_index(
        "ix_worker_profile_environment_variables_worker_profile_id",
        table_name="worker_profile_environment_variables",
    )
    op.drop_index(
        "uq_worker_profile_environment_key",
        table_name="worker_profile_environment_variables",
    )
    op.drop_table("worker_profile_environment_variables")
    op.drop_index("uq_worker_profiles_default", table_name="worker_profiles")
    op.drop_table("worker_profiles")
