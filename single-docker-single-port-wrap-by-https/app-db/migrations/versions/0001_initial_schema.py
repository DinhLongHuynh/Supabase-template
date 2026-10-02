"""initial schema: items

Revision ID: 0001
Revises:
Create Date: 2026-10-01 12:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Times are naive UTC (models.UTCDateTime), hence plain DateTime here.
    op.create_table(
        "items",
        sa.Column("id", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("items_by_created_at", "items", ["created_at"])


def downgrade() -> None:
    op.drop_table("items")
