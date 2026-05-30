from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import FamilyMember


async def create_member(
    session: AsyncSession,
    *,
    family_id: int,
    chat_id: int,
    name: str,
    role: str,
) -> FamilyMember:
    member = FamilyMember(family_id=family_id, chat_id=chat_id, name=name, role=role)
    session.add(member)
    await session.flush()
    return member


async def get_member_by_chat_id(
    session: AsyncSession, chat_id: int
) -> FamilyMember | None:
    result = await session.execute(
        select(FamilyMember).where(FamilyMember.chat_id == chat_id)
    )
    return result.scalar_one_or_none()


async def list_members(session: AsyncSession, family_id: int) -> list[FamilyMember]:
    result = await session.execute(
        select(FamilyMember).where(FamilyMember.family_id == family_id)
    )
    return list(result.scalars().all())
