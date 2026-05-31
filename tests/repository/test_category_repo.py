from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Category, Family, FamilyMember, ReceiptItem
from bot.db.repository import category as category_repo
from bot.db.repository import receipt as receipt_repo


def _deti(cats: list[Category]) -> Category:
    return next(c for c in cats if c.name == "Дети")


async def test_family_scoping(
    db_session: AsyncSession, seed_categories: list[Category], test_family: Family
) -> None:
    deti = _deti(seed_categories)
    ilya = await category_repo.create_category(
        db_session, name="Илья", family_id=test_family.id, parent_id=deti.id
    )
    hobby = await category_repo.create_category(
        db_session, name="Хобби", family_id=test_family.id
    )
    await db_session.commit()

    system_only = await category_repo.list_categories(db_session)
    assert all(c.family_id is None for c in system_only)
    assert ilya.id not in {c.id for c in system_only}

    family = await category_repo.list_for_family(db_session, test_family.id)
    fam_ids = {c.id for c in family}
    assert ilya.id in fam_ids and hobby.id in fam_ids

    tops = {
        c.id for c in await category_repo.list_top_level(db_session, test_family.id)
    }
    assert hobby.id in tops  # custom top-level is an auto-classification candidate
    assert deti.id in tops
    assert ilya.id not in tops  # subcategory excluded from auto-classification

    children = await category_repo.list_children(db_session, deti.id)
    assert ilya.id in {c.id for c in children}
    assert await category_repo.top_level_ancestor(db_session, ilya.id) == deti.id


async def test_rename_and_delete_only_custom(
    db_session: AsyncSession, seed_categories: list[Category], test_family: Family
) -> None:
    deti = _deti(seed_categories)
    ilya = await category_repo.create_category(
        db_session, name="Илья", family_id=test_family.id, parent_id=deti.id
    )
    await db_session.commit()

    assert await category_repo.rename_category(db_session, deti.id, "X") is None
    renamed = await category_repo.rename_category(db_session, ilya.id, "Илюша")
    await db_session.commit()
    assert renamed is not None and renamed.name == "Илюша"

    assert await category_repo.delete_category(db_session, deti.id) is False
    assert await category_repo.delete_category(db_session, ilya.id) is True
    await db_session.commit()
    assert await category_repo.get_category(db_session, ilya.id) is None


async def test_delete_reassigns_items_to_parent(
    db_session: AsyncSession,
    seed_categories: list[Category],
    test_family: Family,
    test_owner_member: FamilyMember,
) -> None:
    deti = _deti(seed_categories)
    ilya = await category_repo.create_category(
        db_session, name="Илья", family_id=test_family.id, parent_id=deti.id
    )
    await db_session.commit()
    receipt = await receipt_repo.save_receipt_with_items(
        db_session,
        member_id=test_owner_member.id,
        shop_name="S",
        purchased_at=datetime(2026, 5, 1, tzinfo=UTC),
        total_amount=Decimal("100"),
        currency="KZT",
        photo_file_id="f",
        raw_claude_json={},
        items=[
            receipt_repo.ItemRow(
                name="x",
                quantity=Decimal(1),
                unit_price=Decimal("100"),
                total_price=Decimal("100"),
                category_id=ilya.id,
            )
        ],
    )
    await db_session.commit()
    item_id = receipt.items[0].id

    await category_repo.delete_category(db_session, ilya.id)
    await db_session.commit()
    item = (
        await db_session.execute(select(ReceiptItem).where(ReceiptItem.id == item_id))
    ).scalar_one()
    assert item.category_id == deti.id  # re-pointed to parent
