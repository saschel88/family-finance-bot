from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Category, FamilyMember
from bot.db.repository import receipt as receipt_repo
from bot.db.repository.receipt import ItemRow


def _rows() -> list[ItemRow]:
    return [
        ItemRow(
            name="Хлеб",
            quantity=Decimal(1),
            unit_price=Decimal("250.00"),
            total_price=Decimal("250.00"),
            confidence=0.9,
        ),
        ItemRow(
            name="Молоко",
            quantity=Decimal(2),
            unit_price=Decimal("400.00"),
            total_price=Decimal("800.00"),
            category_id=None,
        ),
    ]


async def _save(
    db_session: AsyncSession,
    member: FamilyMember,
    *,
    when: datetime,
    rows: list[ItemRow],
    category_id: int | None = None,
) -> int:
    if category_id is not None:
        for r in rows:
            r.category_id = category_id
    receipt = await receipt_repo.save_receipt_with_items(
        db_session,
        member_id=member.id,
        shop_name="Магнум",
        purchased_at=when,
        total_amount=Decimal("1050.00"),
        currency="KZT",
        photo_file_id="file1",
        raw_claude_json={"x": 1},
        items=rows,
    )
    await db_session.commit()
    return receipt.id


async def test_save_receipt_with_items_atomic(
    db_session: AsyncSession, test_owner_member: FamilyMember
) -> None:
    receipt_id = await _save(
        db_session,
        test_owner_member,
        when=datetime(2026, 5, 10, tzinfo=UTC),
        rows=_rows(),
    )
    fetched = await receipt_repo.get_receipt(db_session, receipt_id)
    assert fetched is not None
    assert len(fetched.items) == 2
    assert fetched.shop_name == "Магнум"


async def test_update_item_category_sets_is_manual(
    db_session: AsyncSession,
    test_owner_member: FamilyMember,
    seed_categories: list[Category],
) -> None:
    receipt_id = await _save(
        db_session,
        test_owner_member,
        when=datetime(2026, 5, 10, tzinfo=UTC),
        rows=_rows(),
    )
    fetched = await receipt_repo.get_receipt(db_session, receipt_id)
    assert fetched is not None
    item_id = fetched.items[0].id
    updated = await receipt_repo.update_item_category(
        db_session, item_id, seed_categories[2].id
    )
    await db_session.commit()
    assert updated is not None
    assert updated.category_id == seed_categories[2].id
    assert updated.is_manual is True


async def test_update_missing_item_returns_none(
    db_session: AsyncSession, seed_categories: list[Category]
) -> None:
    result = await receipt_repo.update_item_category(
        db_session, 999999, seed_categories[0].id
    )
    assert result is None


async def test_fk_violation_on_bad_member(
    db_session: AsyncSession,
) -> None:
    with pytest.raises(IntegrityError):
        await receipt_repo.save_receipt_with_items(
            db_session,
            member_id=999999,
            shop_name=None,
            purchased_at=datetime(2026, 5, 10, tzinfo=UTC),
            total_amount=Decimal("1.00"),
            currency="KZT",
            photo_file_id="f",
            raw_claude_json={},
            items=[],
        )
        await db_session.commit()


async def test_sum_by_category_groups(
    db_session: AsyncSession,
    test_owner_member: FamilyMember,
    seed_categories: list[Category],
) -> None:
    await _save(
        db_session,
        test_owner_member,
        when=datetime(2026, 5, 10, tzinfo=UTC),
        rows=_rows(),
        category_id=seed_categories[0].id,
    )
    totals = await receipt_repo.sum_by_category(
        db_session,
        [test_owner_member.id],
        date(2026, 5, 1),
        date(2026, 6, 1),
    )
    assert len(totals) == 1
    assert totals[0].category_id == seed_categories[0].id
    assert totals[0].total == Decimal("1050.00")


async def test_sum_by_category_empty_members(
    db_session: AsyncSession,
) -> None:
    totals = await receipt_repo.sum_by_category(
        db_session, [], date(2026, 5, 1), date(2026, 6, 1)
    )
    assert totals == []


async def test_list_and_count_pagination(
    db_session: AsyncSession, test_owner_member: FamilyMember
) -> None:
    for i in range(3):
        await receipt_repo.save_receipt_with_items(
            db_session,
            member_id=test_owner_member.id,
            shop_name=f"Shop{i}",
            purchased_at=datetime(2026, 5, 10 + i, tzinfo=UTC),
            total_amount=Decimal("10.00"),
            currency="KZT",
            photo_file_id="f",
            raw_claude_json={},
            items=[],
        )
    await db_session.commit()
    ids = [test_owner_member.id]
    start, end = date(2026, 5, 1), date(2026, 6, 1)
    assert await receipt_repo.count_receipts(db_session, ids, start, end) == 3
    page0 = await receipt_repo.list_receipts(
        db_session, ids, start, end, limit=2, offset=0
    )
    page1 = await receipt_repo.list_receipts(
        db_session, ids, start, end, limit=2, offset=2
    )
    assert len(page0) == 2 and len(page1) == 1
    # Newest first.
    assert page0[0].purchased_at.date() == date(2026, 5, 12)


async def test_update_total_and_item_price_and_delete(
    db_session: AsyncSession,
    test_owner_member: FamilyMember,
    seed_categories: list[Category],
) -> None:
    receipt = await receipt_repo.save_receipt_with_items(
        db_session,
        member_id=test_owner_member.id,
        shop_name="Shop",
        purchased_at=datetime(2026, 5, 10, tzinfo=UTC),
        total_amount=Decimal("100.00"),
        currency="KZT",
        photo_file_id="f",
        raw_claude_json={},
        items=[
            receipt_repo.ItemRow(
                name="X",
                quantity=Decimal(2),
                unit_price=Decimal("50.00"),
                total_price=Decimal("100.00"),
            )
        ],
    )
    await db_session.commit()
    item_id = receipt.items[0].id

    await receipt_repo.update_receipt_total(db_session, receipt.id, Decimal("123.45"))
    updated_item = await receipt_repo.update_item_price(
        db_session, item_id, Decimal("80.00")
    )
    await db_session.commit()
    assert updated_item is not None
    assert updated_item.total_price == Decimal("80.00")
    assert updated_item.unit_price == Decimal("40.00")  # 80 / qty(2)

    rid = await receipt_repo.delete_item(db_session, item_id)
    await db_session.commit()
    assert rid == receipt.id
    assert await receipt_repo.delete_item(db_session, 999999) is None

    assert await receipt_repo.delete_receipt(db_session, receipt.id) is True
    await db_session.commit()
    assert await receipt_repo.get_receipt(db_session, receipt.id) is None
