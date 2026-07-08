"""add is_admin to users

Revision ID: 873a082f1585
Revises: 696a40582633
Create Date: 2026-07-08 15:08:27.443301

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '873a082f1585'
down_revision: Union[str, Sequence[str], None] = '696a40582633'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("is_admin")
