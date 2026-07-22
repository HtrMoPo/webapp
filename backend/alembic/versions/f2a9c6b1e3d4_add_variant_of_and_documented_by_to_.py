"""add variant_of and documented_by to model_records

Revision ID: f2a9c6b1e3d4
Revises: c1a4e7f39b02
Create Date: 2026-07-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f2a9c6b1e3d4'
down_revision: Union[str, Sequence[str], None] = 'c1a4e7f39b02'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("model_records") as batch_op:
        batch_op.add_column(sa.Column("variant_of_doi", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("variant_of_record_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_model_records_variant_of_record_id",
            "model_records",
            ["variant_of_record_id"],
            ["id"],
        )
        batch_op.add_column(
            sa.Column("documented_by", sa.JSON(), nullable=False, server_default="[]")
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("model_records") as batch_op:
        batch_op.drop_column("documented_by")
        batch_op.drop_constraint(
            "fk_model_records_variant_of_record_id", type_="foreignkey"
        )
        batch_op.drop_column("variant_of_record_id")
        batch_op.drop_column("variant_of_doi")
