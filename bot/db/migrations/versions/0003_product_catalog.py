"""local product catalog

Revision ID: 0003_product
Revises: 0002_gtin_ntin
Create Date: 2026-05-30

A global product catalog keyed by GTIN/NTIN to reduce external National
Catalog calls and to remember manual category corrections by identifier.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_product"
down_revision = "0002_gtin_ntin"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "product",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("gtin", sa.String(length=32), nullable=True),
        sa.Column("ntin", sa.String(length=32), nullable=True),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column(
            "category_id",
            sa.Integer(),
            sa.ForeignKey("category.id"),
            nullable=False,
        ),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("usage_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("gtin", name="uq_product_gtin"),
        sa.UniqueConstraint("ntin", name="uq_product_ntin"),
        sa.CheckConstraint(
            "gtin IS NOT NULL OR ntin IS NOT NULL",
            name="ck_product_has_identifier",
        ),
        sa.CheckConstraint(
            "source in ('manual', 'nct', 'llm')", name="ck_product_source"
        ),
    )
    op.create_index("ix_product_gtin", "product", ["gtin"])
    op.create_index("ix_product_ntin", "product", ["ntin"])


def downgrade() -> None:
    op.drop_index("ix_product_ntin", table_name="product")
    op.drop_index("ix_product_gtin", table_name="product")
    op.drop_table("product")
