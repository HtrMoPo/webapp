"""add harvest_claims and recent_oauth_callbacks

Revision ID: 9cbb44b7e82d
Revises: 873a082f1585
Create Date: 2026-07-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9cbb44b7e82d'
down_revision: Union[str, Sequence[str], None] = '873a082f1585'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "harvest_claims",
        sa.Column("key", sa.String(), primary_key=True),
        sa.Column("claimed_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "recent_oauth_callbacks",
        sa.Column("code", sa.String(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("recent_oauth_callbacks")
    op.drop_table("harvest_claims")
