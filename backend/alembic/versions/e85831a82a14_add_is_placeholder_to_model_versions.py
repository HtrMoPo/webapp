"""add is_placeholder to model_versions

Revision ID: e85831a82a14
Revises: 9cbb44b7e82d
Create Date: 2026-07-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e85831a82a14'
down_revision: Union[str, Sequence[str], None] = '9cbb44b7e82d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("model_versions") as batch_op:
        batch_op.add_column(sa.Column("is_placeholder", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("model_versions") as batch_op:
        batch_op.drop_column("is_placeholder")
