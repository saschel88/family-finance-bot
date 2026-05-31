from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from telegram import Update
from telegram.ext import ContextTypes

from bot.core.logging import get_logger
from bot.db.models import Category
from bot.db.repository import category as category_repo
from bot.db.repository import member as member_repo
from bot.db.repository import product as product_repo
from bot.db.repository import receipt as receipt_repo
from bot.db.repository import rule as rule_repo
from bot.handlers.keyboards import (
    category_children_keyboard,
    category_tree_keyboard,
    date_keyboard,
)
from bot.services.classifier import Classifier, ClassifyFn
from bot.services.dedup import compute_dedup_key
from bot.services.exchange import ExchangeService
from bot.services.identifiers import normalize_gtin, normalize_ntin
from bot.services.money import format_money
from bot.services.ofd import OfdClient
from bot.services.qr import decode_qr, parse_ofd_url
from bot.services.receipt_text import ReceiptTextParser
from bot.services.schemas import ClassifiedItem, ReceiptVisionResponse, VisionError
from bot.services.vision_common import VisionEngine

_AWAITING_DATE = "awaiting_receipt_date"
_DUPLICATE = "Этот чек уже добавлен ранее — пропускаю, чтобы не задвоить."
_DATE_PROMPT = (
    "Дата в чеке не распознана — поставил сегодняшнюю. "
    "Выберите кнопкой или пришлите дату в формате ДД.ММ.ГГГГ:"
)

logger = get_logger(__name__)

_PROCESSING = "⏳ Обрабатываю чек..."
_VISION_FAILED = (
    "Не удалось распознать чек. Попробуйте сделать фото чётче и отправить снова."
)


async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.effective_chat is not None and update.message is not None
    chat_id = update.effective_chat.id
    factory = context.bot_data["session_factory"]

    async with factory() as session:
        member = await member_repo.get_member_by_chat_id(session, chat_id)
    if member is None:
        await update.message.reply_text("Сначала зарегистрируйтесь через /start.")
        return

    # A new receipt cancels any pending date prompt from a previous one.
    if context.user_data is not None:
        context.user_data.pop(_AWAITING_DATE, None)

    status_msg = await update.message.reply_text(_PROCESSING)

    photo = update.message.photo[-1]
    tg_file = await context.bot.get_file(photo.file_id)
    image_bytes = bytes(await tg_file.download_as_bytearray())

    # Prefer authoritative OFD data when the receipt carries a QR code.
    qr_ref = parse_ofd_url(decode_qr(image_bytes) or "")
    vision_data: ReceiptVisionResponse | None = None
    if qr_ref is not None:
        ofd_client: OfdClient = context.bot_data["ofd_client"]
        text = await ofd_client.fetch_ticket_text(qr_ref)
        if text:
            ofd_parser: ReceiptTextParser = context.bot_data["ofd_parser"]
            try:
                vision_data = await ofd_parser.parse(text)
                logger.info("receipt source", source="ofd", ofd=qr_ref.ofd)
            except VisionError:
                logger.warning("ofd parse failed", ofd=qr_ref.ofd)

    if vision_data is None:
        vision: VisionEngine = context.bot_data["vision"]
        try:
            vision_data = await vision.extract(image_bytes)
        except VisionError:
            logger.warning("vision failed", chat_id=chat_id)
            await status_msg.edit_text(_VISION_FAILED)
            return

    dedup_key = compute_dedup_key(member.family_id, vision_data, qr_ref)
    async with factory() as session:
        if await receipt_repo.get_by_dedup_key(session, dedup_key) is not None:
            await status_msg.edit_text(_DUPLICATE)
            return

    classifier: Classifier = context.bot_data["classifier"]
    exchange: ExchangeService = context.bot_data["exchange"]
    date_missing = vision_data.purchased_at is None
    purchased_at = vision_data.purchased_at or datetime.now(UTC)

    try:
        async with factory() as session:
            async with session.begin():
                # Auto-classification uses only top-level categories (system +
                # the family's own); subcategories are assigned manually.
                top_level = await category_repo.list_top_level(
                    session, member.family_id
                )
                family_cats = await category_repo.list_for_family(
                    session, member.family_id
                )
                classify_factory: Callable[[list[Category]], ClassifyFn] = (
                    context.bot_data["classify_factory"]
                )
                classified = await classifier.classify_items(
                    session, vision_data.items, classify_factory(top_level)
                )
                rows = await _build_rows(classified, vision_data, exchange)
                receipt = await receipt_repo.save_receipt_with_items(
                    session,
                    member_id=member.id,
                    shop_name=vision_data.shop_name,
                    purchased_at=purchased_at,
                    total_amount=vision_data.total_amount,
                    currency="KZT",
                    photo_file_id=photo.file_id,
                    raw_claude_json=vision_data.model_dump(mode="json"),
                    fiscal_id=vision_data.fiscal_id,
                    dedup_key=dedup_key,
                    items=rows,
                )
                saved_items = list(receipt.items)
                receipt_id = receipt.id
            cat_by_id = {c.id: c for c in family_cats}
    except IntegrityError:
        # Lost a race on the unique dedup_key — another upload won.
        await status_msg.edit_text(_DUPLICATE)
        return

    summary = _format_summary(vision_data, classified, cat_by_id)
    await status_msg.edit_text(summary)

    # Ask the user to confirm uncertain items via inline buttons.
    for item_model, classified_item in zip(saved_items, classified):
        if classified_item.category_id is None:
            await update.message.reply_text(
                f"Выберите категорию для: {item_model.name}",
                reply_markup=category_tree_keyboard(item_model.id, family_cats),
            )

    # If the receipt had no date, it was saved with "now"; let the user fix it.
    if date_missing:
        if context.user_data is not None:
            context.user_data[_AWAITING_DATE] = receipt_id
        await update.message.reply_text(
            _DATE_PROMPT, reply_markup=date_keyboard(receipt_id)
        )


