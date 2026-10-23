"""create payload table

Revision ID: a6fcaf6e5f3b
Revises:
Create Date: 2026-10-23 15:34:46.356503

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a6fcaf6e5f3b"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "payload",
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("output", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payload")),
    )


def downgrade() -> None:
    op.drop_table("payload")
