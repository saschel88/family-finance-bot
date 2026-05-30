from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Family, FamilyMember
from bot.db.repository import invite as invite_repo


async def test_create_invite_sets_expiry(
    db_session: AsyncSession,
    test_family: Family,
    test_owner_member: FamilyMember,
) -> None:
    now = datetime(2026, 5, 1, 12, tzinfo=UTC)
    invite = await invite_repo.create_invite(
        db_session,
        family_id=test_family.id,
        created_by=test_owner_member.id,
        now=now,
    )
    await db_session.commit()
    assert invite.token
    assert invite.expires_at == now + timedelta(hours=24)


async def test_valid_invite_returned(
    db_session: AsyncSession,
    test_family: Family,
    test_owner_member: FamilyMember,
) -> None:
    now = datetime(2026, 5, 1, 12, tzinfo=UTC)
    invite = await invite_repo.create_invite(
        db_session,
        family_id=test_family.id,
        created_by=test_owner_member.id,
        now=now,
    )
    await db_session.commit()
    found = await invite_repo.get_valid_invite(
        db_session, invite.token, now=now + timedelta(hours=1)
    )
    assert found is not None
    assert found.id == invite.id


async def test_expired_invite_rejected(
    db_session: AsyncSession,
    test_family: Family,
    test_owner_member: FamilyMember,
) -> None:
    now = datetime(2026, 5, 1, 12, tzinfo=UTC)
    invite = await invite_repo.create_invite(
        db_session,
        family_id=test_family.id,
        created_by=test_owner_member.id,
        now=now,
    )
    await db_session.commit()
    found = await invite_repo.get_valid_invite(
        db_session, invite.token, now=now + timedelta(hours=25)
    )
    assert found is None


async def test_used_invite_rejected(
    db_session: AsyncSession,
    test_family: Family,
    test_owner_member: FamilyMember,
    test_member: FamilyMember,
) -> None:
    now = datetime(2026, 5, 1, 12, tzinfo=UTC)
    invite = await invite_repo.create_invite(
        db_session,
        family_id=test_family.id,
        created_by=test_owner_member.id,
        now=now,
    )
    await db_session.commit()
    await invite_repo.mark_used(db_session, invite, test_member, now=now)
    await db_session.commit()
    found = await invite_repo.get_valid_invite(
        db_session, invite.token, now=now + timedelta(hours=1)
    )
    assert found is None


async def test_unknown_token_returns_none(db_session: AsyncSession) -> None:
    assert await invite_repo.get_valid_invite(db_session, "nope") is None
