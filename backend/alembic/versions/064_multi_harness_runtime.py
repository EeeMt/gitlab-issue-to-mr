"""add multi-harness runtime data model

Revision ID: 064_multi_harness
Revises: 063_harness_runtime
Create Date: 2026-08-03
"""

from datetime import UTC, datetime
from typing import Sequence, Union
from uuid import uuid4

import sqlalchemy as sa

from alembic import op

revision: str = "064_multi_harness"
down_revision: Union[str, None] = "063_harness_runtime"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_LEGACY_SESSION_NAMESPACE = "legacy"


def _now() -> datetime:
    # All Codify DB columns use naive-UTC datetimes (see app.core.utcnow).
    return datetime.now(UTC).replace(tzinfo=None)


def upgrade() -> None:
    bind = op.get_bind()

    # ---- WorkerProfile: harness allowlist / default / constraints / digest ----
    op.add_column(
        "worker_profiles",
        sa.Column(
            "enabled_harnesses",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[\"claude\"]'"),
        ),
    )
    op.add_column(
        "worker_profiles",
        sa.Column(
            "default_harness_key",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'claude'"),
        ),
    )
    op.add_column(
        "worker_profiles",
        sa.Column(
            "harness_constraints",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    op.add_column(
        "worker_profiles",
        sa.Column("image_digest", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "worker_profiles",
        sa.Column(
            "harness_runtimes",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )

    # ---- AIProvider: model endpoint fields + credential ref ----
    op.add_column(
        "ai_providers",
        sa.Column(
            "provider_kind",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'anthropic_compatible'"),
        ),
    )
    op.add_column(
        "ai_providers",
        sa.Column(
            "wire_protocol",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'anthropic_messages'"),
        ),
    )
    op.add_column(
        "ai_providers",
        sa.Column("provider_driver", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "ai_providers",
        sa.Column(
            "provider_options",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    op.add_column(
        "ai_providers",
        sa.Column("credential_ref", sa.String(length=128), nullable=True),
    )

    # ---- TaskWorkerProfileSnapshot: frozen harness/endpoint/cli fields ----
    for column in (
        ("harness_key", sa.String(length=32)),
        ("harness_adapter_version", sa.String(length=64)),
        ("harness_adapter_digest", sa.String(length=64)),
        ("harness_config_snapshot", sa.JSON()),
        ("model_endpoint_snapshot", sa.JSON()),
        ("credential_ref", sa.String(length=128)),
        ("cli_source", sa.String(length=32)),
        ("cli_executable_path", sa.String(length=1024)),
        ("cli_version", sa.String(length=128)),
        ("cli_binary_digest", sa.String(length=64)),
        ("image_digest", sa.String(length=128)),
        ("runtime_contract_version", sa.String(length=64)),
        ("orchestration_version", sa.String(length=64)),
        ("runtime_bundle_digest", sa.String(length=64)),
    ):
        op.add_column("task_worker_profile_snapshots", sa.Column(*column, nullable=True))

    # ---- model_credentials: persistent, independently-rotatable credentials ----
    op.create_table(
        "model_credentials",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("ref", sa.String(length=128), nullable=False),
        sa.Column("secret_encrypted", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("provider_kind", sa.String(length=32), nullable=True),
        sa.Column("version_metadata", sa.JSON(), nullable=True),
        sa.Column("retired_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_model_credentials_ref",
        "model_credentials",
        ["ref"],
        unique=True,
    )

    # ---- issue_harness_sessions: per-issue/harness/namespace lineage ----
    op.create_table(
        "issue_harness_sessions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("issue_id", sa.Integer(), nullable=False),
        sa.Column("harness_key", sa.String(length=64), nullable=False),
        sa.Column("session_namespace", sa.String(length=128), nullable=False),
        sa.Column("session_id", sa.String(length=255), nullable=True),
        sa.Column("lineage_reason", sa.String(length=64), nullable=True),
        sa.Column("session_metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["issue_id"], ["issues.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "issue_id",
            "harness_key",
            "session_namespace",
            name="uq_issue_harness_session",
        ),
    )
    op.create_index(
        "ix_issue_harness_sessions_issue_id",
        "issue_harness_sessions",
        ["issue_id"],
        unique=False,
    )

    # ---- Backfill (idempotent) ----
    now = _now()

    # 1. Snapshots: default the harness to claude for historical rows.
    bind.execute(
        sa.text(
            "UPDATE task_worker_profile_snapshots SET harness_key = 'claude' "
            "WHERE harness_key IS NULL"
        )
    )

    # 2. Providers with a stored api_key -> independent ModelCredential.
    provider_rows = bind.execute(
        sa.text(
            "SELECT id, name, api_key, provider_kind FROM ai_providers "
            "WHERE api_key IS NOT NULL AND api_key != ''"
        )
    ).fetchall()
    for row in provider_rows:
        ref = f"cred-{row.id}-{uuid4().hex[:8]}"
        bind.execute(
            sa.text(
                "INSERT INTO model_credentials "
                "(name, ref, secret_encrypted, kind, status, provider_kind, created_at, updated_at) "
                "VALUES (:name, :ref, :secret, 'api_key', 'active', :provider_kind, :created, :updated)"
            ),
            {
                "name": f"{row.name} credential",
                "ref": ref,
                "secret": row.api_key,
                "provider_kind": row.provider_kind,
                "created": now,
                "updated": now,
            },
        )
        bind.execute(
            sa.text("UPDATE ai_providers SET credential_ref = :ref WHERE id = :id"),
            {"ref": ref, "id": row.id},
        )

    # 3. Issues: mirror the legacy Claude session into a namespaced lineage row.
    issue_rows = bind.execute(
        sa.text(
            "SELECT id, claude_session_id FROM issues "
            "WHERE claude_session_id IS NOT NULL AND claude_session_id != ''"
        )
    ).fetchall()
    for row in issue_rows:
        exists = bind.execute(
            sa.text(
                "SELECT 1 FROM issue_harness_sessions "
                "WHERE issue_id = :issue_id AND harness_key = 'claude' "
                "AND session_namespace = :namespace"
            ),
            {"issue_id": row.id, "namespace": _LEGACY_SESSION_NAMESPACE},
        ).fetchone()
        if exists:
            continue
        bind.execute(
            sa.text(
                "INSERT INTO issue_harness_sessions "
                "(issue_id, harness_key, session_namespace, session_id, lineage_reason, session_metadata, created_at, updated_at) "
                "VALUES (:issue_id, 'claude', :namespace, :session_id, 'legacy_backfill', :meta, :created, :updated)"
            ),
            {
                "issue_id": row.id,
                "namespace": _LEGACY_SESSION_NAMESPACE,
                "session_id": row.claude_session_id,
                "meta": '{"source":"legacy_backfill"}',
                "created": now,
                "updated": now,
            },
        )


def downgrade() -> None:
    bind = op.get_bind()
    # Explicitly clear provider credential refs before dropping the table.
    bind.execute(
        sa.text(
            "UPDATE ai_providers SET credential_ref = NULL WHERE credential_ref IS NOT NULL"
        )
    )
    op.drop_index("ix_issue_harness_sessions_issue_id", table_name="issue_harness_sessions")
    op.drop_table("issue_harness_sessions")
    op.drop_index("ix_model_credentials_ref", table_name="model_credentials")
    op.drop_table("model_credentials")
    for name in (
        "harness_key",
        "harness_adapter_version",
        "harness_adapter_digest",
        "harness_config_snapshot",
        "model_endpoint_snapshot",
        "credential_ref",
        "cli_source",
        "cli_executable_path",
        "cli_version",
        "cli_binary_digest",
        "image_digest",
        "runtime_contract_version",
        "orchestration_version",
        "runtime_bundle_digest",
    ):
        op.drop_column("task_worker_profile_snapshots", name)
    for name in (
        "credential_ref",
        "provider_options",
        "provider_driver",
        "wire_protocol",
        "provider_kind",
    ):
        op.drop_column("ai_providers", name)
    for name in (
        "harness_runtimes",
        "image_digest",
        "harness_constraints",
        "default_harness_key",
        "enabled_harnesses",
    ):
        op.drop_column("worker_profiles", name)
