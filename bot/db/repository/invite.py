from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import FamilyInvite, FamilyMember


async def create_invite(
    session: AsyncSession,
    *,
    family_id: int,
    created_by: int,
    ttl_hours: int = 24,
    now: datetime | None = None,
) -> FamilyInvite:
    now = now or datetime.now(UTC)
    invite = FamilyInvite(
        family_id=family_id,
        token=uuid4().hex,
        created_by=created_by,
        expires_at=now + timedelta(hours=ttl_hours),
    )
    session.add(invite)
    await session.flush()
    return invite


async def get_valid_invite(
    session: AsyncSession, token: str, now: datetime | None = None
) -> FamilyInvite | None:
    """Return the invite only if it is unused and not expired."""
    now = now or datetime.now(UTC)
    result = await session.execute(
        select(FamilyInvite).where(FamilyInvite.token == token)
    )
    invite = result.scalar_one_or_none()
    if invite is None:
        return None
    if invite.used_at is not None:
        return None
    if invite.expires_at <= now:
        return None
    return invite


async def mark_used(
    session: AsyncSession,
    invite: FamilyInvite,
    member: FamilyMember,
    now: datetime | None = None,
) -> None:
    invite.used_by = member.id
    invite.used_at = now or datetime.now(UTC)
    await session.flush()
