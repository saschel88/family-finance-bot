from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from enum import IntEnum
from typing import Any

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from bot.core.logging import get_logger
from bot.db.repository import category as category_repo
from bot.db.repository import family as family_repo
from bot.db.repository import invite as invite_repo
from bot.db.repository import member as member_repo
from bot.db.repository import rule as rule_repo
from bot.handlers.keyboards import CHOICE_CREATE, CHOICE_JOIN, choice_keyboard
from bot.services.exchange import ExchangeService
from bot.services.reporter import Reporter, format_report

logger = get_logger(__name__)


class OnboardingState(IntEnum):
    CHOOSING = 0
    WAITING_NAME = 1
    WAITING_INVITE_TOKEN = 2


def _session_factory(context: ContextTypes.DEFAULT_TYPE):  # type: ignore[no-untyped-def]
    return context.bot_data["session_factory"]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point of onboarding. Greets known members, else offers a choice."""
    assert update.effective_chat is not None
    chat_id = update.effective_chat.id
    factory = _session_factory(context)
    async with factory() as session:
        member = await member_repo.get_member_by_chat_id(session, chat_id)
    if member is not None:
        await _reply(update, f"С возвращением, {member.name}! 👋")
        return ConversationHandler.END
    await _reply(
        update,
        "Привет! Я помогу вести учёт семейных расходов по чекам.\n"
        "Создайте семью или войдите по приглашению:",
        reply_markup=choice_keyboard(),
    )
    return OnboardingState.CHOOSING


async def onboarding_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    assert query is not None
    await query.answer()
    if query.data == CHOICE_CREATE:
        await query.edit_message_text("Введите название семьи:")
        return OnboardingState.WAITING_NAME
    if query.data == CHOICE_JOIN:
        await query.edit_message_text("Введите токен приглашения:")
        return OnboardingState.WAITING_INVITE_TOKEN
    return OnboardingState.CHOOSING


async def onboarding_create(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    assert update.effective_chat is not None and update.effective_user is not None
    assert update.message is not None
    family_name = (update.message.text or "").strip()
    if not family_name:
        await _reply(update, "Название не может быть пустым. Попробуйте ещё раз:")
        return OnboardingState.WAITING_NAME
    chat_id = update.effective_chat.id
    member_name = update.effective_user.first_name or "Участник"
    factory = _session_factory(context)
    async with factory() as session:
        async with session.begin():
            family = await family_repo.create_family(session, family_name)
            await member_repo.create_member(
                session,
                family_id=family.id,
                chat_id=chat_id,
                name=member_name,
                role="owner",
            )
    await _reply(
        update,
        f"Семья «{family_name}» создана! Вы — владелец.\n"
        "Отправьте фото чека, чтобы начать.",
    )
    return ConversationHandler.END


async def onboarding_join(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    assert update.effective_chat is not None and update.effective_user is not None
    assert update.message is not None
    token = (update.message.text or "").strip()
    chat_id = update.effective_chat.id
    member_name = update.effective_user.first_name or "Участник"
    factory = _session_factory(context)
    async with factory() as session:
        async with session.begin():
            invite = await invite_repo.get_valid_invite(session, token)
            if invite is None:
                await _reply(
                    update,
                    "Приглашение недействительно или истекло. "
                    "Запросите новое и попробуйте снова:",
                )
                return OnboardingState.WAITING_INVITE_TOKEN
            member = await member_repo.create_member(
                session,
                family_id=invite.family_id,
                chat_id=chat_id,
                name=member_name,
                role="member",
            )
            await invite_repo.mark_used(session, invite, member)
    await _reply(update, "Вы присоединились к семье! Отправьте фото чека.")
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await _reply(update, "Отменено.")
    return ConversationHandler.END


async def invite(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Create a one-time invite link (owner only)."""
    assert update.effective_chat is not None
    chat_id = update.effective_chat.id
    factory = _session_factory(context)
    async with factory() as session:
        async with session.begin():
            member = await member_repo.get_member_by_chat_id(session, chat_id)
            if member is None:
                await _reply(update, "Сначала зарегистрируйтесь через /start.")
                return
            if member.role != "owner":
                await _reply(update, "Только владелец может создавать приглашения.")
                return
            new_invite = await invite_repo.create_invite(
                session, family_id=member.family_id, created_by=member.id
            )
    await _reply(
        update,
        "Приглашение создано (действует 24 часа).\n"
        f"Токен: <code>{new_invite.token}</code>\n\n"
        "Новый участник: /start → «Войти по приглашению» → вставить токен.",
        parse_mode="HTML",
    )


async def report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.effective_chat is not None
    chat_id = update.effective_chat.id
    args = context.args or []
    factory = _session_factory(context)
    async with factory() as session:
        member = await member_repo.get_member_by_chat_id(session, chat_id)
    if member is None:
        await _reply(update, "Сначала зарегистрируйтесь через /start.")
        return
    reporter: Reporter = context.bot_data["reporter"]
    today = date.today()
    if "week" in args:
        result = await reporter.weekly(member, "own", today)
    elif "family" in args:
        result = await reporter.monthly(member, "family", today)
    else:
        result = await reporter.monthly(member, "own", today)
    await _reply(update, format_report(result))


async def categories(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    factory = _session_factory(context)
    async with factory() as session:
        cats = await category_repo.list_categories(session)
    lines = "\n".join(f"{c.emoji} {c.name}" for c in cats)
    await _reply(update, f"Категории:\n{lines}")


async def learn(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/learn <product> <category> — add an exact classification rule."""
    args = context.args or []
    if len(args) < 2:
        await _reply(update, "Использование: /learn <товар> <категория>")
        return
    factory = _session_factory(context)
    async with factory() as session:
        async with session.begin():
            cats = await category_repo.list_categories(session)
            cat_by_name = {c.name.lower(): c for c in cats}
            # Match the longest trailing suffix that is a known category.
            product: str | None = None
            category = None
            for i in range(1, len(args)):
                candidate = " ".join(args[i:]).lower()
                if candidate in cat_by_name:
                    category = cat_by_name[candidate]
                    product = " ".join(args[:i])
                    break
            if category is None or not product:
                await _reply(
                    update,
                    "Категория не найдена. Список — /categories",
                )
                return
            await rule_repo.upsert_exact(
                session, pattern=product, category_id=category.id
            )
    await _reply(update, f"Запомнил: «{product}» → {category.emoji} {category.name}")


async def rate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/rate <currency> <rate> — set a manual exchange rate to KZT."""
    args = context.args or []
    if len(args) < 2:
        await _reply(
            update, "Использование: /rate <валюта> <курс> (напр. /rate USD 470)"
        )
        return
    try:
        value = Decimal(args[1])
    except (InvalidOperation, ValueError):
        await _reply(update, "Курс должен быть числом, напр. /rate USD 470")
        return
    currency = args[0].upper()
    exchange: ExchangeService = context.bot_data["exchange"]
    await exchange.set_manual_rate(currency, value)
    await _reply(update, f"Курс {currency} → KZT установлен: {value}")


async def _reply(update: Update, text: str, **kwargs: Any) -> None:
    message = update.effective_message
    if message is not None:
        await message.reply_text(text, **kwargs)
