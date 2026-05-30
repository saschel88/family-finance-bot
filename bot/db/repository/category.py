from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Category


async def list_categories(session: AsyncSession) -> list[Category]:
    result = await session.execute(select(Category).order_by(Category.id))
    return list(result.scalars().all())


async def get_category(session: AsyncSession, category_id: int) -> Category | None:
    result = await session.execute(select(Category).where(Category.id == category_id))
    return result.scalar_one_or_none()


async def get_by_name(session: AsyncSession, name: str) -> Category | None:
    """Case-insensitive lookup by category name."""
    result = await session.execute(
        select(Category).where(func.lower(Category.name) == name.lower())
    )
    return result.scalars().first()
