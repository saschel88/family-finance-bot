from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import ProductRule


async def find_rules(session: AsyncSession) -> list[ProductRule]:
    """Load all rules; matching happens in the classifier (table is small)."""
    result = await session.execute(select(ProductRule))
    return list(result.scalars().all())


async def create_rule(
    session: AsyncSession,
    *,
    pattern: str,
    category_id: int,
    match_type: str = "exact",
    confidence: float = 1.0,
) -> ProductRule:
    rule = ProductRule(
        pattern=pattern,
        category_id=category_id,
        match_type=match_type,
        confidence=confidence,
    )
    session.add(rule)
    await session.flush()
    return rule


async def increment_usage(session: AsyncSession, rule: ProductRule) -> None:
    rule.usage_count += 1
    await session.flush()


async def upsert_exact(
    session: AsyncSession, *, pattern: str, category_id: int
) -> ProductRule:
    """Insert or update an exact-match rule for the given (lowercased) pattern."""
    normalized = pattern.strip().lower()
    result = await session.execute(
        select(ProductRule).where(
            func.lower(ProductRule.pattern) == normalized,
            ProductRule.match_type == "exact",
        )
    )
    rule = result.scalars().first()
    if rule is None:
        rule = ProductRule(
            pattern=normalized,
            category_id=category_id,
            match_type="exact",
            confidence=1.0,
        )
        session.add(rule)
    else:
        rule.category_id = category_id
        rule.usage_count += 1
    await session.flush()
    return rule
