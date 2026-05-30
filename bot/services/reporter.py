from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.db.models import FamilyMember
from bot.db.repository import category as category_repo
from bot.db.repository import member as member_repo
from bot.db.repository import receipt as receipt_repo


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

    async def _build(
        self,
        title: str,
        member: FamilyMember,
        scope: str,
        start: date,
        end: date,
    ) -> Report:
        async with self._session_factory() as session:
            if scope == "family":
                members = await member_repo.list_members(session, member.family_id)
                member_ids = [m.id for m in members]
            else:
                member_ids = [member.id]

            totals = await receipt_repo.sum_by_category(session, member_ids, start, end)
            categories = {c.id: c for c in await category_repo.list_categories(session)}

        lines: list[ReportLine] = []
        grand_total = Decimal(0)
        for ct in totals:
            grand_total += ct.total
            cat = categories.get(ct.category_id) if ct.category_id else None
            lines.append(
                ReportLine(
                    category_name=cat.name if cat else "Без категории",
                    emoji=cat.emoji if cat else "❓",
                    total=ct.total,
                )
            )
        lines.sort(key=lambda line: line.total, reverse=True)
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
        f"{line.emoji} {line.category_name}: {line.total:.2f}" for line in report.lines
    )
    return f"{header}\n{body}\n\nИтого: {report.total:.2f}"
