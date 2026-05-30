from __future__ import annotations

from datetime import date
from decimal import Decimal

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.core.logging import get_logger
from bot.db.models import ExchangeRate

logger = get_logger(__name__)

_HTTP_TIMEOUT = httpx.Timeout(10.0)


class ExchangeService:
    """Currency conversion to KZT.

    NBK fetching is a STUB (returns None) so conversion falls back to the most
    recent manually-set rate. The `/rate` command path (set_manual_rate) is
    fully functional.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        nbk_url: str,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._nbk_url = nbk_url
        self._http = http

    async def convert(
        self,
        amount: Decimal,
        from_currency: str,
        to_currency: str = "KZT",
        on: date | None = None,
    ) -> tuple[Decimal, ExchangeRate | None]:
        """Convert amount to KZT. Returns (converted_amount, rate_used)."""
        if from_currency.upper() == to_currency.upper():
            return amount, None
        rate = await self.get_rate(from_currency, on or date.today())
        if rate is None:
            logger.warning(
                "exchange no rate",
                from_currency=from_currency,
                to_currency=to_currency,
            )
            return amount, None
        return amount * rate.rate, rate

    async def get_rate(self, from_currency: str, on: date) -> ExchangeRate | None:
        """Return a rate, trying NBK (stub) then the latest manual rate."""
        nbk_rate = await self._fetch_nbk(from_currency, on)
        if nbk_rate is not None:
            return nbk_rate
        async with self._session_factory() as session:
            result = await session.execute(
                select(ExchangeRate)
                .where(ExchangeRate.from_currency == from_currency.upper())
                .order_by(ExchangeRate.rate_date.desc())
            )
            return result.scalars().first()

    async def set_manual_rate(
        self, from_currency: str, rate: Decimal, on: date | None = None
    ) -> ExchangeRate:
        """Insert or update a manual rate for the given currency/date."""
        on = on or date.today()
        currency = from_currency.upper()
        async with self._session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    select(ExchangeRate).where(
                        ExchangeRate.from_currency == currency,
                        ExchangeRate.rate_date == on,
                    )
                )
                existing = result.scalar_one_or_none()
                if existing is not None:
                    existing.rate = rate
                    existing.source = "manual"
                    await session.flush()
                    return existing
                row = ExchangeRate(
                    from_currency=currency,
                    to_currency="KZT",
                    rate=rate,
                    rate_date=on,
                    source="manual",
                )
                session.add(row)
                await session.flush()
                return row

    async def _fetch_nbk(self, from_currency: str, on: date) -> ExchangeRate | None:
        """STUB: real NBK RSS fetch lands here. Returns None for now."""
        logger.info("nbk stub", from_currency=from_currency, on=on.isoformat())
        return None
