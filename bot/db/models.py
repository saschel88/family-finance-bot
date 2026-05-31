from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class Family(Base):
    __tablename__ = "family"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    members: Mapped[list[FamilyMember]] = relationship(
        back_populates="family", cascade="all, delete-orphan"
    )


class FamilyMember(Base):
    __tablename__ = "family_member"
    __table_args__ = (
        UniqueConstraint("chat_id", name="uq_family_member_chat_id"),
        Index("ix_family_member_family_id", "family_id"),
        CheckConstraint("role in ('owner', 'member')", name="ck_family_member_role"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    family_id: Mapped[int] = mapped_column(ForeignKey("family.id"))
    chat_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    name: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16))
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    family: Mapped[Family] = relationship(back_populates="members")


class FamilyInvite(Base):
    __tablename__ = "family_invite"
    __table_args__ = (UniqueConstraint("token", name="uq_family_invite_token"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    family_id: Mapped[int] = mapped_column(ForeignKey("family.id"))
    token: Mapped[str] = mapped_column(String(64), unique=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("family_member.id"))
    used_by: Mapped[int | None] = mapped_column(
        ForeignKey("family_member.id"), nullable=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Category(Base):
    __tablename__ = "category"
    __table_args__ = (Index("ix_category_family_id", "family_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    emoji: Mapped[str] = mapped_column(String(16))
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("category.id"), nullable=True
    )
    # NULL = system (shared by all); set = a family's own custom category.
    family_id: Mapped[int | None] = mapped_column(
        ForeignKey("family.id"), nullable=True
    )
    is_system: Mapped[bool] = mapped_column(default=False)
    # oktru_code drives NCT category mapping (see nct_category_map.json).
    oktru_code: Mapped[str | None] = mapped_column(String(8), nullable=True)


class Receipt(Base):
    __tablename__ = "receipt"
    __table_args__ = (
        UniqueConstraint("dedup_key", name="uq_receipt_dedup_key"),
        Index("ix_receipt_family_member_id", "family_member_id"),
        Index("ix_receipt_purchased_at", "purchased_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    family_member_id: Mapped[int] = mapped_column(ForeignKey("family_member.id"))
    shop_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    purchased_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="KZT")
    photo_file_id: Mapped[str] = mapped_column(String(255))
    # Receipt's fiscal identifier (КГД/ОФД), when printed.
    fiscal_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Per-family uniqueness key: "{family_id}:{fiscal_id|content-fingerprint}".
    dedup_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    raw_claude_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    items: Mapped[list[ReceiptItem]] = relationship(
        back_populates="receipt", cascade="all, delete-orphan"
    )


class ReceiptItem(Base):
    __tablename__ = "receipt_item"
    __table_args__ = (
        Index("ix_receipt_item_receipt_id", "receipt_id"),
        Index("ix_receipt_item_category_id", "category_id"),
        Index("ix_receipt_item_gtin", "gtin"),
        Index("ix_receipt_item_ntin", "ntin"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    receipt_id: Mapped[int] = mapped_column(ForeignKey("receipt.id"))
    name: Mapped[str] = mapped_column(String(512))
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    total_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("category.id"), nullable=True
    )
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    is_manual: Mapped[bool] = mapped_column(default=False)
    original_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    original_price: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    exchange_rate_id: Mapped[int | None] = mapped_column(
        ForeignKey("exchange_rate.id"), nullable=True
    )
    # Official catalog identifiers (legal requirement):
    #   gtin — international barcode printed on the receipt (from vision)
    #   ntin — Kazakhstan national code (NTIN/KZTIN), from NCT enrichment
    gtin: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ntin: Mapped[str | None] = mapped_column(String(32), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    receipt: Mapped[Receipt] = relationship(back_populates="items")


class ProductRule(Base):
    __tablename__ = "product_rule"
    __table_args__ = (
        Index("ix_product_rule_pattern", "pattern"),
        Index("ix_product_rule_category_id", "category_id"),
        CheckConstraint(
            "match_type in ('exact', 'contains', 'regex')",
            name="ck_product_rule_match_type",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    pattern: Mapped[str] = mapped_column(String(512))
    category_id: Mapped[int] = mapped_column(ForeignKey("category.id"))
    match_type: Mapped[str] = mapped_column(String(16))
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    usage_count: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Product(Base):
    """Local product catalog keyed by official identifiers (GTIN/NTIN).

    Global (shared across families) to maximize reuse and minimize external
    National Catalog calls. Each row maps an identifier to a category and a
    canonical name. `source` records provenance (manual > nct > llm) and gates
    overwrites in the repository upsert.
    """

    __tablename__ = "product"
    __table_args__ = (
        UniqueConstraint("gtin", name="uq_product_gtin"),
        UniqueConstraint("ntin", name="uq_product_ntin"),
        Index("ix_product_gtin", "gtin"),
        Index("ix_product_ntin", "ntin"),
        CheckConstraint(
            "gtin IS NOT NULL OR ntin IS NOT NULL",
            name="ck_product_has_identifier",
        ),
        CheckConstraint("source in ('manual', 'nct', 'llm')", name="ck_product_source"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    gtin: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ntin: Mapped[str | None] = mapped_column(String(32), nullable=True)
    name: Mapped[str] = mapped_column(String(512))
    category_id: Mapped[int] = mapped_column(ForeignKey("category.id"))
    source: Mapped[str] = mapped_column(String(16))
    usage_count: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ExchangeRate(Base):
    __tablename__ = "exchange_rate"
    __table_args__ = (
        UniqueConstraint(
            "from_currency", "rate_date", name="uq_exchange_rate_from_date"
        ),
        CheckConstraint("source in ('nbk', 'manual')", name="ck_exchange_rate_source"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    from_currency: Mapped[str] = mapped_column(String(3))
    to_currency: Mapped[str] = mapped_column(String(3), default="KZT")
    rate: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    rate_date: Mapped[date] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
