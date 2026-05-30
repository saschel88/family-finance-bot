from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Product

# Provenance precedence — a higher-ranked source may overwrite a lower one.
_SOURCE_RANK = {"llm": 0, "nct": 1, "manual": 2}


async def get_by_gtin(session: AsyncSession, gtin: str) -> Product | None:
    result = await session.execute(select(Product).where(Product.gtin == gtin))
    return result.scalar_one_or_none()


async def get_by_ntin(session: AsyncSession, ntin: str) -> Product | None:
    result = await session.execute(select(Product).where(Product.ntin == ntin))
    return result.scalar_one_or_none()


async def upsert(
    session: AsyncSession,
    *,
    category_id: int,
    name: str,
    source: str,
    gtin: str | None = None,
    ntin: str | None = None,
) -> Product | None:
    """Insert or update a catalog entry keyed by GTIN (preferred) or NTIN.

    Returns None if neither identifier is supplied. On conflict, the category
    and name are overwritten only when the incoming source rank is >= the
    stored one (manual > nct > llm); usage_count is always bumped.
    """
    if not gtin and not ntin:
        return None

    existing: Product | None = None
    if gtin:
        existing = await get_by_gtin(session, gtin)
    if existing is None and ntin:
        existing = await get_by_ntin(session, ntin)

    new_rank = _SOURCE_RANK.get(source, 0)
    if existing is None:
        product = Product(
            gtin=gtin,
            ntin=ntin,
            name=name,
            category_id=category_id,
            source=source,
            usage_count=1,
        )
        session.add(product)
        await session.flush()
        return product

    existing.usage_count += 1
    # Backfill a missing identifier if we now know it.
    if gtin and not existing.gtin:
        existing.gtin = gtin
    if ntin and not existing.ntin:
        existing.ntin = ntin
    if new_rank >= _SOURCE_RANK.get(existing.source, 0):
        existing.category_id = category_id
        existing.name = name
        existing.source = source
    await session.flush()
    return existing
