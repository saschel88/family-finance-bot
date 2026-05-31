"""Reports v2 + receipt editing + manual entry (inline, button-driven).

Callback namespaces:
- ``rep:`` — report view navigation (period / mode / scope / page / custom)
- ``rcp:`` — receipt card and editing actions
- ``add:`` — manual purchase entry (category pick)

Free-text inputs (custom period, edited date/total/price, manual amount) are
captured by ``report_text_handler`` via a per-user pending marker in
``user_data`` and registered in its own handler group.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from decimal import Decimal, InvalidOperation

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.core.logging import get_logger
from bot.db.models import Category, FamilyMember, Receipt
from bot.db.repository import category as category_repo
from bot.db.repository import member as member_repo
from bot.db.repository import receipt as receipt_repo
from bot.handlers.keyboards import category_children_keyboard, category_tree_keyboard
from bot.services.money import format_money
from bot.services.reporter import (
    PERIOD_LABELS,
    Reporter,
    format_by_day,
    format_report,
    format_total,
    period_bounds,
)

logger = get_logger(__name__)

_PAGE_SIZE = 8
_PENDING = (
    "report_pending"  # user_data key: {"kind","id"} or {"kind":"custom"|"add",...}
)
_REP_STATE = "report_state"  # user_data key: last (period, scope, mode, page)

_PERIODS = ("today", "week", "month", "prev_month", "year")
_MODES = {"sum": "Итог", "day": "По дням", "cat": "По группам", "list": "Перечень"}


# --- helpers ----------------------------------------------------------------
async def _member(
    context: ContextTypes.DEFAULT_TYPE, chat_id: int
) -> FamilyMember | None:
    factory = context.bot_data["session_factory"]
    async with factory() as session:
        return await member_repo.get_member_by_chat_id(session, chat_id)


def _custom(context: ContextTypes.DEFAULT_TYPE) -> tuple[date, date] | None:
    data = context.user_data or {}
    raw = data.get("report_custom")
    if raw is None:
        return None
    return date.fromisoformat(raw[0]), date.fromisoformat(raw[1])


def _parse_amount(text: str) -> Decimal | None:
    cleaned = text.strip().replace(" ", "").replace(" ", "").replace(",", ".")
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        return None
    return value if value >= 0 else None


_DATE_FORMATS = ("%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d", "%d.%m.%y")


def _parse_date(text: str) -> date | None:
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _noon(d: date) -> datetime:
    return datetime.combine(d, time(12, 0), tzinfo=UTC)


# --- report view ------------------------------------------------------------
def _selector_rows(
    period: str, scope: str, mode: str
) -> list[list[InlineKeyboardButton]]:
    def mark(active: bool, label: str) -> str:
        return f"• {label}" if active else label

    periods = [
        InlineKeyboardButton(
            mark(period == p, PERIOD_LABELS[p]),
            callback_data=f"rep:v:{p}:{scope}:{mode}:0",
        )
        for p in _PERIODS
    ]
    modes = [
        InlineKeyboardButton(
            mark(mode == m, label), callback_data=f"rep:v:{period}:{scope}:{m}:0"
        )
        for m, label in _MODES.items()
    ]
    scopes = [
        InlineKeyboardButton(
            mark(scope == "own", "Я"), callback_data=f"rep:v:{period}:own:{mode}:0"
        ),
        InlineKeyboardButton(
            mark(scope == "family", "Семья"),
            callback_data=f"rep:v:{period}:family:{mode}:0",
        ),
        InlineKeyboardButton("Период…", callback_data=f"rep:custom:{scope}:{mode}"),
    ]
    return [periods, modes, scopes]


async def _render_view(
    context: ContextTypes.DEFAULT_TYPE,
    member: FamilyMember,
    period: str,
    scope: str,
    mode: str,
    page: int,
) -> tuple[str, InlineKeyboardMarkup]:
    if context.user_data is not None:
        context.user_data[_REP_STATE] = (period, scope, mode, page)
    reporter: Reporter = context.bot_data["reporter"]
    start, end = period_bounds(period, date.today(), _custom(context))
    title = f"Отчёт — {PERIOD_LABELS[period]}"
    rows = _selector_rows(period, scope, mode)

    if mode == "sum":
        total = await reporter.total(member, scope, start, end)
        text = format_total(title, scope, start, end, total)
    elif mode == "day":
        days = await reporter.by_day(member, scope, start, end)
        text = format_by_day(title, scope, start, end, days)
    elif mode == "cat":
        report = await reporter.by_category(member, scope, start, end, title)
        text = format_report(report)
    else:  # list
        text, list_rows = await _render_list(context, member, scope, start, end, page)
        rows = list_rows + rows
    return text, InlineKeyboardMarkup(rows)


async def _render_list(
    context: ContextTypes.DEFAULT_TYPE,
    member: FamilyMember,
    scope: str,
    start: date,
    end: date,
    page: int,
) -> tuple[str, list[list[InlineKeyboardButton]]]:
    reporter: Reporter = context.bot_data["reporter"]
    factory = context.bot_data["session_factory"]
    async with factory() as session:
        member_ids = await reporter._resolve_member_ids(session, member, scope)
        count = await receipt_repo.count_receipts(session, member_ids, start, end)
        receipts = await receipt_repo.list_receipts(
            session, member_ids, start, end, limit=_PAGE_SIZE, offset=page * _PAGE_SIZE
        )
    header = (
        f"🧾 Перечень покупок ({'семья' if scope == 'family' else 'вы'})\n"
        f"{start.isoformat()} — {(end).isoformat()}  ·  всего: {count}\n"
    )
    if not receipts:
        return header + "\nНет покупок за этот период.", []
    rows: list[list[InlineKeyboardButton]] = []
    for r in receipts:
        label = (
            f"{r.purchased_at.date().isoformat()} · "
            f"{(r.shop_name or 'Покупка')[:18]} · {format_money(r.total_amount)}"
        )
        rows.append([InlineKeyboardButton(label, callback_data=f"rcp:o:{r.id}")])
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(
            InlineKeyboardButton("◀", callback_data=f"rep:page:{scope}:{page - 1}")
        )
    if (page + 1) * _PAGE_SIZE < count:
        nav.append(
            InlineKeyboardButton("▶", callback_data=f"rep:page:{scope}:{page + 1}")
        )
    if nav:
        rows.append(nav)
    return header, rows


async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.effective_chat is not None and update.message is not None
    member = await _member(context, update.effective_chat.id)
    if member is None:
        await update.message.reply_text("Сначала зарегистрируйтесь через /start.")
        return
    text, keyboard = await _render_view(context, member, "month", "own", "cat", 0)
    await update.message.reply_text(text, reply_markup=keyboard)


async def rep_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    assert query is not None and query.data is not None and update.effective_chat
    await query.answer()
    member = await _member(context, update.effective_chat.id)
    if member is None:
        return
    parts = query.data.split(":")
    action = parts[1]

    if action == "custom":
        scope, mode = parts[2], parts[3]
        if context.user_data is not None:
            context.user_data[_PENDING] = {
                "kind": "custom",
                "scope": scope,
                "mode": mode,
            }
        await query.edit_message_text(
            "Пришлите период двумя датами: «ДД.ММ.ГГГГ ДД.ММ.ГГГГ»"
        )
        return

    if action == "page":
        scope, page = parts[2], int(parts[3])
        state = (context.user_data or {}).get(_REP_STATE, ("month", scope, "list", 0))
        period = state[0]
        text, keyboard = await _render_view(
            context, member, period, scope, "list", page
        )
        await query.edit_message_text(text, reply_markup=keyboard)
        return

    # action == "v": rep:v:<period>:<scope>:<mode>:<page>
    period, scope, mode, page = parts[2], parts[3], parts[4], int(parts[5])
    if period == "custom_keep":
        state = (context.user_data or {}).get(_REP_STATE, ("month", scope, mode, 0))
        period = state[0]
    text, keyboard = await _render_view(context, member, period, scope, mode, page)
    await query.edit_message_text(text, reply_markup=keyboard)


# --- receipt card + editing -------------------------------------------------
async def _render_card(
    context: ContextTypes.DEFAULT_TYPE, receipt_id: int
) -> tuple[str, InlineKeyboardMarkup] | None:
    factory = context.bot_data["session_factory"]
    async with factory() as session:
        receipt = await receipt_repo.get_receipt(session, receipt_id)
        if receipt is None:
            return None
        cats = {c.id: c for c in await category_repo.list_categories(session)}
        items = list(receipt.items)
    lines = [
        f"🧾 {receipt.shop_name or 'Покупка'}",
        f"📅 {receipt.purchased_at.date().isoformat()}  ·  итого: "
        f"{format_money(receipt.total_amount, receipt.currency)}",
        "",
    ]
    rows: list[list[InlineKeyboardButton]] = []
    for it in items:
        cat = cats.get(it.category_id) if it.category_id else None
        label = f"{cat.emoji} {cat.name}" if cat else "❓"
        lines.append(
            f"• {it.name} — {format_money(it.total_price, receipt.currency)} ({label})"
        )
        rows.append(
            [InlineKeyboardButton(f"✏ {it.name[:24]}", callback_data=f"rcp:i:{it.id}")]
        )
    rows.append(
        [
            InlineKeyboardButton("📅 Дата", callback_data=f"rcp:ed:{receipt.id}"),
            InlineKeyboardButton("💰 Итог", callback_data=f"rcp:et:{receipt.id}"),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton("🗑 Удалить чек", callback_data=f"rcp:dr:{receipt.id}"),
            InlineKeyboardButton("← К перечню", callback_data="rcp:back"),
        ]
    )
    return "\n".join(lines), InlineKeyboardMarkup(rows)


def _item_menu(item_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🏷 Категория", callback_data=f"rcp:ic:{item_id}")],
            [InlineKeyboardButton("💰 Сумма", callback_data=f"rcp:ip:{item_id}")],
            [
                InlineKeyboardButton(
                    "🗑 Удалить позицию", callback_data=f"rcp:idel:{item_id}"
                )
            ],
        ]
    )


async def rcp_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    assert query is not None and query.data is not None and update.effective_chat
    await query.answer()
    member = await _member(context, update.effective_chat.id)
    if member is None:
        return
    parts = query.data.split(":")
    action = parts[1]
    factory = context.bot_data["session_factory"]

    if action == "back":
        state = (context.user_data or {}).get(_REP_STATE, ("month", "own", "list", 0))
        period, scope, _, page = state
        text, keyboard = await _render_view(
            context, member, period, scope, "list", page
        )
        await query.edit_message_text(text, reply_markup=keyboard)
        return

    if action == "o":  # open card
        rendered = await _render_card(context, int(parts[2]))
        if rendered is None:
            await query.edit_message_text("Чек не найден.")
            return
        await query.edit_message_text(rendered[0], reply_markup=rendered[1])
        return

    if action == "i":  # item menu
        await query.edit_message_reply_markup(reply_markup=_item_menu(int(parts[2])))
        return

    if action == "ic":  # item category — top-level picker with drill-down
        item_id = int(parts[2])
        async with factory() as session:
            family_cats = await category_repo.list_for_family(session, member.family_id)
        await query.edit_message_reply_markup(
            reply_markup=category_tree_keyboard(
                item_id, family_cats, sel="rcp:sc", drill="rcp:scd"
            )
        )
        return

    if action == "scd":  # drill into a parent's subcategories
        item_id, parent_id = int(parts[2]), int(parts[3])
        async with factory() as session:
            parent = await category_repo.get_category(session, parent_id)
            children = await category_repo.list_children(session, parent_id)
        if parent is None:
            return
        await query.edit_message_reply_markup(
            reply_markup=category_children_keyboard(
                item_id, parent, children, sel="rcp:sc", back="rcp:ic"
            )
        )
        return

    if action == "sc":  # set category (leaf or "parent (общее)")
        item_id, cat_id = int(parts[2]), int(parts[3])
        async with factory() as session:
            async with session.begin():
                item = await receipt_repo.update_item_category(session, item_id, cat_id)
                receipt_id = item.receipt_id if item else None
        if receipt_id is not None:
            await _reopen_card(query, context, receipt_id)
        return

    if action in ("ed", "et", "ip"):  # ask for free-text input
        target_id = int(parts[2])
        kind = {"ed": "rdate", "et": "rtotal", "ip": "iprice"}[action]
        if context.user_data is not None:
            context.user_data[_PENDING] = {"kind": kind, "id": target_id}
        prompt = (
            "Пришлите дату покупки: ДД.ММ.ГГГГ"
            if kind == "rdate"
            else "Пришлите сумму (например 1500 или 1500,50)"
        )
        await query.edit_message_text(prompt)
        return

    if action == "dr":  # delete receipt — confirm
        await query.edit_message_reply_markup(
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "✅ Да, удалить", callback_data=f"rcp:drc:{parts[2]}"
                        ),
                        InlineKeyboardButton(
                            "Отмена", callback_data=f"rcp:o:{parts[2]}"
                        ),
                    ]
                ]
            )
        )
        return

    if action == "drc":  # delete receipt — confirmed
        async with factory() as session:
            async with session.begin():
                await receipt_repo.delete_receipt(session, int(parts[2]))
        await query.edit_message_text("🗑 Чек удалён.")
        return

    if action == "idel":  # delete item — confirm
        await query.edit_message_reply_markup(
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "✅ Да", callback_data=f"rcp:idc:{parts[2]}"
                        ),
                        InlineKeyboardButton(
                            "Отмена", callback_data=f"rcp:i:{parts[2]}"
                        ),
                    ]
                ]
            )
        )
        return

    if action == "idc":  # delete item — confirmed
        async with factory() as session:
            async with session.begin():
                receipt_id = await receipt_repo.delete_item(session, int(parts[2]))
        if receipt_id is not None:
            await _reopen_card(query, context, receipt_id)
        else:
            await query.edit_message_text("Позиция не найдена.")
        return


async def _reopen_card(
    query: object, context: ContextTypes.DEFAULT_TYPE, receipt_id: int
) -> None:
    rendered = await _render_card(context, receipt_id)
    if rendered is None:
        await query.edit_message_text("Чек не найден.")  # type: ignore[attr-defined]
        return
    await query.edit_message_text(rendered[0], reply_markup=rendered[1])  # type: ignore[attr-defined]


# --- manual add -------------------------------------------------------------
async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.effective_chat is not None and update.message is not None
    member = await _member(context, update.effective_chat.id)
    if member is None:
        await update.message.reply_text("Сначала зарегистрируйтесь через /start.")
        return
    factory = context.bot_data["session_factory"]
    async with factory() as session:
        cats = await category_repo.list_top_level(session, member.family_id)
    buttons = [
        InlineKeyboardButton(f"{c.emoji} {c.name}", callback_data=f"add:cat:{c.id}")
        for c in cats
    ]
    grid = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    await update.message.reply_text(
        "Выберите категорию покупки:", reply_markup=InlineKeyboardMarkup(grid)
    )


# --- category management ----------------------------------------------------
def _category_tree_text(cats: list[Category]) -> str:
    tops = [c for c in cats if c.parent_id is None]
    children: dict[int, list[Category]] = {}
    for c in cats:
        if c.parent_id is not None:
            children.setdefault(c.parent_id, []).append(c)
    lines = ["📂 Категории (своя — добавлена вами):"]
    for t in tops:
        tag = "" if t.family_id is None else " · своя"
        lines.append(f"{t.emoji} {t.name}{tag}")
        for ch in children.get(t.id, []):
            lines.append(f"   ↳ {ch.emoji} {ch.name}")
    return "\n".join(lines)


def _categories_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("➕ Категория", callback_data="cm:addtop")],
            [InlineKeyboardButton("➕ Подкатегория", callback_data="cm:addsubpick")],
            [InlineKeyboardButton("✏ / 🗑 Изменить свои", callback_data="cm:editlist")],
        ]
    )


async def categories_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.effective_chat is not None and update.message is not None
    member = await _member(context, update.effective_chat.id)
    if member is None:
        await update.message.reply_text("Сначала зарегистрируйтесь через /start.")
        return
    factory = context.bot_data["session_factory"]
    async with factory() as session:
        cats = await category_repo.list_for_family(session, member.family_id)
    await update.message.reply_text(
        _category_tree_text(cats), reply_markup=_categories_keyboard()
    )


async def cm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    assert query is not None and query.data is not None and update.effective_chat
    await query.answer()
    member = await _member(context, update.effective_chat.id)
    if member is None:
        return
    parts = query.data.split(":")
    action = parts[1]
    factory = context.bot_data["session_factory"]

    if action == "addtop":
        if context.user_data is not None:
            context.user_data[_PENDING] = {"kind": "cat_add", "parent_id": None}
        await query.edit_message_text("Введите название новой категории:")
        return

    if action == "addsubpick":
        async with factory() as session:
            tops = await category_repo.list_top_level(session, member.family_id)
        buttons = [
            InlineKeyboardButton(
                f"{c.emoji} {c.name}", callback_data=f"cm:addsub:{c.id}"
            )
            for c in tops
        ]
        rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
        await query.edit_message_text(
            "Выберите родительскую категорию:",
            reply_markup=InlineKeyboardMarkup(rows),
        )
        return

    if action == "addsub":
        if context.user_data is not None:
            context.user_data[_PENDING] = {
                "kind": "cat_add",
                "parent_id": int(parts[2]),
            }
        await query.edit_message_text("Введите название подкатегории:")
        return

    if action == "editlist":
        async with factory() as session:
            cats = await category_repo.list_for_family(session, member.family_id)
        custom = [c for c in cats if c.family_id is not None]
        if not custom:
            await query.edit_message_text(
                "У вас пока нет своих категорий. Добавьте через ➕."
            )
            return
        buttons = [
            InlineKeyboardButton(f"{c.emoji} {c.name}", callback_data=f"cm:edit:{c.id}")
            for c in custom
        ]
        rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
        await query.edit_message_text(
            "Ваши категории — выберите для изменения:",
            reply_markup=InlineKeyboardMarkup(rows),
        )
        return

    if action == "edit":
        cid = parts[2]
        await query.edit_message_reply_markup(
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "✏ Переименовать", callback_data=f"cm:ren:{cid}"
                        ),
                        InlineKeyboardButton(
                            "🗑 Удалить", callback_data=f"cm:del:{cid}"
                        ),
                    ],
                    [InlineKeyboardButton("‹ Назад", callback_data="cm:editlist")],
                ]
            )
        )
        return

    if action == "ren":
        if context.user_data is not None:
            context.user_data[_PENDING] = {"kind": "cat_rename", "id": int(parts[2])}
        await query.edit_message_text("Введите новое название:")
        return

    if action == "del":
        cid = parts[2]
        await query.edit_message_reply_markup(
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "✅ Удалить", callback_data=f"cm:delc:{cid}"
                        ),
                        InlineKeyboardButton("Отмена", callback_data=f"cm:edit:{cid}"),
                    ]
                ]
            )
        )
        return

    if action == "delc":
        async with factory() as session:
            async with session.begin():
                ok = await category_repo.delete_category(session, int(parts[2]))
        await query.edit_message_text(
            "🗑 Категория удалена." if ok else "Нельзя удалить системную категорию."
        )
        return


async def add_cat_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    assert query is not None and query.data is not None
    await query.answer()
    category_id = int(query.data.split(":")[2])
    if context.user_data is not None:
        context.user_data[_PENDING] = {"kind": "add", "id": category_id}
    await query.edit_message_text(
        "Введите сумму. Можно с названием: «Кофе 1500» — или просто «1500»."
    )


# --- shared text input (custom period / edits / manual amount) --------------
async def report_text_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if context.user_data is None:
        return
    pending = context.user_data.get(_PENDING)
    if pending is None or update.message is None or not update.message.text:
        return
    assert update.effective_chat is not None
    member = await _member(context, update.effective_chat.id)
    if member is None:
        return
    kind = pending["kind"]
    text = update.message.text
    factory = context.bot_data["session_factory"]

    if kind == "custom":
        parts = text.split()
        if len(parts) != 2 or not all(_parse_date(p) for p in parts):
            await update.message.reply_text("Формат: ДД.ММ.ГГГГ ДД.ММ.ГГГГ")
            return
        d1, d2 = _parse_date(parts[0]), _parse_date(parts[1])
        assert d1 and d2
        context.user_data["report_custom"] = (d1.isoformat(), d2.isoformat())
        context.user_data.pop(_PENDING, None)
        view = await _render_view(
            context, member, "custom", pending["scope"], pending["mode"], 0
        )
        await update.message.reply_text(view[0], reply_markup=view[1])
        return

    if kind == "cat_add":
        new_name = text.strip()
        if not new_name:
            await update.message.reply_text("Название не может быть пустым.")
            return
        async with factory() as session:
            async with session.begin():
                await category_repo.create_category(
                    session,
                    name=new_name,
                    family_id=member.family_id,
                    parent_id=pending.get("parent_id"),
                )
        context.user_data.pop(_PENDING, None)
        await update.message.reply_text(f"✅ Категория добавлена: {new_name}")
        return

    if kind == "cat_rename":
        new_name = text.strip()
        if not new_name:
            await update.message.reply_text("Название не может быть пустым.")
            return
        async with factory() as session:
            async with session.begin():
                renamed = await category_repo.rename_category(
                    session, pending["id"], new_name
                )
        context.user_data.pop(_PENDING, None)
        await update.message.reply_text(
            f"✏ Переименовано: {new_name}"
            if renamed is not None
            else "Системную категорию нельзя переименовать."
        )
        return

    if kind == "rdate":
        d = _parse_date(text)
        if d is None:
            await update.message.reply_text("Формат даты: ДД.ММ.ГГГГ")
            return
        async with factory() as session:
            async with session.begin():
                await receipt_repo.update_receipt_date(session, pending["id"], _noon(d))
        context.user_data.pop(_PENDING, None)
        await update.message.reply_text(f"📅 Дата покупки: {d.isoformat()}")
        return

    if kind in ("rtotal", "iprice"):
        amount = _parse_amount(text)
        if amount is None:
            await update.message.reply_text(
                "Нужна сумма числом, напр. 1500 или 1500,50"
            )
            return
        async with factory() as session:
            async with session.begin():
                if kind == "rtotal":
                    await receipt_repo.update_receipt_total(
                        session, pending["id"], amount
                    )
                else:
                    await receipt_repo.update_item_price(session, pending["id"], amount)
        context.user_data.pop(_PENDING, None)
        await update.message.reply_text(f"💰 Обновлено: {format_money(amount)}")
        return

    if kind == "add":
        name, amount = _split_name_amount(text)
        if amount is None:
            await update.message.reply_text(
                "Нужна сумма. Например «Кофе 1500» или «1500»."
            )
            return
        category_id = pending["id"]
        async with factory() as session:
            async with session.begin():
                cat = await category_repo.get_category(session, category_id)
                await receipt_repo.save_receipt_with_items(
                    session,
                    member_id=member.id,
                    shop_name=None,
                    purchased_at=_noon(date.today()),
                    total_amount=amount,
                    currency="KZT",
                    photo_file_id="manual",
                    raw_claude_json={"source": "manual"},
                    items=[
                        receipt_repo.ItemRow(
                            name=name or (cat.name if cat else "Покупка"),
                            quantity=Decimal(1),
                            unit_price=amount,
                            total_price=amount,
                            category_id=category_id,
                            confidence=1.0,
                            is_manual=True,
                        )
                    ],
                )
        context.user_data.pop(_PENDING, None)
        label = f"{cat.emoji} {cat.name}" if cat else "категория"
        title = name or (cat.name if cat else "покупка")
        await update.message.reply_text(
            f"✅ Добавлено: {title} — {format_money(amount)} ({label})"
        )
        return


def _split_name_amount(text: str) -> tuple[str | None, Decimal | None]:
    tokens = text.split()
    if not tokens:
        return None, None
    amount = _parse_amount(tokens[-1])
    if amount is None:
        return None, None
    name = " ".join(tokens[:-1]).strip() or None
    return name, amount
