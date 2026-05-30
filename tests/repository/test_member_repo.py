from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Family
from bot.db.repository import member as member_repo


async def test_create_and_get_by_chat_id(
    db_session: AsyncSession, test_family: Family
) -> None:
    created = await member_repo.create_member(
        db_session,
        family_id=test_family.id,
        chat_id=555,
        name="Alice",
        role="owner",
    )
    await db_session.commit()
    fetched = await member_repo.get_member_by_chat_id(db_session, 555)
    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.name == "Alice"


async def test_get_missing_returns_none(db_session: AsyncSession) -> None:
    assert await member_repo.get_member_by_chat_id(db_session, 999999) is None


async def test_list_members(db_session: AsyncSession, test_family: Family) -> None:
    await member_repo.create_member(
        db_session, family_id=test_family.id, chat_id=1, name="A", role="owner"
    )
    await member_repo.create_member(
        db_session, family_id=test_family.id, chat_id=2, name="B", role="member"
    )
    await db_session.commit()
    members = await member_repo.list_members(db_session, test_family.id)
    assert len(members) == 2


async def test_duplicate_chat_id_raises(
    db_session: AsyncSession, test_family: Family
) -> None:
    await member_repo.create_member(
        db_session, family_id=test_family.id, chat_id=42, name="A", role="owner"
    )
    await db_session.commit()
    with pytest.raises(IntegrityError):
        await member_repo.create_member(
            db_session,
            family_id=test_family.id,
            chat_id=42,
            name="B",
            role="member",
        )
