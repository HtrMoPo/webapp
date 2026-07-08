"""nullable owner and source on model_records

Revision ID: 696a40582633
Revises: 27768895ca39
Create Date: 2026-07-08 14:57:28.941841

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '696a40582633'
down_revision: Union[str, Sequence[str], None] = '27768895ca39'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # SQLite has limited ALTER TABLE support, so both changes go through
    # batch mode (which rebuilds the table under the hood).
    with op.batch_alter_table("model_records") as batch_op:
        batch_op.add_column(sa.Column("source", sa.String(), nullable=False, server_default="app"))
        batch_op.alter_column("owner_user_id", existing_type=sa.INTEGER(), nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("model_records") as batch_op:
        batch_op.alter_column("owner_user_id", existing_type=sa.INTEGER(), nullable=False)
        batch_op.drop_column("source")
