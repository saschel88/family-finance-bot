"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-30

Creates the full schema (8 entities + required indexes) and seeds the 13
system categories. The category rows are literals here (not imported from
nct_category_map.json) so the migration stays self-contained and reproducible
across dev / prod / CI test databases.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


SYSTEM_CATEGORIES: list[dict[str, object]] = [
    {"name": "Продукты", "emoji": "🛒", "oktru_code": "01"},
    {"name": "Кафе и рестораны", "emoji": "🍕", "oktru_code": "56"},
    {"name": "Аптека", "emoji": "💊", "oktru_code": "21"},
    {"name": "Красота и гигиена", "emoji": "🧴", "oktru_code": "20"},
    {"name": "Одежда и обувь", "emoji": "👕", "oktru_code": "14"},
    {"name": "Дети", "emoji": "👶", "oktru_code": "88"},
    {"name": "Дом и хозяйство", "emoji": "🏠", "oktru_code": "46"},
    {"name": "Техника", "emoji": "📱", "oktru_code": "26"},
    {"name": "Авто", "emoji": "⛽", "oktru_code": "45"},
    {"name": "Образование", "emoji": "🎓", "oktru_code": "85"},
    {"name": "Развлечения", "emoji": "🎭", "oktru_code": "93"},
    {"name": "Путешествия", "emoji": "✈️", "oktru_code": "79"},
    {"name": "Прочее", "emoji": "💰", "oktru_code": None},
]


def upgrade() -> None:
    op.create_table(
        "family",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "category",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("emoji", sa.String(length=16), nullable=False),
        sa.Column(
            "parent_id", sa.Integer(), sa.ForeignKey("category.id"), nullable=True
        ),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("oktru_code", sa.String(length=8), nullable=True),
    )

    op.create_table(
        "exchange_rate",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("from_currency", sa.String(length=3), nullable=False),
        sa.Column(
            "to_currency",
            sa.String(length=3),
            nullable=False,
            server_default="KZT",
        ),
        sa.Column("rate", sa.Numeric(18, 6), nullable=False),
        sa.Column("rate_date", sa.Date(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "from_currency", "rate_date", name="uq_exchange_rate_from_date"
        ),
        sa.CheckConstraint(
            "source in ('nbk', 'manual')", name="ck_exchange_rate_source"
        ),
    )

    op.create_table(
        "family_member",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "family_id", sa.Integer(), sa.ForeignKey("family.id"), nullable=False
        ),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column(
            "joined_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("chat_id", name="uq_family_member_chat_id"),
        sa.CheckConstraint("role in ('owner', 'member')", name="ck_family_member_role"),
    )
    op.create_index("ix_family_member_family_id", "family_member", ["family_id"])

    op.create_table(
        "family_invite",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "family_id", sa.Integer(), sa.ForeignKey("family.id"), nullable=False
        ),
        sa.Column("token", sa.String(length=64), nullable=False),
        sa.Column(
            "created_by",
            sa.Integer(),
            sa.ForeignKey("family_member.id"),
            nullable=False,
        ),
        sa.Column(
            "used_by",
            sa.Integer(),
            sa.ForeignKey("family_member.id"),
            nullable=True,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("token", name="uq_family_invite_token"),
    )

    op.create_table(
        "receipt",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "family_member_id",
            sa.Integer(),
            sa.ForeignKey("family_member.id"),
            nullable=False,
        ),
        sa.Column("shop_name", sa.String(length=255), nullable=True),
        sa.Column("purchased_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("total_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column(
            "currency", sa.String(length=3), nullable=False, server_default="KZT"
        ),
        sa.Column("photo_file_id", sa.String(length=255), nullable=False),
        sa.Column(
            "raw_claude_json",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
        ),
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
    )
    op.create_index("ix_receipt_family_member_id", "receipt", ["family_member_id"])
    op.create_index("ix_receipt_purchased_at", "receipt", ["purchased_at"])

    op.create_table(
        "product_rule",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("pattern", sa.String(length=512), nullable=False),
        sa.Column(
            "category_id",
            sa.Integer(),
            sa.ForeignKey("category.id"),
            nullable=False,
        ),
        sa.Column("match_type", sa.String(length=16), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("usage_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "match_type in ('exact', 'contains', 'regex')",
            name="ck_product_rule_match_type",
        ),
    )
    op.create_index("ix_product_rule_pattern", "product_rule", ["pattern"])
    op.create_index("ix_product_rule_category_id", "product_rule", ["category_id"])

    op.create_table(
        "receipt_item",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "receipt_id",
            sa.Integer(),
            sa.ForeignKey("receipt.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("quantity", sa.Numeric(12, 3), nullable=False),
        sa.Column("unit_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("total_price", sa.Numeric(12, 2), nullable=False),
        sa.Column(
            "category_id",
            sa.Integer(),
            sa.ForeignKey("category.id"),
            nullable=True,
        ),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("is_manual", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("original_currency", sa.String(length=3), nullable=True),
        sa.Column("original_price", sa.Numeric(12, 2), nullable=True),
        sa.Column(
            "exchange_rate_id",
            sa.Integer(),
            sa.ForeignKey("exchange_rate.id"),
            nullable=True,
        ),
        sa.Column("nct_code", sa.String(length=64), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_receipt_item_receipt_id", "receipt_item", ["receipt_id"])
    op.create_index("ix_receipt_item_category_id", "receipt_item", ["category_id"])
    op.create_index("ix_receipt_item_nct_code", "receipt_item", ["nct_code"])

    # Seed system categories.
    category_table = sa.table(
        "category",
        sa.column("name", sa.String),
        sa.column("emoji", sa.String),
        sa.column("is_system", sa.Boolean),
        sa.column("oktru_code", sa.String),
    )
    op.bulk_insert(
        category_table,
        [{**row, "is_system": True} for row in SYSTEM_CATEGORIES],
    )


def downgrade() -> None:
    op.drop_table("receipt_item")
    op.drop_table("product_rule")
    op.drop_table("receipt")
    op.drop_table("family_invite")
    op.drop_table("family_member")
    op.drop_table("exchange_rate")
    op.drop_table("category")
    op.drop_table("family")
