"""add fingerprint to payload

Revision ID: 5783f19755a3
Revises: f2a620be9810
Create Date: 2026-10-23 18:26:29.403960

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5783f19755a3"
down_revision: str | Sequence[str] | None = "f2a620be9810"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # No backfill: nothing is deployed, and a local database with older payloads is reset with `docker compose down -v`.
    op.add_column("payload", sa.Column("fingerprint", sa.String(length=64), nullable=False))
    op.create_unique_constraint(op.f("uq_payload_fingerprint"), "payload", ["fingerprint"])


def downgrade() -> None:
    op.drop_constraint(op.f("uq_payload_fingerprint"), "payload", type_="unique")
    op.drop_column("payload", "fingerprint")
