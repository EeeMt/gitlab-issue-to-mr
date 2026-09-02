"""Remove the unused provider driver field.

Revision ID: 078_remove_provider_driver
Revises: 077_v2_worker_kit_identity
"""

from typing import Sequence, Union

from alembic import op

revision: str = "078_remove_provider_driver"
down_revision: Union[str, None] = "077_v2_worker_kit_identity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "DELETE FROM ai_providers "
        "WHERE provider_kind = 'openai_compatible' "
        "AND model_protocol = 'anthropic_messages'"
    )
    op.drop_column("ai_providers", "provider_driver")


def downgrade() -> None:
    raise RuntimeError("078_remove_provider_driver is roll-forward-only; restore from backup")
