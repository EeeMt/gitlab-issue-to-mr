"""add task issue_sequence and projected session lineage

Revision ID: 068_issue_sequence_lineage
Revises: 067_harness_key
Create Date: 2026-08-08

Two-phase hardening per design §5.3. Phase one (068) adds nullable sequence and
projected-lineage columns plus the ``issue_session_lineages`` table, backfills
historical ordering/lineage, and establishes a NULL-tolerant unique index so the
legacy Backend can keep inserting rows during the compatibility window.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "068_issue_sequence_lineage"
down_revision: Union[str, None] = "067_harness_key"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TERMINAL_STATUSES = ("completed", "failed", "cancelled")
LEGACY_NAMESPACE = "legacy"


def _session_namespace_for(harness_key: str, endpoint_fingerprint: str | None) -> str:
    """Secret-free namespace mirroring ``app.core.harness_sessions`` (state major 1)."""
    material = f"{harness_key}|{endpoint_fingerprint or ''}|state-1"
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]
    return f"{harness_key}-{digest}"


def _backfill_lineage(bind: sa.engine.Connection) -> None:
    """Backfill projected lineage and ``issue_session_lineages`` per design §5.2.

    Runs inside the migration transaction. Terminal tasks without a verifiable
    frozen snapshot map to the ``legacy`` namespace; active tasks missing one
    leave their projection NULL so the runtime ``sequence_repair_required``
    fail-closed protocol blocks the issue instead of guessing a Provider.
    """
    issue_ids = [
        row[0]
        for row in bind.execute(sa.text("SELECT id FROM issues ORDER BY id")).all()
    ]

    for issue_id in issue_ids:
        rows = bind.execute(
            sa.text(
                "SELECT id, status, session_mode, output_session_id, issue_sequence "
                "FROM tasks WHERE issue_id = :issue_id "
                "ORDER BY created_at ASC, id ASC"
            ),
            {"issue_id": issue_id},
        ).mappings().all()
        if not rows:
            continue

        task_ids = [row["id"] for row in rows]
        # Bind each id as its own placeholder: a single tuple/array parameter
        # renders as ``IN $1`` and is a syntax error under the asyncpg driver
        # used by alembic's async env.py.
        snapshot_placeholders = ", ".join(f":sid_{i}" for i in range(len(task_ids)))
        snapshots = {
            snap["task_id"]: snap
            for snap in bind.execute(
                sa.text(
                    "SELECT task_id, harness_key, model_endpoint_snapshot "
                    f"FROM task_worker_profile_snapshots WHERE task_id IN ({snapshot_placeholders})"
                ),
                {f"sid_{i}": task_id for i, task_id in enumerate(task_ids)},
            ).mappings().all()
        }

        # tail: last backfilled projection tuple for the issue.
        tail: dict | None = None
        # generation -> establishing task id; reset of gen 0 is None.
        generation_meta: dict[int, dict] = {}
        # (generation) -> [(task_id, issue_sequence, status, output_session_id)]
        generation_tasks: dict[int, list[dict]] = defaultdict(list)

        for row in rows:
            task_id = row["id"]
            snapshot = snapshots.get(task_id)
            session_mode = row["session_mode"] or "continue"
            status = row["status"]

            harness_key = None
            namespace = None
            if snapshot is not None and snapshot["harness_key"]:
                harness_key = snapshot["harness_key"]
                endpoint = snapshot["model_endpoint_snapshot"]
                fingerprint = None
                if isinstance(endpoint, dict):
                    fingerprint = endpoint.get("fingerprint")
                namespace = _session_namespace_for(harness_key, fingerprint)
            elif status in TERMINAL_STATUSES:
                harness_key = "legacy"
                namespace = LEGACY_NAMESPACE
            # Active task without a verifiable snapshot: leave projection NULL;
            # the runtime integrity protocol fails the issue closed.

            if harness_key is None:
                continue

            if tail is None:
                generation = 1 if session_mode == "fresh" else 0
                reset_task_id = task_id if session_mode == "fresh" else None
                reason = "initial"
            elif session_mode == "fresh":
                generation = tail["generation"] + 1
                reset_task_id = task_id
                reason = "fresh"
            elif harness_key == tail["harness_key"] and namespace == tail["namespace"]:
                generation = tail["generation"]
                reset_task_id = tail["reset_task_id"]
                reason = "inherited"
            else:
                # Historical namespace change: record an explicit compat reset.
                generation = tail["generation"] + 1
                reset_task_id = task_id
                reason = "legacy_namespace_change"

            bind.execute(
                sa.text(
                    "UPDATE tasks SET projected_harness_key = :harness, "
                    "projected_session_namespace = :namespace, "
                    "projected_lineage_generation = :generation, "
                    "projected_reset_task_id = :reset_task_id, "
                    "lineage_projection_reason = :reason WHERE id = :task_id"
                ),
                {
                    "harness": harness_key,
                    "namespace": namespace,
                    "generation": generation,
                    "reset_task_id": reset_task_id,
                    "reason": reason,
                    "task_id": task_id,
                },
            )

            tail = {
                "harness_key": harness_key,
                "namespace": namespace,
                "generation": generation,
                "reset_task_id": reset_task_id,
                "reason": reason,
            }
            generation_meta[generation] = {
                "harness_key": harness_key,
                "namespace": namespace,
                "reset_task_id": reset_task_id,
                "reason": reason,
            }
            generation_tasks[generation].append(
                {
                    "task_id": task_id,
                    "issue_sequence": row["issue_sequence"],
                    "status": status,
                    "output_session_id": row["output_session_id"],
                }
            )

        _backfill_session_lineages(bind, issue_id, generation_meta, generation_tasks)


def _backfill_session_lineages(
    bind: sa.engine.Connection,
    issue_id: int,
    generation_meta: dict[int, dict],
    generation_tasks: dict[int, list[dict]],
) -> None:
    """Populate ``issue_session_lineages`` from completed-task output evidence.

    A generation's ``session_id`` comes only from the latest completed Task that
    produced an output session in that generation; generation 0 with no output
    evidence may import an exactly matching legacy ``issue_harness_sessions``
    row. Reset generations never import legacy pointers.
    """
    for generation, meta in sorted(generation_meta.items()):
        tasks = generation_tasks.get(generation, [])
        # Latest completed producer by issue_sequence (None sequences sort last).
        producer = None
        for task in sorted(
            tasks,
            key=lambda t: (
                t["issue_sequence"] is not None,
                t["issue_sequence"] if t["issue_sequence"] is not None else -1,
            ),
            reverse=True,
        ):
            if task["status"] in TERMINAL_STATUSES and task["output_session_id"]:
                producer = task
                break

        session_id = None
        last_output_task_id = None
        last_output_issue_sequence = None
        lineage_reason = meta["reason"]

        if producer is not None:
            session_id = producer["output_session_id"]
            last_output_task_id = producer["task_id"]
            last_output_issue_sequence = producer["issue_sequence"]
        elif generation == 0:
            legacy = bind.execute(
                sa.text(
                    "SELECT session_id FROM issue_harness_sessions "
                    "WHERE issue_id = :issue_id AND harness_key = :harness "
                    "AND session_namespace = :namespace "
                    "AND session_id IS NOT NULL ORDER BY id DESC LIMIT 1"
                ),
                {
                    "issue_id": issue_id,
                    "harness": meta["harness_key"],
                    "namespace": meta["namespace"],
                },
            ).scalar()
            if legacy:
                session_id = legacy
                lineage_reason = "imported_legacy"

        bind.execute(
            sa.text(
                "INSERT INTO issue_session_lineages "
                "(issue_id, lineage_generation, harness_key, session_namespace, "
                "reset_task_id, session_id, last_output_task_id, "
                "last_output_issue_sequence, lineage_reason, created_at, updated_at) "
                "VALUES (:issue_id, :generation, :harness, :namespace, :reset_task_id, "
                ":session_id, :last_output_task_id, :last_output_issue_sequence, "
                ":lineage_reason, now(), now())"
            ),
            {
                "issue_id": issue_id,
                "generation": generation,
                "harness": meta["harness_key"],
                "namespace": meta["namespace"],
                "reset_task_id": meta["reset_task_id"],
                "session_id": session_id,
                "last_output_task_id": last_output_task_id,
                "last_output_issue_sequence": last_output_issue_sequence,
                "lineage_reason": lineage_reason,
            },
        )


def upgrade() -> None:
    bind = op.get_bind()

    op.add_column("tasks", sa.Column("issue_sequence", sa.Integer(), nullable=True))
    op.add_column(
        "tasks", sa.Column("projected_harness_key", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "tasks",
        sa.Column("projected_session_namespace", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "tasks", sa.Column("projected_lineage_generation", sa.Integer(), nullable=True)
    )
    op.add_column(
        "tasks", sa.Column("projected_reset_task_id", sa.Integer(), nullable=True)
    )
    op.add_column(
        "tasks",
        sa.Column("lineage_projection_reason", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "tasks", sa.Column("input_lineage_reason", sa.String(length=32), nullable=True)
    )
    op.create_foreign_key(
        "tasks_projected_reset_task_id_fkey",
        "tasks",
        "tasks",
        ["projected_reset_task_id"],
        ["id"],
        ondelete="NO ACTION",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_check_constraint(
        "ck_tasks_lineage_projection_reason",
        "tasks",
        "lineage_projection_reason IS NULL OR lineage_projection_reason IN "
        "('initial', 'inherited', 'fresh', 'legacy_namespace_change')",
    )
    op.create_check_constraint(
        "ck_tasks_input_lineage_reason",
        "tasks",
        "input_lineage_reason IS NULL OR input_lineage_reason IN "
        "('fresh', 'resumed', 'fresh_no_match')",
    )

    op.create_table(
        "issue_session_lineages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "issue_id",
            sa.Integer(),
            sa.ForeignKey("issues.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("lineage_generation", sa.Integer(), nullable=False),
        sa.Column("harness_key", sa.String(length=64), nullable=False),
        sa.Column("session_namespace", sa.String(length=128), nullable=False),
        sa.Column(
            "reset_task_id",
            sa.Integer(),
            sa.ForeignKey("tasks.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("session_id", sa.String(length=255), nullable=True),
        sa.Column(
            "last_output_task_id",
            sa.Integer(),
            sa.ForeignKey("tasks.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("last_output_issue_sequence", sa.Integer(), nullable=True),
        sa.Column("lineage_reason", sa.String(length=64), nullable=True),
        sa.Column("lineage_metadata", sa.JSON(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "issue_id",
            "lineage_generation",
            name="uq_issue_session_lineage_generation",
        ),
    )

    # Create the task indexes before the backfill UPDATEs populate the deferrable
    # ``projected_reset_task_id`` FK: PostgreSQL refuses CREATE INDEX on a table
    # with pending deferred-trigger events, and every non-null projection value
    # schedules one. At this point the new columns are still all NULL, so the
    # partial unique index has no rows to conflict with.
    op.create_index(
        "uq_tasks_issue_sequence",
        "tasks",
        ["issue_id", "issue_sequence"],
        unique=True,
        postgresql_where=sa.text("issue_sequence IS NOT NULL"),
    )
    op.create_index(
        "ix_tasks_issue_status_sequence",
        "tasks",
        ["issue_id", "status", "issue_sequence"],
    )
    op.create_index(
        "ix_tasks_issue_generation_sequence",
        "tasks",
        ["issue_id", "projected_lineage_generation", "issue_sequence"],
    )

    # Deterministic historical ordering: (created_at, id) is the pre-sequence
    # audit order and matches the runtime repair traversal.
    bind.execute(
        sa.text(
            "UPDATE tasks SET issue_sequence = ordered.rn FROM ("
            "SELECT id, row_number() OVER (PARTITION BY issue_id "
            "ORDER BY created_at ASC, id ASC) AS rn FROM tasks"
            ") AS ordered WHERE tasks.id = ordered.id"
        )
    )

    _backfill_lineage(bind)


def downgrade() -> None:
    op.drop_index("uq_tasks_issue_sequence", table_name="tasks")
    op.drop_index("ix_tasks_issue_status_sequence", table_name="tasks")
    op.drop_index("ix_tasks_issue_generation_sequence", table_name="tasks")
    op.drop_table("issue_session_lineages")
    op.drop_constraint(
        "tasks_projected_reset_task_id_fkey", "tasks", type_="foreignkey"
    )
    op.drop_constraint(
        "ck_tasks_input_lineage_reason", "tasks", type_="check"
    )
    op.drop_constraint(
        "ck_tasks_lineage_projection_reason", "tasks", type_="check"
    )
    op.create_foreign_key(
        "tasks_projected_reset_task_id_fkey",
        "tasks",
        "tasks",
        ["projected_reset_task_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.drop_column("tasks", "input_lineage_reason")
    op.drop_column("tasks", "lineage_projection_reason")
    op.drop_column("tasks", "projected_reset_task_id")
    op.drop_column("tasks", "projected_lineage_generation")
    op.drop_column("tasks", "projected_session_namespace")
    op.drop_column("tasks", "projected_harness_key")
    op.drop_column("tasks", "issue_sequence")
