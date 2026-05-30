from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot.db.models import Receipt, ReceiptItem


@dataclass
class ItemRow:
    """Plain item payload for persistence (keeps repository service-agnostic)."""

    name: str
    quantity: Decimal
    unit_price: Decimal
    total_price: Decimal
    category_id: int | None = None
    confidence: float = 0.0
    gtin: str | None = None
    ntin: str | None = None
    original_currency: str | None = None
    original_price: Decimal | None = None
    exchange_rate_id: int | None = None


@dataclass
class CategoryTotal:
    category_id: int | None
    total: Decimal


async def save_receipt_with_items(
    session: AsyncSession,
    *,
    member_id: int,
    shop_name: str | None,
    purchased_at: datetime,
    total_amount: Decimal,
    currency: str,
    photo_file_id: str,
    raw_claude_json: dict[str, Any],
    fiscal_id: str | None = None,
    dedup_key: str | None = None,
    items: list[ItemRow] | None = None,
) -> Receipt:
    """Persist a receipt and all its items in a single flush."""
    items = items or []
    receipt = Receipt(
        family_member_id=member_id,
        shop_name=shop_name,
        purchased_at=purchased_at,
        total_amount=total_amount,
        currency=currency,
        photo_file_id=photo_file_id,
        raw_claude_json=raw_claude_json,
        fiscal_id=fiscal_id,
        dedup_key=dedup_key,
    )
    receipt.items = [
        ReceiptItem(
            name=row.name,
            quantity=row.quantity,
            unit_price=row.unit_price,
            total_price=row.total_price,
            category_id=row.category_id,
            confidence=row.confidence,
            gtin=row.gtin,
            ntin=row.ntin,
            original_currency=row.original_currency,
            original_price=row.original_price,
            exchange_rate_id=row.exchange_rate_id,
        )
        for row in items
    ]
    session.add(receipt)
    await session.flush()
    return receipt


async def get_receipt(session: AsyncSession, receipt_id: int) -> Receipt | None:
    result = await session.execute(
        select(Receipt)
        .where(Receipt.id == receipt_id)
        .options(selectinload(Receipt.items))
    )
    return result.scalar_one_or_none()


async def get_by_dedup_key(session: AsyncSession, dedup_key: str) -> Receipt | None:
    result = await session.execute(
        select(Receipt).where(Receipt.dedup_key == dedup_key)
    )
    return result.scalar_one_or_none()


async def update_receipt_date(
    session: AsyncSession, receipt_id: int, when: datetime
) -> Receipt | None:
    result = await session.execute(select(Receipt).where(Receipt.id == receipt_id))
    receipt = result.scalar_one_or_none()
    if receipt is None:
        return None
    receipt.purchased_at = when
    await session.flush()
    return receipt


async def update_item_category(
    session: AsyncSession,
    item_id: int,
    category_id: int,
    *,
    is_manual: bool = True,
) -> ReceiptItem | None:
    result = await session.execute(select(ReceiptItem).where(ReceiptItem.id == item_id))
    item = result.scalar_one_or_none()
    if item is None:
        return None
    item.category_id = category_id
    item.is_manual = is_manual
    await session.flush()
    return item


async def sum_by_category(
    session: AsyncSession,
    member_ids: list[int],
    start: date,
    end: date,
) -> list[CategoryTotal]:
    """Sum item totals grouped by category over [start, end) (half-open)."""
    if not member_ids:
        return []
    stmt = (
        select(
            ReceiptItem.category_id,
            func.coalesce(func.sum(ReceiptItem.total_price), 0),
        )
        .join(Receipt, ReceiptItem.receipt_id == Receipt.id)
        .where(
            Receipt.family_member_id.in_(member_ids),
            Receipt.purchased_at >= start,
            Receipt.purchased_at < end,
        )
        .group_by(ReceiptItem.category_id)
    )
    result = await session.execute(stmt)
    return [
        CategoryTotal(category_id=row[0], total=Decimal(row[1])) for row in result.all()
    ]
