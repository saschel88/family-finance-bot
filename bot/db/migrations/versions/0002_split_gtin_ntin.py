"""split nct_code into gtin and ntin

Revision ID: 0002_gtin_ntin
Revises: 0001_initial
Create Date: 2026-05-30

GTIN (international barcode, from the receipt) and NTIN/KZTIN (Kazakhstan
national code, from the National Catalog) are distinct official identifiers
required by law. Replace the single nct_code column with explicit gtin / ntin
columns. Existing nct_code values are migrated into gtin (they originated as
barcodes), then the old column is dropped.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_gtin_ntin"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "receipt_item",
        sa.Column("gtin", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "receipt_item",
        sa.Column("ntin", sa.String(length=32), nullable=True),
    )
    op.execute("UPDATE receipt_item SET gtin = nct_code WHERE nct_code IS NOT NULL")
    op.drop_index("ix_receipt_item_nct_code", table_name="receipt_item")
    op.drop_column("receipt_item", "nct_code")
    op.create_index("ix_receipt_item_gtin", "receipt_item", ["gtin"])
    op.create_index("ix_receipt_item_ntin", "receipt_item", ["ntin"])


def downgrade() -> None:
    op.add_column(
        "receipt_item",
        sa.Column("nct_code", sa.String(length=64), nullable=True),
    )
    op.execute("UPDATE receipt_item SET nct_code = gtin WHERE gtin IS NOT NULL")
    op.drop_index("ix_receipt_item_ntin", table_name="receipt_item")
    op.drop_index("ix_receipt_item_gtin", table_name="receipt_item")
    op.drop_column("receipt_item", "ntin")
    op.drop_column("receipt_item", "gtin")
    op.create_index("ix_receipt_item_nct_code", "receipt_item", ["nct_code"])
