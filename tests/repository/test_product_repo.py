from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Category
from bot.db.repository import product as product_repo


async def test_insert_then_get_by_gtin(
    db_session: AsyncSession, seed_categories: list[Category]
) -> None:
    created = await product_repo.upsert(
        db_session,
        category_id=seed_categories[0].id,
        name="Молоко 1л",
        source="manual",
        gtin="4870001234567",
    )
    await db_session.commit()
    assert created is not None
    found = await product_repo.get_by_gtin(db_session, "4870001234567")
    assert found is not None
    assert found.category_id == seed_categories[0].id
    assert found.usage_count == 1


async def test_upsert_without_identifier_returns_none(
    db_session: AsyncSession, seed_categories: list[Category]
) -> None:
    result = await product_repo.upsert(
        db_session,
        category_id=seed_categories[0].id,
        name="X",
        source="manual",
    )
    assert result is None


async def test_manual_overwrites_llm(
    db_session: AsyncSession, seed_categories: list[Category]
) -> None:
    await product_repo.upsert(
        db_session,
        category_id=seed_categories[0].id,
        name="Товар",
        source="llm",
        gtin="111",
    )
    await db_session.commit()
    updated = await product_repo.upsert(
        db_session,
        category_id=seed_categories[2].id,
        name="Товар (исправлено)",
        source="manual",
        gtin="111",
    )
    await db_session.commit()
    assert updated is not None
    assert updated.category_id == seed_categories[2].id
    assert updated.source == "manual"
    assert updated.usage_count == 2


async def test_llm_does_not_overwrite_manual(
    db_session: AsyncSession, seed_categories: list[Category]
) -> None:
    await product_repo.upsert(
        db_session,
        category_id=seed_categories[2].id,
        name="Товар",
        source="manual",
        gtin="222",
    )
    await db_session.commit()
    result = await product_repo.upsert(
        db_session,
        category_id=seed_categories[0].id,
        name="Товар",
        source="llm",
        gtin="222",
    )
    await db_session.commit()
    assert result is not None
    # Category stays as the manual one; usage still bumped.
    assert result.category_id == seed_categories[2].id
    assert result.source == "manual"
    assert result.usage_count == 2


async def test_backfills_missing_ntin(
    db_session: AsyncSession, seed_categories: list[Category]
) -> None:
    await product_repo.upsert(
        db_session,
        category_id=seed_categories[0].id,
        name="Товар",
        source="manual",
        gtin="333",
    )
    await db_session.commit()
    updated = await product_repo.upsert(
        db_session,
        category_id=seed_categories[0].id,
        name="Товар",
        source="nct",
        gtin="333",
        ntin="KZ-999",
    )
    await db_session.commit()
    assert updated is not None
    assert updated.ntin == "KZ-999"
