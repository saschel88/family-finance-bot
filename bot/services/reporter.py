from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.db.models import FamilyMember
from bot.db.repository import category as category_repo
from bot.db.repository import member as member_repo
from bot.db.repository import receipt as receipt_repo
from bot.services.money import format_money


@dataclass
class ReportLine:
    category_name: str
    emoji: str
    total: Decimal


@dataclass
class Report:
    title: str
    scope: str
    start: date
    end: date
    lines: list[ReportLine]
    total: Decimal


def _month_bounds(today: date) -> tuple[date, date]:
    start = today.replace(day=1)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


def _week_bounds(today: date) -> tuple[date, date]:
    start = today - timedelta(days=today.weekday())
    end = start + timedelta(days=7)
    return start, end


# Period kind -> human label (Russian).
PERIOD_LABELS = {
    "today": "Сегодня",
    "week": "Неделя",
    "month": "Месяц",
    "prev_month": "Прошлый месяц",
    "year": "Год",
    "custom": "Период",
}


def period_bounds(
    kind: str, today: date, custom: tuple[date, date] | None = None
) -> tuple[date, date]:
    """Half-open [start, end) bounds for a named period."""
    if kind == "today":
        return today, today + timedelta(days=1)
    if kind == "week":
        return _week_bounds(today)
    if kind == "month":
        return _month_bounds(today)
    if kind == "prev_month":
        first = today.replace(day=1)
        prev_end = first
        prev_start = (first - timedelta(days=1)).replace(day=1)
        return prev_start, prev_end
    if kind == "year":
        return date(today.year, 1, 1), date(today.year + 1, 1, 1)
    if kind == "custom" and custom is not None:
        start, end = custom
        return start, end + timedelta(days=1)  # make end inclusive
    raise ValueError(f"unknown period kind: {kind}")


class Reporter:
    """Aggregates spending by category over a period and scope."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def monthly(self, member: FamilyMember, scope: str, today: date) -> Report:
        start, end = _month_bounds(today)
        return await self._build("Расходы за месяц", member, scope, start, end)

    async def weekly(self, member: FamilyMember, scope: str, today: date) -> Report:
        start, end = _week_bounds(today)
        return await self._build("Расходы за неделю", member, scope, start, end)

    async def _resolve_member_ids(
        self, session: AsyncSession, member: FamilyMember, scope: str
    ) -> list[int]:
        if scope == "family":
            members = await member_repo.list_members(session, member.family_id)
            return [m.id for m in members]
        return [member.id]

    async def total(
        self, member: FamilyMember, scope: str, start: date, end: date
    ) -> Decimal:
        async with self._session_factory() as session:
            member_ids = await self._resolve_member_ids(session, member, scope)
            return await receipt_repo.sum_total(session, member_ids, start, end)

    async def by_day(
        self, member: FamilyMember, scope: str, start: date, end: date
    ) -> list[receipt_repo.DayTotal]:
        async with self._session_factory() as session:
            member_ids = await self._resolve_member_ids(session, member, scope)
            return await receipt_repo.sum_by_day(session, member_ids, start, end)

    async def by_category(
        self,
        member: FamilyMember,
        scope: str,
        start: date,
        end: date,
        title: str = "Расходы по категориям",
    ) -> Report:
        return await self._build(title, member, scope, start, end)

    async def _build(
        self,
        title: str,
        member: FamilyMember,
        scope: str,
        start: date,
        end: date,
    ) -> Report:
        async with self._session_factory() as session:
            member_ids = await self._resolve_member_ids(session, member, scope)
            totals = await receipt_repo.sum_by_category(session, member_ids, start, end)
            cats = await category_repo.list_for_family(session, member.family_id)
        by_id = {c.id: c for c in cats}

        def root_of(category_id: int) -> int:
            cat = by_id.get(category_id)
            seen: set[int] = set()
            while cat is not None and cat.parent_id is not None and cat.id not in seen:
                seen.add(cat.id)
                cat = by_id.get(cat.parent_id)
            return cat.id if cat is not None else category_id

        # Roll subcategory spending up into the top-level category.
        top_total: dict[int | None, Decimal] = {}
        sub_total: dict[tuple[int, int], Decimal] = {}
        for ct in totals:
            if ct.category_id is None:
                top_total[None] = top_total.get(None, Decimal(0)) + ct.total
                continue
            root_id = root_of(ct.category_id)
            top_total[root_id] = top_total.get(root_id, Decimal(0)) + ct.total
            if root_id != ct.category_id:  # spending on a subcategory
                sub_total[(root_id, ct.category_id)] = ct.total

        lines: list[ReportLine] = []
        grand_total = Decimal(0)
        ordered = sorted(top_total.items(), key=lambda kv: kv[1], reverse=True)
        for top_id, total in ordered:
            grand_total += total
            cat = by_id.get(top_id) if top_id is not None else None
            lines.append(
                ReportLine(
                    category_name=cat.name if cat else "Без категории",
                    emoji=cat.emoji if cat else "❓",
                    total=total,
                )
            )
            subs = [(cid, t) for (r, cid), t in sub_total.items() if r == top_id]
            for cid, t in sorted(subs, key=lambda kv: kv[1], reverse=True):
                sub = by_id.get(cid)
                lines.append(
                    ReportLine(
                        category_name=f"↳ {sub.name if sub else ''}",
                        emoji="",
                        total=t,
                    )
                )
        return Report(
            title=title,
            scope=scope,
            start=start,
            end=end,
            lines=lines,
            total=grand_total,
        )


def format_report(report: Report) -> str:
    """Render a report as a Russian Telegram message (pure, no Telegram dep)."""
    scope_label = "семья" if report.scope == "family" else "вы"
    header = (
        f"📊 {report.title} ({scope_label})\n"
        f"{report.start.isoformat()} — {report.end.isoformat()}\n"
    )
    if not report.lines:
        return header + "\nНет расходов за этот период."
    body = "\n".join(
        f"{line.emoji} {line.category_name}: {format_money(line.total)}"
        for line in report.lines
    )
    return f"{header}\n{body}\n\nИтого: {format_money(report.total)}"


def _scope_label(scope: str) -> str:
    return "семья" if scope == "family" else "вы"


def _period_header(title: str, scope: str, start: date, end: date) -> str:
    last = end - timedelta(days=1)
    return (
        f"📊 {title} ({_scope_label(scope)})\n"
        f"{start.isoformat()} — {last.isoformat()}\n"
    )


def format_total(title: str, scope: str, start: date, end: date, total: Decimal) -> str:
    return _period_header(title, scope, start, end) + f"\nИтого: {format_money(total)}"


def format_by_day(
    title: str,
    scope: str,
    start: date,
    end: date,
    days: list[receipt_repo.DayTotal],
) -> str:
    header = _period_header(title, scope, start, end)
    if not days:
        return header + "\nНет расходов за этот период."
    body = "\n".join(f"{d.day.isoformat()}: {format_money(d.total)}" for d in days)
    grand = sum((d.total for d in days), Decimal(0))
    return f"{header}\n{body}\n\nИтого: {format_money(grand)}"
