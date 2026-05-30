from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Category
from bot.db.repository import product as product_repo
from bot.db.repository import rule as rule_repo
from bot.services.classifier import Classifier
from bot.services.nct import NctClient
from bot.services.schemas import NctProduct, ReceiptItemData


def _nct() -> NctClient:
    return NctClient(base_url="https://nct.test")


def _item(name: str, barcode: str | None = None) -> ReceiptItemData:
    return ReceiptItemData(
        name=name,
        quantity=1,  # type: ignore[arg-type]
        unit_price=100,  # type: ignore[arg-type]
        total_price=100,  # type: ignore[arg-type]
        barcode=barcode,
    )


async def test_gtin_hit_assigns_category(
    db_session: AsyncSession, seed_categories: list[Category]
) -> None:
    nct = _nct()
    nct.lookup_by_gtin = AsyncMock(  # type: ignore[method-assign]
        return_value=NctProduct(gtin="123", name="X", nct_category="dairy")
    )
    nct.map_nct_category_to_local = MagicMock(  # type: ignore[method-assign]
        return_value=seed_categories[0].id
    )
    classifier = Classifier(nct)
    [result] = await classifier.classify_items(
        db_session, [_item("Молоко", barcode="123")], claude=None
    )
    assert result.source == "nct_gtin"
    assert result.category_id == seed_categories[0].id
    assert result.confidence == 1.0


async def test_name_hit_assigns_category(
    db_session: AsyncSession, seed_categories: list[Category]
) -> None:
    nct = _nct()
    nct.search_by_name = AsyncMock(  # type: ignore[method-assign]
        return_value=[NctProduct(gtin="9", name="X", nct_category="dairy")]
    )
    nct.map_nct_category_to_local = MagicMock(  # type: ignore[method-assign]
        return_value=seed_categories[0].id
    )
    classifier = Classifier(nct)
    [result] = await classifier.classify_items(db_session, [_item("Сыр")], claude=None)
    assert result.source == "nct_name"
    assert result.category_id == seed_categories[0].id


async def test_rule_exact_match(
    db_session: AsyncSession, seed_categories: list[Category]
) -> None:
    await rule_repo.create_rule(
        db_session,
        pattern="молоко",
        category_id=seed_categories[0].id,
        match_type="exact",
    )
    await db_session.commit()
    classifier = Classifier(_nct())
    [result] = await classifier.classify_items(
        db_session, [_item("Молоко")], claude=None
    )
    assert result.source == "rule_exact"
    assert result.category_id == seed_categories[0].id


async def test_rule_contains_match(
    db_session: AsyncSession, seed_categories: list[Category]
) -> None:
    await rule_repo.create_rule(
        db_session,
        pattern="кола",
        category_id=seed_categories[0].id,
        match_type="contains",
    )
    await db_session.commit()
    classifier = Classifier(_nct())
    [result] = await classifier.classify_items(
        db_session, [_item("Кока-кола 1л")], claude=None
    )
    assert result.source == "rule_contains"


async def test_rule_regex_match(
    db_session: AsyncSession, seed_categories: list[Category]
) -> None:
    await rule_repo.create_rule(
        db_session,
        pattern=r"^хлеб.*",
        category_id=seed_categories[0].id,
        match_type="regex",
    )
    await db_session.commit()
    classifier = Classifier(_nct())
    [result] = await classifier.classify_items(
        db_session, [_item("Хлеб бородинский")], claude=None
    )
    assert result.source == "rule_regex"


async def test_claude_fallback_used(
    db_session: AsyncSession, seed_categories: list[Category]
) -> None:
    async def claude(item: ReceiptItemData) -> tuple[int | None, float]:
        return seed_categories[1].id, 0.8

    classifier = Classifier(_nct())
    [result] = await classifier.classify_items(
        db_session, [_item("Нечто странное")], claude=claude
    )
    assert result.source == "claude"
    assert result.category_id == seed_categories[1].id


async def test_low_confidence_returns_uncertain(
    db_session: AsyncSession, seed_categories: list[Category]
) -> None:
    async def claude(item: ReceiptItemData) -> tuple[int | None, float]:
        return seed_categories[1].id, 0.5

    classifier = Classifier(_nct())
    [result] = await classifier.classify_items(
        db_session, [_item("Нечто странное")], claude=claude
    )
    assert result.category_id is None
    assert result.source == "unknown"


async def test_all_miss_no_claude_returns_uncertain(
    db_session: AsyncSession, seed_categories: list[Category]
) -> None:
    classifier = Classifier(_nct())
    [result] = await classifier.classify_items(
        db_session, [_item("Неизвестный товар")], claude=None
    )
    assert result.category_id is None
    assert result.source == "unknown"


async def test_local_catalog_gtin_hit_first(
    db_session: AsyncSession, seed_categories: list[Category]
) -> None:
    await product_repo.upsert(
        db_session,
        category_id=seed_categories[0].id,
        name="Молоко (каталог)",
        source="manual",
        gtin="999000111",
    )
    await db_session.commit()
    classifier = Classifier(_nct())
    [result] = await classifier.classify_items(
        db_session, [_item("кривое имя", barcode="999000111")], claude=None
    )
    assert result.source == "catalog_gtin"
    assert result.category_id == seed_categories[0].id
    assert result.canonical_name == "Молоко (каталог)"


async def test_confident_llm_with_gtin_is_cached(
    db_session: AsyncSession, seed_categories: list[Category]
) -> None:
    async def claude(item: ReceiptItemData) -> tuple[int | None, float]:
        return seed_categories[1].id, 0.95

    classifier = Classifier(_nct())
    [result] = await classifier.classify_items(
        db_session, [_item("Загадка", barcode="555000222")], claude=claude
    )
    assert result.source == "claude"
    cached = await product_repo.get_by_gtin(db_session, "555000222")
    assert cached is not None
    assert cached.category_id == seed_categories[1].id
    assert cached.source == "llm"


async def test_nct_gtin_hit_is_cached(
    db_session: AsyncSession, seed_categories: list[Category]
) -> None:
    nct = _nct()
    nct.lookup_by_gtin = AsyncMock(  # type: ignore[method-assign]
        return_value=NctProduct(
            gtin="777", ntin="KZ-777", name="Хлеб (НК)", nct_category="bakery"
        )
    )
    nct.map_nct_category_to_local = MagicMock(  # type: ignore[method-assign]
        return_value=seed_categories[0].id
    )
    classifier = Classifier(nct)
    [result] = await classifier.classify_items(
        db_session, [_item("хлеб", barcode="777")], claude=None
    )
    assert result.source == "nct_gtin"
    assert result.ntin == "KZ-777"
    cached = await product_repo.get_by_gtin(db_session, "777")
    assert cached is not None
    assert cached.source == "nct"
    assert cached.ntin == "KZ-777"
