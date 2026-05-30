from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.db.models import Category, FamilyMember, Receipt, ReceiptItem
from bot.services.reporter import Reporter


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
