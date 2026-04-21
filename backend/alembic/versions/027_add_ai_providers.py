"""add ai_providers table and tasks.provider_id FK

Revision ID: 027_add_ai_providers
Revises: 026_add_filter_indexes
Create Date: 2026-04-16
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "027_add_ai_providers"
down_revision: Union[str, None] = "026_add_filter_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create ai_providers table
    op.create_table(
        "ai_providers",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("base_url", sa.Text, nullable=False),
        sa.Column("api_key", sa.Text, nullable=True),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("max_turns", sa.Integer, nullable=False, server_default="20"),
        sa.Column("system_prompt", sa.Text, nullable=True),
        sa.Column("is_default", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )

    # 2. Add provider_id FK to tasks
    op.add_column("tasks", sa.Column("provider_id", sa.Integer, nullable=True))
    op.create_foreign_key(
        "fk_tasks_provider_id",
        "tasks",
        "ai_providers",
        ["provider_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_tasks_provider_id", "tasks", ["provider_id"])

    # 3. Data migration: copy current system_config anthropic_* entries into a default provider
    conn = op.get_bind()

    # Read current settings from system_config
    rows = conn.execute(
        sa.text("SELECT key, value, value_type FROM system_config WHERE key IN "
                "('anthropic_base_url', 'anthropic_api_key', 'anthropic_model', 'claude_max_turns')")
    ).fetchall()

    config = {}
    for row in rows:
        config[row[0]] = row[1]

    # Only create default provider if there's at least a base_url or model configured
    base_url = config.get("anthropic_base_url", "http://localhost:11434/v1")
    api_key = config.get("anthropic_api_key")  # Already encrypted in system_config
    model = config.get("anthropic_model", "claude-sonnet-4-20250514")
    max_turns_str = config.get("claude_max_turns", "20")
    try:
        max_turns = int(max_turns_str)
    except (ValueError, TypeError):
        max_turns = 20

    conn.execute(
        sa.text(
            "INSERT INTO ai_providers (name, base_url, api_key, model, max_turns, is_default, created_at, updated_at) "
            "VALUES (:name, :base_url, :api_key, :model, :max_turns, :is_default, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ),
        {
            "name": "default",
            "base_url": base_url,
            "api_key": api_key,  # Preserve encrypted value as-is
            "model": model,
            "max_turns": max_turns,
            "is_default": True,
        },
    )


def downgrade() -> None:
    op.drop_index("ix_tasks_provider_id", table_name="tasks")
    op.drop_constraint("fk_tasks_provider_id", "tasks", type_="foreignkey")
    op.drop_column("tasks", "provider_id")
    op.drop_table("ai_providers")
