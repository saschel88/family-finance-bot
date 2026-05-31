"""family-scoped custom categories

Revision ID: 0005_cat_family
Revises: 0004_dedup
Create Date: 2026-05-31

Add Category.family_id so families can define their own custom categories and
subcategories (parent_id already exists). NULL family_id = system/shared.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_cat_family"
down_revision = "0004_dedup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "category",
        sa.Column(
            "family_id",
            sa.Integer(),
            sa.ForeignKey("family.id"),
            nullable=True,
        ),
    )
    op.create_index("ix_category_family_id", "category", ["family_id"])


def downgrade() -> None:
    op.drop_index("ix_category_family_id", table_name="category")
    op.drop_column("category", "family_id")
