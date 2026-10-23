"""create transformation table

Revision ID: f2a620be9810
Revises: a6fcaf6e5f3b
Create Date: 2026-10-23 17:58:32.689244

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f2a620be9810"
down_revision: str | Sequence[str] | None = "a6fcaf6e5f3b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "transformation",
        sa.Column("text_hash", sa.String(length=64), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("result", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("text_hash", name=op.f("pk_transformation")),
    )


def downgrade() -> None:
    op.drop_table("transformation")
