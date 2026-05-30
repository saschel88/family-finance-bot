from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Family


async def create_family(session: AsyncSession, name: str) -> Family:
    family = Family(name=name)
    session.add(family)
    await session.flush()
    return family


async def get_family(session: AsyncSession, family_id: int) -> Family | None:
    result = await session.execute(select(Family).where(Family.id == family_id))
    return result.scalar_one_or_none()
