from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.services.exchange import ExchangeService


def _service(
    session_factory: async_sessionmaker[AsyncSession],
) -> ExchangeService:
    return ExchangeService(session_factory, nbk_url="https://nbk.test")


async def test_kzt_passthrough_no_conversion(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = _service(session_factory)
    amount, rate = await service.convert(Decimal("100.00"), "KZT")
    assert amount == Decimal("100.00")
    assert rate is None


async def test_manual_rate_used_for_conversion(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = _service(session_factory)
    await service.set_manual_rate("USD", Decimal("470"), date(2026, 5, 1))
    amount, rate = await service.convert(Decimal("10"), "USD", on=date(2026, 5, 2))
    assert amount == Decimal("4700")
    assert rate is not None
    assert rate.source == "manual"


async def test_set_manual_rate_updates_existing(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = _service(session_factory)
    on = date(2026, 5, 1)
    await service.set_manual_rate("USD", Decimal("470"), on)
    updated = await service.set_manual_rate("USD", Decimal("480"), on)
    assert updated.rate == Decimal("480")


async def test_no_rate_falls_back_to_amount(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = _service(session_factory)
    amount, rate = await service.convert(Decimal("10"), "EUR")
    assert amount == Decimal("10")
    assert rate is None