async def category_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    assert query is not None and query.data is not None
    await query.answer()
    try:
        _, raw_item_id, raw_category_id = query.data.split(":")
        item_id = int(raw_item_id)
        category_id = int(raw_category_id)
    except ValueError:
        logger.warning("bad category callback", data=query.data)
        return

    factory = context.bot_data["session_factory"]
    async with factory() as session:
        async with session.begin():
            item = await receipt_repo.update_item_category(
                session, item_id, category_id, is_manual=True
            )
            if item is None:
                await query.edit_message_text("Позиция не найдена.")
                return
            # Learn at the TOP-LEVEL category (auto-classification never picks
            # subcategories); the item itself keeps the chosen (sub)category.
            learn_category_id = await category_repo.top_level_ancestor(
                session, category_id
            )
            if item.gtin or item.ntin:
                await product_repo.upsert(
                    session,
                    category_id=learn_category_id,
                    name=item.name,
                    source="manual",
                    gtin=item.gtin,
                    ntin=item.ntin,
                )
            else:
                await rule_repo.upsert_exact(
                    session, pattern=item.name, category_id=learn_category_id
                )
            category = await category_repo.get_category(session, category_id)
    label = f"{category.emoji} {category.name}" if category else "категория"
    await query.edit_message_text(f"✅ {item.name} → {label}")


async def category_drill_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Open subcategories of a tapped parent (photo-flow category buttons)."""
    query = update.callback_query
    assert query is not None and query.data is not None
    await query.answer()
    try:
        _, raw_item_id, raw_parent_id = query.data.split(":")
        item_id, parent_id = int(raw_item_id), int(raw_parent_id)
    except ValueError:
        return
    factory = context.bot_data["session_factory"]
    async with factory() as session:
        parent = await category_repo.get_category(session, parent_id)
        children = await category_repo.list_children(session, parent_id)
    if parent is None:
        return
    await query.edit_message_reply_markup(
        reply_markup=category_children_keyboard(item_id, parent, children)
    )


async def category_back_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Return to the top-level category list (photo-flow category buttons)."""
    query = update.callback_query
    assert query is not None and query.data is not None and update.effective_chat
    await query.answer()
    try:
        item_id = int(query.data.split(":")[1])
    except (ValueError, IndexError):
        return
    factory = context.bot_data["session_factory"]
    async with factory() as session:
        member = await member_repo.get_member_by_chat_id(
            session, update.effective_chat.id
        )
        if member is None:
            return
        family_cats = await category_repo.list_for_family(session, member.family_id)
    await query.edit_message_reply_markup(
        reply_markup=category_tree_keyboard(item_id, family_cats)
    )


_DATE_FORMATS = ("%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d", "%d.%m.%y")


