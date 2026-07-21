"""add obsoleted_by to model_records

Revision ID: c1a4e7f39b02
Revises: 8ec085c16514
Create Date: 2026-07-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c1a4e7f39b02'
down_revision: Union[str, Sequence[str], None] = '8ec085c16514'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("model_records") as batch_op:
        batch_op.add_column(sa.Column("obsoleted_by_doi", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("obsoleted_by_record_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_model_records_obsoleted_by_record_id",
            "model_records",
            ["obsoleted_by_record_id"],
            ["id"],
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("model_records") as batch_op:
        batch_op.drop_constraint(
            "fk_model_records_obsoleted_by_record_id", type_="foreignkey"
        )
        batch_op.drop_column("obsoleted_by_record_id")
        batch_op.drop_column("obsoleted_by_doi")
