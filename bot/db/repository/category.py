from __future__ import annotations

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Category, ReceiptItem


async def list_categories(session: AsyncSession) -> list[Category]:
    """All system categories (shared). Used for LLM/auto-classification base."""
    result = await session.execute(
        select(Category).where(Category.family_id.is_(None)).order_by(Category.id)
    )
    return list(result.scalars().all())


async def list_for_family(session: AsyncSession, family_id: int) -> list[Category]:
    """System categories + the family's own custom categories (for UI/reports)."""
    result = await session.execute(
        select(Category)
        .where(or_(Category.family_id.is_(None), Category.family_id == family_id))
        .order_by(Category.id)
    )
    return list(result.scalars().all())


async def list_top_level(session: AsyncSession, family_id: int) -> list[Category]:
    """Top-level categories (system + custom) — the auto-classification set.

    Subcategories (parent_id set) are excluded: they are assigned manually only.
    """
    result = await session.execute(
        select(Category)
        .where(
            Category.parent_id.is_(None),
            or_(Category.family_id.is_(None), Category.family_id == family_id),
        )
        .order_by(Category.id)
    )
    return list(result.scalars().all())


async def list_children(session: AsyncSession, parent_id: int) -> list[Category]:
    result = await session.execute(
        select(Category).where(Category.parent_id == parent_id).order_by(Category.id)
    )
    return list(result.scalars().all())


async def create_category(
    session: AsyncSession,
    *,
    name: str,
    family_id: int,
    parent_id: int | None = None,
    emoji: str = "🏷",
) -> Category:
    category = Category(
        name=name,
        emoji=emoji,
        parent_id=parent_id,
        family_id=family_id,
        is_system=False,
    )
    session.add(category)
    await session.flush()
    return category


async def rename_category(
    session: AsyncSession, category_id: int, name: str
) -> Category | None:
    category = await get_category(session, category_id)
    if category is None or category.family_id is None:
        return None  # system categories are not editable
    category.name = name
    await session.flush()
    return category


async def delete_category(session: AsyncSession, category_id: int) -> bool:
    """Delete a custom category. Its items/children are re-pointed to its parent
    (or NULL). System categories cannot be deleted."""
    category = await get_category(session, category_id)
    if category is None or category.family_id is None:
        return False
    parent_id = category.parent_id
    await session.execute(
        update(ReceiptItem)
        .where(ReceiptItem.category_id == category_id)
        .values(category_id=parent_id)
    )
    await session.execute(
        update(Category)
        .where(Category.parent_id == category_id)
        .values(parent_id=parent_id)
    )
    await session.delete(category)
    await session.flush()
    return True


async def get_category(session: AsyncSession, category_id: int) -> Category | None:
    result = await session.execute(select(Category).where(Category.id == category_id))
    return result.scalar_one_or_none()


async def top_level_ancestor(session: AsyncSession, category_id: int) -> int:
    """Walk up parent_id to the top-level ancestor id (for catalog learning)."""
    current = await get_category(session, category_id)
    seen: set[int] = set()
    while current is not None and current.parent_id is not None:
        if current.id in seen:
            break
        seen.add(current.id)
        current = await get_category(session, current.parent_id)
    return current.id if current is not None else category_id


async def get_by_name(session: AsyncSession, name: str) -> Category | None:
    """Case-insensitive lookup by category name."""
    result = await session.execute(
        select(Category).where(func.lower(Category.name) == name.lower())
    )
    return result.scalars().first()
