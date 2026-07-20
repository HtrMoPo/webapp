"""add downloads and views to model_records

Revision ID: 8ec085c16514
Revises: 69ce2421547d
Create Date: 2026-07-20 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8ec085c16514'
down_revision: Union[str, Sequence[str], None] = '69ce2421547d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("model_records") as batch_op:
        batch_op.add_column(sa.Column("downloads", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("views", sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("model_records") as batch_op:
        batch_op.drop_column("views")
        batch_op.drop_column("downloads")