def _parse_date(text: str) -> datetime | None:
    """Parse a user-typed date into a noon-UTC datetime, or None."""
    cleaned = text.strip()
    for fmt in _DATE_FORMATS:
        try:
            parsed = datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
        return parsed.replace(hour=12, tzinfo=UTC)
    return None


def _relative_date(choice: str) -> datetime | None:
    days = {"today": 0, "yesterday": 1, "dby": 2}.get(choice)
    if days is None:
        return None
    target = (datetime.now(UTC) - timedelta(days=days)).date()
    return datetime.combine(target, time(12, 0), tzinfo=UTC)


async def date_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    assert query is not None and query.data is not None
    await query.answer()
    try:
        _, raw_receipt_id, choice = query.data.split(":")
        receipt_id = int(raw_receipt_id)
    except ValueError:
        logger.warning("bad date callback", data=query.data)
        return

    if choice == "manual":
        if context.user_data is not None:
            context.user_data[_AWAITING_DATE] = receipt_id
        await query.edit_message_text("Пришлите дату покупки в формате ДД.ММ.ГГГГ:")
        return

    when = _relative_date(choice)
    if when is None:
        return
    factory = context.bot_data["session_factory"]
    async with factory() as session:
        async with session.begin():
            await receipt_repo.update_receipt_date(session, receipt_id, when)
    if context.user_data is not None:
        context.user_data.pop(_AWAITING_DATE, None)
    await query.edit_message_text(f"📅 Дата покупки: {when.date().isoformat()}")


async def date_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Capture a manually typed purchase date while one is awaited.

    Runs in its own handler group; silently no-ops unless a date is pending
    and the text parses as a date (so it never interferes with other text).
    """
    if context.user_data is None:
        return
    receipt_id = context.user_data.get(_AWAITING_DATE)
    if receipt_id is None or update.message is None or not update.message.text:
        return
    when = _parse_date(update.message.text)
    if when is None:
        return
    factory = context.bot_data["session_factory"]
    async with factory() as session:
        async with session.begin():
            await receipt_repo.update_receipt_date(session, receipt_id, when)
    context.user_data.pop(_AWAITING_DATE, None)
    await update.message.reply_text(f"📅 Дата покупки: {when.date().isoformat()}")


async def _build_rows(
    classified: list[ClassifiedItem],
    vision_data: ReceiptVisionResponse,
    exchange: ExchangeService,
) -> list[receipt_repo.ItemRow]:
    currency = vision_data.currency.upper()
    rows: list[receipt_repo.ItemRow] = []
    for c in classified:
        total_price = c.item.total_price
        unit_price = c.item.unit_price
        original_currency: str | None = None
        original_price: Decimal | None = None
        exchange_rate_id: int | None = None
        if currency != "KZT":
            converted_total, used_rate = await exchange.convert(total_price, currency)
            if used_rate is not None:
                original_currency = currency
                original_price = total_price
                exchange_rate_id = used_rate.id
                converted_unit, _ = await exchange.convert(unit_price, currency)
                total_price = converted_total
                unit_price = converted_unit
        rows.append(
            receipt_repo.ItemRow(
                # Prefer the catalog/NCT canonical name over noisy OCR.
                name=c.canonical_name or c.item.name,
                quantity=c.item.quantity,
                unit_price=unit_price,
                total_price=total_price,
                category_id=c.category_id,
                confidence=c.confidence,
                # GTIN from the printed barcode and NTIN from the source
                # (OFD) take priority; classifier/catalog ntin is the fallback.
                gtin=normalize_gtin(c.item.barcode),
                ntin=normalize_ntin(c.item.ntin) or c.ntin,
                original_currency=original_currency,
                original_price=original_price,
                exchange_rate_id=exchange_rate_id,
            )
        )
    return rows


def _format_summary(
    vision_data: ReceiptVisionResponse,
    classified: list[ClassifiedItem],
    cat_by_id: Mapping[int, Category],
) -> str:
    shop = vision_data.shop_name or "Магазин"
    currency = vision_data.currency
    header = f"🧾 {shop}\nИтого: {format_money(vision_data.total_amount, currency)}\n"
    lines = []
    for c in classified:
        cat = cat_by_id.get(c.category_id) if c.category_id is not None else None
        label = f"{cat.emoji} {cat.name}" if cat is not None else "❓ не определено"
        name = c.canonical_name or c.item.name
        lines.append(
            f"• {name} — {format_money(c.item.total_price, currency)} ({label})"
        )
    return header + "\n" + "\n".join(lines)
