from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Category
from bot.db.repository import rule as rule_repo


async def test_create_and_find_rules(
    db_session: AsyncSession, seed_categories: list[Category]
) -> None:
    await rule_repo.create_rule(
        db_session, pattern="хлеб", category_id=seed_categories[0].id
    )
    await db_session.commit()
    rules = await rule_repo.find_rules(db_session)
    assert len(rules) == 1
    assert rules[0].pattern == "хлеб"


async def test_increment_usage(
    db_session: AsyncSession, seed_categories: list[Category]
) -> None:
    rule = await rule_repo.create_rule(
        db_session, pattern="кофе", category_id=seed_categories[0].id
    )
    await db_session.commit()
    await rule_repo.increment_usage(db_session, rule)
    await db_session.commit()
    assert rule.usage_count == 1


async def test_upsert_exact_inserts_then_updates(
    db_session: AsyncSession, seed_categories: list[Category]
) -> None:
    first = await rule_repo.upsert_exact(
        db_session, pattern="Молоко", category_id=seed_categories[0].id
    )
    await db_session.commit()
    assert first.pattern == "молоко"
    assert first.match_type == "exact"

    second = await rule_repo.upsert_exact(
        db_session, pattern="молоко", category_id=seed_categories[1].id
    )
    await db_session.commit()
    assert second.id == first.id
    assert second.category_id == seed_categories[1].id
    assert second.usage_count == 1

    rules = await rule_repo.find_rules(db_session)
    assert len(rules) == 1
