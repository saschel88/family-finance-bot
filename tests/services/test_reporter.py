from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.db.models import Category, FamilyMember, Receipt, ReceiptItem
from bot.services.money import format_money
from bot.services.reporter import Reporter, format_by_day, format_total, period_bounds


async def _add_receipt(
    session: AsyncSession,
    *,
    member: FamilyMember,
    when: datetime,
    category_id: int,
    amount: Decimal,
) -> None:
    receipt = Receipt(
        family_member_id=member.id,
        shop_name="Shop",
        purchased_at=when,
        total_amount=amount,
        currency="KZT",
        photo_file_id="f",
        raw_claude_json={},
    )
    receipt.items = [
        ReceiptItem(
            name="item",
            quantity=Decimal(1),
            unit_price=amount,
            total_price=amount,
            category_id=category_id,
        )
    ]
    session.add(receipt)
    await session.commit()


async def test_monthly_own_scope(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    seed_categories: list[Category],
    test_owner_member: FamilyMember,
) -> None:
    cat = seed_categories[0]
    await _add_receipt(
        db_session,
        member=test_owner_member,
        when=datetime(2026, 5, 10, 12, tzinfo=UTC),
        category_id=cat.id,
        amount=Decimal("100.00"),
    )
    reporter = Reporter(session_factory)
    report = await reporter.monthly(
        test_owner_member, "own", datetime(2026, 5, 15).date()
    )
    assert report.total == Decimal("100.00")
    assert report.lines[0].category_name == cat.name


async def test_monthly_family_scope_aggregates_members(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    seed_categories: list[Category],
    test_owner_member: FamilyMember,
    test_member: FamilyMember,
) -> None:
    cat = seed_categories[0]
    when = datetime(2026, 5, 10, 12, tzinfo=UTC)
    await _add_receipt(
        db_session,
        member=test_owner_member,
        when=when,
        category_id=cat.id,
        amount=Decimal("100.00"),
    )
    await _add_receipt(
        db_session,
        member=test_member,
        when=when,
        category_id=cat.id,
        amount=Decimal("50.00"),
    )
    reporter = Reporter(session_factory)
    own = await reporter.monthly(test_owner_member, "own", datetime(2026, 5, 15).date())
    family = await reporter.monthly(
        test_owner_member, "family", datetime(2026, 5, 15).date()
    )
    assert own.total == Decimal("100.00")
    assert family.total == Decimal("150.00")


async def test_month_boundaries_half_open(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    seed_categories: list[Category],
    test_owner_member: FamilyMember,
) -> None:
    cat = seed_categories[0]
    # First day of month — included.
    await _add_receipt(
        db_session,
        member=test_owner_member,
        when=datetime(2026, 5, 1, 12, tzinfo=UTC),
        category_id=cat.id,
        amount=Decimal("10.00"),
    )
    # Previous month — excluded.
    await _add_receipt(
        db_session,
        member=test_owner_member,
        when=datetime(2026, 4, 25, 12, tzinfo=UTC),
        category_id=cat.id,
        amount=Decimal("999.00"),
    )
    # Next month — excluded.
    await _add_receipt(
        db_session,
        member=test_owner_member,
        when=datetime(2026, 6, 3, 12, tzinfo=UTC),
        category_id=cat.id,
        amount=Decimal("999.00"),
    )
    reporter = Reporter(session_factory)
    report = await reporter.monthly(
        test_owner_member, "own", datetime(2026, 5, 15).date()
    )
    assert report.total == Decimal("10.00")


async def test_weekly_scope(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    seed_categories: list[Category],
    test_owner_member: FamilyMember,
) -> None:
    cat = seed_categories[0]
    # 2026-05-13 is a Wednesday; week is Mon 2026-05-11 .. Mon 2026-05-18.
    await _add_receipt(
        db_session,
        member=test_owner_member,
        when=datetime(2026, 5, 13, 12, tzinfo=UTC),
        category_id=cat.id,
        amount=Decimal("30.00"),
    )
    await _add_receipt(
        db_session,
        member=test_owner_member,
        when=datetime(2026, 5, 5, 12, tzinfo=UTC),
        category_id=cat.id,
        amount=Decimal("999.00"),
    )
    reporter = Reporter(session_factory)
    report = await reporter.weekly(
        test_owner_member, "own", datetime(2026, 5, 13).date()
    )
    assert report.total == Decimal("30.00")


async def test_empty_report_has_no_lines(
    session_factory: async_sessionmaker[AsyncSession],
    test_owner_member: FamilyMember,
) -> None:
    reporter = Reporter(session_factory)
    report = await reporter.monthly(
        test_owner_member, "own", datetime(2026, 5, 15).date()
    )
    assert report.lines == []
    assert report.total == Decimal(0)


def test_period_bounds_kinds() -> None:
    today = date(2026, 5, 13)  # Wednesday
    assert period_bounds("today", today) == (date(2026, 5, 13), date(2026, 5, 14))
    assert period_bounds("week", today) == (date(2026, 5, 11), date(2026, 5, 18))
    assert period_bounds("month", today) == (date(2026, 5, 1), date(2026, 6, 1))
    assert period_bounds("prev_month", today) == (date(2026, 4, 1), date(2026, 5, 1))
    assert period_bounds("year", today) == (date(2026, 1, 1), date(2027, 1, 1))
    # custom end is made inclusive (+1 day)
    assert period_bounds("custom", today, (date(2026, 5, 1), date(2026, 5, 10))) == (
        date(2026, 5, 1),
        date(2026, 5, 11),
    )


def test_format_total_and_by_day() -> None:
    from bot.db.repository.receipt import DayTotal

    txt = format_total(
        "Отчёт", "own", date(2026, 5, 1), date(2026, 6, 1), Decimal("123.45")
    )
    assert format_money(Decimal("123.45")) in txt
    days = [
        DayTotal(day=date(2026, 5, 2), total=Decimal("10")),
        DayTotal(day=date(2026, 5, 3), total=Decimal("20")),
    ]
    out = format_by_day("Отчёт", "own", date(2026, 5, 1), date(2026, 6, 1), days)
    assert format_money(Decimal("10")) in out
    assert format_money(Decimal("30")) in out


async def test_total_and_by_day_modes(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    seed_categories: list[Category],
    test_owner_member: FamilyMember,
) -> None:
    cat = seed_categories[0]
    await _add_receipt(
        db_session,
        member=test_owner_member,
        when=datetime(2026, 5, 2, 12, tzinfo=UTC),
        category_id=cat.id,
        amount=Decimal("100.00"),
    )
    await _add_receipt(
        db_session,
        member=test_owner_member,
        when=datetime(2026, 5, 2, 18, tzinfo=UTC),
        category_id=cat.id,
        amount=Decimal("50.00"),
    )
    await _add_receipt(
        db_session,
        member=test_owner_member,
        when=datetime(2026, 5, 5, 12, tzinfo=UTC),
        category_id=cat.id,
        amount=Decimal("30.00"),
    )
    reporter = Reporter(session_factory)
    start, end = date(2026, 5, 1), date(2026, 6, 1)
    assert await reporter.total(test_owner_member, "own", start, end) == Decimal(
        "180.00"
    )
    days = await reporter.by_day(test_owner_member, "own", start, end)
    by = {d.day: d.total for d in days}
    assert by[date(2026, 5, 2)] == Decimal("150.00")
    assert by[date(2026, 5, 5)] == Decimal("30.00")
