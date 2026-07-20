"""add schema_version to model_versions

Revision ID: 69ce2421547d
Revises: e85831a82a14
Create Date: 2026-07-20 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '69ce2421547d'
down_revision: Union[str, Sequence[str], None] = 'e85831a82a14'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("model_versions") as batch_op:
        batch_op.add_column(sa.Column("schema_version", sa.String(), nullable=False, server_default="v1"))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("model_versions") as batch_op:
        batch_op.drop_column("schema_version")
