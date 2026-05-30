"""receipt fiscal_id and dedup key

Revision ID: 0004_dedup
Revises: 0003_product
Create Date: 2026-05-30

Add the receipt fiscal identifier and a per-family uniqueness key so the same
receipt is not counted twice. dedup_key is unique (NULLs allowed for legacy
rows; PostgreSQL treats NULLs as distinct).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_dedup"
down_revision = "0003_product"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "receipt", sa.Column("fiscal_id", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "receipt", sa.Column("dedup_key", sa.String(length=128), nullable=True)
    )
    op.create_unique_constraint("uq_receipt_dedup_key", "receipt", ["dedup_key"])


def downgrade() -> None:
    op.drop_constraint("uq_receipt_dedup_key", "receipt", type_="unique")
    op.drop_column("receipt", "dedup_key")
    op.drop_column("receipt", "fiscal_id")
