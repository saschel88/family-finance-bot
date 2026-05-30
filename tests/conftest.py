from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from pytest_postgresql import factories
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from bot.db.models import Base, Category, Family, FamilyMember
from bot.db.repository import family as family_repo
from bot.db.repository import member as member_repo

# --- Test PostgreSQL connection (a running server, e.g. docker) -------------
TEST_PG_HOST = os.getenv("TEST_PG_HOST", "localhost")
TEST_PG_PORT = int(os.getenv("TEST_PG_PORT", "5433"))
TEST_PG_USER = os.getenv("TEST_PG_USER", "postgres")
TEST_PG_PASSWORD = os.getenv("TEST_PG_PASSWORD", "postgres")

postgresql_noproc = factories.postgresql_noproc(
    host=TEST_PG_HOST,
    port=TEST_PG_PORT,
    user=TEST_PG_USER,
    password=TEST_PG_PASSWORD,
)
postgresql = factories.postgresql("postgresql_noproc")


_CATEGORY_MAP = (
    Path(__file__).resolve().parents[1] / "bot" / "core" / "nct_category_map.json"
)


@pytest_asyncio.fixture
async def db_engine(postgresql: Any) -> AsyncIterator[AsyncEngine]:
    info = postgresql.info
    url = (
        f"postgresql+asyncpg://{info.user}:{TEST_PG_PASSWORD}"
        f"@{info.host}:{info.port}/{info.dbname}"
    )
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
def session_factory(
    db_engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(db_engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def db_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def seed_categories(db_session: AsyncSession) -> list[Category]:
    data = json.loads(_CATEGORY_MAP.read_text(encoding="utf-8"))
    cats = [
        Category(
            name=row["name"],
            emoji=row["emoji"],
            is_system=True,
            oktru_code=row["oktru_code"],
        )
        for row in data["categories"]
    ]
    db_session.add_all(cats)
    await db_session.commit()
    return cats


@pytest_asyncio.fixture
async def test_family(db_session: AsyncSession) -> Family:
    family = await family_repo.create_family(db_session, "Тестовая семья")
    await db_session.commit()
    return family


@pytest_asyncio.fixture
async def test_owner_member(
    db_session: AsyncSession, test_family: Family
) -> FamilyMember:
    member = await member_repo.create_member(
        db_session,
        family_id=test_family.id,
        chat_id=1001,
        name="Owner",
        role="owner",
    )
    await db_session.commit()
    return member


@pytest_asyncio.fixture
async def test_member(db_session: AsyncSession, test_family: Family) -> FamilyMember:
    member = await member_repo.create_member(
        db_session,
        family_id=test_family.id,
        chat_id=1002,
        name="Member",
        role="member",
    )
    await db_session.commit()
    return member


# --- Telegram / Anthropic mocks ---------------------------------------------
def make_update(
    *,
    chat_id: int = 1001,
    text: str | None = None,
    callback_data: str | None = None,
    photo: bool = False,
) -> MagicMock:
    update = MagicMock(name="Update")
    update.effective_chat = MagicMock()
    update.effective_chat.id = chat_id
    update.effective_user = MagicMock()
    update.effective_user.first_name = "Tester"

    if callback_data is not None:
        query = MagicMock(name="CallbackQuery")
        query.data = callback_data
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        query.message = MagicMock()
        query.message.reply_text = AsyncMock()
        update.callback_query = query
        update.message = None
        update.effective_message = query.message
    else:
        message = MagicMock(name="Message")
        message.text = text
        sent = MagicMock(name="SentMessage")
        sent.edit_text = AsyncMock()
        message.reply_text = AsyncMock(return_value=sent)
        if photo:
            size = MagicMock()
            size.file_id = "file123"
            message.photo = [size]
        update.message = message
        update.callback_query = None
        update.effective_message = message
    return update


@pytest.fixture
def make_context(
    session_factory: async_sessionmaker[AsyncSession],
) -> Callable[..., MagicMock]:
    def _make(args: list[str] | None = None, **bot_data: Any) -> MagicMock:
        context = MagicMock(name="Context")
        context.bot_data = {"session_factory": session_factory, **bot_data}
        context.user_data = {}
        context.args = args or []
        context.bot = AsyncMock()
        return context

    return _make


def make_anthropic(text: str) -> AsyncMock:
    """An AsyncAnthropic mock whose messages.create returns one text block."""
    client = AsyncMock()
    block = MagicMock()
    block.type = "text"
    block.text = text
    response = MagicMock()
    response.content = [block]
    client.messages.create = AsyncMock(return_value=response)
    return client


def make_gemini(text: str) -> MagicMock:
    """A genai.Client mock whose aio.models.generate_content returns .text."""
    client = MagicMock()
    response = MagicMock()
    response.text = text
    client.aio.models.generate_content = AsyncMock(return_value=response)
    return client
