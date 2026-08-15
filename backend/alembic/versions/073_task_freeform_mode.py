"""Add freeform task mode to the tasks check constraint

Revision ID: 073_task_freeform_mode
Revises: 072_shared_per_item_inheritance
Create Date: 2026-08-16

Extends ``ck_tasks_task_mode`` from ``execute/plan`` to
``execute/freeform/plan``. The ``tasks.task_mode`` server default stays
``execute``. No columns are added and no historical rows are backfilled; the
``deleted_task_statistics.task_mode`` archive is intentionally untouched.

The downgrade first maps every ``freeform`` row to ``execute`` and forces
``require_changes=false`` (the canonical freeform invariant), then restores the
binary ``execute/plan`` constraint. This is the designed, lossy degradation
semantic for reverting the freeform release.
"""

import sqlalchemy as sa

from alembic import op

revision = "073_task_freeform_mode"
down_revision = "072_shared_per_item_inheritance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_tasks_task_mode", "tasks", type_="check")
    op.create_check_constraint(
        "ck_tasks_task_mode",
        "tasks",
        "task_mode IN ('execute', 'freeform', 'plan')",
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE tasks SET task_mode = 'execute', require_changes = false "
            "WHERE task_mode = 'freeform'"
        )
    )
    op.drop_constraint("ck_tasks_task_mode", "tasks", type_="check")
    op.create_check_constraint(
        "ck_tasks_task_mode",
        "tasks",
        "task_mode IN ('execute', 'plan')",
    )
