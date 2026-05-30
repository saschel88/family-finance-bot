from __future__ import annotations

from collections.abc import Callable
from unittest.mock import MagicMock

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from telegram.ext import ConversationHandler

from bot.db.models import Category, FamilyMember
from bot.db.repository import member as member_repo
from bot.db.repository import rule as rule_repo
from bot.handlers import commands
from bot.handlers.keyboards import CHOICE_CREATE
from bot.services.exchange import ExchangeService
from bot.services.reporter import Reporter
from tests.conftest import make_update


async def test_start_new_user_offers_choice(
    make_context: Callable[..., MagicMock],
) -> None:
    update = make_update(chat_id=7001)
    context = make_context()
    state = await commands.start(update, context)
    assert state == commands.OnboardingState.CHOOSING
    update.message.reply_text.assert_awaited()


async def test_start_existing_member_greets(
    make_context: Callable[..., MagicMock],
    test_owner_member: FamilyMember,
) -> None:
    update = make_update(chat_id=test_owner_member.chat_id)
    context = make_context()
    state = await commands.start(update, context)
    assert state == ConversationHandler.END


async def test_onboarding_choice_create(
    make_context: Callable[..., MagicMock],
) -> None:
    update = make_update(callback_data=CHOICE_CREATE)
    context = make_context()
    state = await commands.onboarding_choice(update, context)
    assert state == commands.OnboardingState.WAITING_NAME
    update.callback_query.answer.assert_awaited()


async def test_onboarding_create_persists_family_and_owner(
    make_context: Callable[..., MagicMock],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    update = make_update(chat_id=7002, text="Семья Тест")
    context = make_context()
    state = await commands.onboarding_create(update, context)
    assert state == ConversationHandler.END
    async with session_factory() as session:
        member = await member_repo.get_member_by_chat_id(session, 7002)
    assert member is not None
    assert member.role == "owner"


async def test_onboarding_create_empty_name_reprompts(
    make_context: Callable[..., MagicMock],
) -> None:
    update = make_update(chat_id=7003, text="   ")
    context = make_context()
    state = await commands.onboarding_create(update, context)
    assert state == commands.OnboardingState.WAITING_NAME


async def test_onboarding_join_invalid_token(
    make_context: Callable[..., MagicMock],
) -> None:
    update = make_update(chat_id=7004, text="badtoken")
    context = make_context()
    state = await commands.onboarding_join(update, context)
    assert state == commands.OnboardingState.WAITING_INVITE_TOKEN


async def test_invite_owner_only(
    make_context: Callable[..., MagicMock],
    test_member: FamilyMember,
) -> None:
    update = make_update(chat_id=test_member.chat_id)
    context = make_context()
    await commands.invite(update, context)
    # Non-owner gets a refusal, not a token.
    args = update.message.reply_text.await_args
    assert "владелец" in args.args[0].lower()


async def test_invite_owner_creates_token(
    make_context: Callable[..., MagicMock],
    test_owner_member: FamilyMember,
) -> None:
    update = make_update(chat_id=test_owner_member.chat_id)
    context = make_context()
    await commands.invite(update, context)
    args = update.message.reply_text.await_args
    assert "Токен" in args.args[0]


async def test_report_routing(
    make_context: Callable[..., MagicMock],
    session_factory: async_sessionmaker[AsyncSession],
    test_owner_member: FamilyMember,
) -> None:
    update = make_update(chat_id=test_owner_member.chat_id)
    context = make_context(reporter=Reporter(session_factory))
    await commands.report(update, context)
    update.message.reply_text.assert_awaited()


async def test_categories_lists_all(
    make_context: Callable[..., MagicMock],
    seed_categories: list[Category],
) -> None:
    update = make_update()
    context = make_context()
    await commands.categories(update, context)
    text = update.message.reply_text.await_args.args[0]
    assert seed_categories[0].name in text


async def test_learn_adds_rule(
    make_context: Callable[..., MagicMock],
    session_factory: async_sessionmaker[AsyncSession],
    seed_categories: list[Category],
) -> None:
    category = seed_categories[0]
    update = make_update()
    context = make_context(args=["молоко", category.name])
    await commands.learn(update, context)
    async with session_factory() as session:
        rules = await rule_repo.find_rules(session)
    assert any(r.pattern == "молоко" for r in rules)


async def test_learn_bad_args(
    make_context: Callable[..., MagicMock],
) -> None:
    update = make_update()
    context = make_context(args=["молоко"])
    await commands.learn(update, context)
    assert "Использование" in update.message.reply_text.await_args.args[0]


async def test_rate_sets_manual_rate(
    make_context: Callable[..., MagicMock],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    update = make_update()
    context = make_context(
        args=["USD", "470"],
        exchange=ExchangeService(session_factory, "https://nbk.test"),
    )
    await commands.rate(update, context)
    assert "USD" in update.message.reply_text.await_args.args[0]


async def test_rate_bad_number(
    make_context: Callable[..., MagicMock],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    update = make_update()
    context = make_context(
        args=["USD", "abc"],
        exchange=ExchangeService(session_factory, "https://nbk.test"),
    )
    await commands.rate(update, context)
    assert "числом" in update.message.reply_text.await_args.args[0]
