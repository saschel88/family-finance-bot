from __future__ import annotations

from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.db.models import Category, FamilyMember, ProductRule, Receipt, ReceiptItem
from bot.db.repository import product as product_repo
from bot.db.repository import receipt as receipt_repo
from bot.handlers import receipt
from bot.services.classifier import Classifier
from bot.services.claude_classify import ClaudeClassifier
from bot.services.exchange import ExchangeService
from bot.services.nct import NctClient
from bot.services.schemas import ReceiptItemData, ReceiptVisionResponse
from bot.services.vision import VisionService
from tests.conftest import make_anthropic, make_update

_RECEIPT_JSON = """
{
  "shop_name": "Магнум",
  "purchased_at": "2026-05-01T12:00:00",
  "currency": "KZT",
  "total_amount": 250.00,
  "items": [
    {"name": "Хлеб", "quantity": 1, "unit_price": 250.00,
     "total_price": 250.00, "barcode": "4870001234567"}
  ]
}
"""


def _photo_context(
    make_context: Callable[..., MagicMock],
    session_factory: async_sessionmaker[AsyncSession],
    *,
    vision_json: str,
    classify_json: str,
) -> MagicMock:
    classify_client = make_anthropic(classify_json)
    context = make_context(
        vision=VisionService(make_anthropic(vision_json), "claude-test"),
        classifier=Classifier(NctClient(base_url="https://nct.test")),
        exchange=ExchangeService(session_factory, "https://nbk.test"),
        classify_factory=lambda cats: ClaudeClassifier(
            classify_client, "claude-test", cats
        ),
    )
    tg_file = AsyncMock()
    tg_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"img"))
    context.bot.get_file = AsyncMock(return_value=tg_file)
    return context


async def test_photo_happy_path_saves_receipt(
    make_context: Callable[..., MagicMock],
    session_factory: async_sessionmaker[AsyncSession],
    seed_categories: list[Category],
    test_owner_member: FamilyMember,
) -> None:
    classify_json = (
        f'[{{"index": 0, "category_id": {seed_categories[0].id},'
        ' "confidence": 0.95}]'
    )
    context = _photo_context(
        make_context,
        session_factory,
        vision_json=_RECEIPT_JSON,
        classify_json=classify_json,
    )
    update = make_update(chat_id=test_owner_member.chat_id, photo=True)

    await receipt.photo_handler(update, context)

    status = update.message.reply_text.return_value
    status.edit_text.assert_awaited()
    async with session_factory() as session:
        rows = (await session.execute(select(ReceiptItem))).scalars().all()
    assert len(rows) == 1
    assert rows[0].category_id == seed_categories[0].id
    # GTIN from the receipt barcode must be persisted (legal requirement).
    assert rows[0].gtin == "4870001234567"


async def test_photo_vision_failure_no_save(
    make_context: Callable[..., MagicMock],
    session_factory: async_sessionmaker[AsyncSession],
    seed_categories: list[Category],
    test_owner_member: FamilyMember,
) -> None:
    context = _photo_context(
        make_context,
        session_factory,
        vision_json="not json",
        classify_json="[]",
    )
    update = make_update(chat_id=test_owner_member.chat_id, photo=True)

    await receipt.photo_handler(update, context)

    status = update.message.reply_text.return_value
    assert "Не удалось" in status.edit_text.await_args.args[0]
    async with session_factory() as session:
        rows = (await session.execute(select(ReceiptItem))).scalars().all()
    assert rows == []


async def test_photo_unregistered_user(
    make_context: Callable[..., MagicMock],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    context = _photo_context(
        make_context,
        session_factory,
        vision_json=_RECEIPT_JSON,
        classify_json="[]",
    )
    update = make_update(chat_id=99999, photo=True)
    await receipt.photo_handler(update, context)
    update.message.reply_text.assert_awaited()
    assert "/start" in update.message.reply_text.await_args.args[0]


async def test_category_callback_updates_item_and_learns_rule(
    make_context: Callable[..., MagicMock],
    session_factory: async_sessionmaker[AsyncSession],
    seed_categories: list[Category],
    db_session: AsyncSession,
    test_owner_member: FamilyMember,
) -> None:
    from datetime import UTC, datetime
    from decimal import Decimal

    saved = await receipt_repo.save_receipt_with_items(
        db_session,
        member_id=test_owner_member.id,
        shop_name="Shop",
        purchased_at=datetime(2026, 5, 1, tzinfo=UTC),
        total_amount=Decimal("100"),
        currency="KZT",
        photo_file_id="f",
        raw_claude_json={},
        items=[
            receipt_repo.ItemRow(
                name="Загадка",
                quantity=Decimal(1),
                unit_price=Decimal("100"),
                total_price=Decimal("100"),
            )
        ],
    )
    await db_session.commit()
    item_id = saved.items[0].id
    category_id = seed_categories[2].id

    context = make_context()
    update = make_update(callback_data=f"cat:{item_id}:{category_id}")
    await receipt.category_callback(update, context)

    update.callback_query.answer.assert_awaited()
    async with session_factory() as session:
        item = (
            await session.execute(select(ReceiptItem).where(ReceiptItem.id == item_id))
        ).scalar_one()
        assert item.category_id == category_id
        assert item.is_manual is True
        rules = (await session.execute(select(ProductRule))).scalars().all()
    assert any(r.pattern == "загадка" for r in rules)


async def test_category_callback_with_gtin_learns_product(
    make_context: Callable[..., MagicMock],
    session_factory: async_sessionmaker[AsyncSession],
    seed_categories: list[Category],
    db_session: AsyncSession,
    test_owner_member: FamilyMember,
) -> None:
    from datetime import UTC, datetime
    from decimal import Decimal

    saved = await receipt_repo.save_receipt_with_items(
        db_session,
        member_id=test_owner_member.id,
        shop_name="Shop",
        purchased_at=datetime(2026, 5, 1, tzinfo=UTC),
        total_amount=Decimal("100"),
        currency="KZT",
        photo_file_id="f",
        raw_claude_json={},
        items=[
            receipt_repo.ItemRow(
                name="кривой OCR",
                quantity=Decimal(1),
                unit_price=Decimal("100"),
                total_price=Decimal("100"),
                gtin="4870009998887",
            )
        ],
    )
    await db_session.commit()
    item_id = saved.items[0].id
    category_id = seed_categories[1].id

    context = make_context()
    update = make_update(callback_data=f"cat:{item_id}:{category_id}")
    await receipt.category_callback(update, context)

    async with session_factory() as session:
        product = await product_repo.get_by_gtin(session, "4870009998887")
        rules = (await session.execute(select(ProductRule))).scalars().all()
    assert product is not None
    assert product.category_id == category_id
    assert product.source == "manual"
    # No name-based rule when an identifier is present.
    assert rules == []


async def test_category_callback_bad_data(
    make_context: Callable[..., MagicMock],
) -> None:
    context = make_context()
    update = make_update(callback_data="cat:notanint")
    await receipt.category_callback(update, context)
    update.callback_query.answer.assert_awaited()


def _fixed_classify(category_id: int) -> Callable[..., object]:
    async def _fn(
        items: list[ReceiptItemData],
    ) -> list[tuple[int | None, float]]:
        return [(category_id, 0.9) for _ in items]

    return _fn


async def test_ofd_source_used_when_qr_present(
    mocker: object,
    make_context: Callable[..., MagicMock],
    session_factory: async_sessionmaker[AsyncSession],
    seed_categories: list[Category],
    test_owner_member: FamilyMember,
) -> None:
    from datetime import UTC, datetime
    from decimal import Decimal

    mocker.patch(  # type: ignore[attr-defined]
        "bot.handlers.receipt.decode_qr",
        return_value=(
            "https://consumer.wofd.kz/?i=841061549277&f=010102737143"
            "&s=26965.00&t=20260501T185332"
        ),
    )

    vision_data = ReceiptVisionResponse(
        shop_name="ТОО КАРИ КЗ",
        purchased_at=datetime(2026, 5, 1, 18, 53, 32, tzinfo=UTC),
        total_amount=Decimal("26965.00"),
        fiscal_id="841061549277",
        items=[
            ReceiptItemData(
                name="Бэтэнке",
                quantity=Decimal(1),
                unit_price=Decimal("12243.00"),
                total_price=Decimal("12243.00"),
                barcode="04630529181414",
                ntin="0200141815130",
            )
        ],
    )

    class _FakeOfdClient:
        async def fetch_ticket_text(self, ref: object) -> str:
            return "exact ofd text"

    class _FakeParser:
        async def parse(self, text: str) -> ReceiptVisionResponse:
            return vision_data

    vision_mock = AsyncMock()
    vision_mock.extract = AsyncMock(side_effect=AssertionError("vision called"))

    context = make_context(
        vision=vision_mock,
        ofd_client=_FakeOfdClient(),
        ofd_parser=_FakeParser(),
        classifier=Classifier(NctClient(base_url="https://nct.test")),
        exchange=ExchangeService(session_factory, "https://nbk.test"),
        classify_factory=lambda cats: _fixed_classify(seed_categories[0].id),
    )
    tg_file = AsyncMock()
    tg_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"img"))
    context.bot.get_file = AsyncMock(return_value=tg_file)

    update = make_update(chat_id=test_owner_member.chat_id, photo=True)
    await receipt.photo_handler(update, context)

    vision_mock.extract.assert_not_called()
    async with session_factory() as session:
        item = (await session.execute(select(ReceiptItem))).scalars().one()
        rcpt = (await session.execute(select(Receipt))).scalars().one()
    assert item.gtin == "04630529181414"
    assert item.ntin == "0200141815130"
    assert rcpt.fiscal_id == "841061549277"
    assert rcpt.dedup_key is not None and ":q:wofd:" in rcpt.dedup_key


_NO_DATE_JSON = """
{
  "shop_name": "Магнум",
  "purchased_at": null,
  "currency": "KZT",
  "total_amount": 250.00,
  "fiscal_id": "555111",
  "items": [
    {"name": "Хлеб", "quantity": 1, "unit_price": 250.00,
     "total_price": 250.00, "barcode": null}
  ]
}
"""


async def test_duplicate_receipt_rejected(
    make_context: Callable[..., MagicMock],
    session_factory: async_sessionmaker[AsyncSession],
    seed_categories: list[Category],
    test_owner_member: FamilyMember,
) -> None:
    classify_json = (
        f'[{{"index": 0, "category_id": {seed_categories[0].id},'
        ' "confidence": 0.95}]'
    )
    context = _photo_context(
        make_context,
        session_factory,
        vision_json=_NO_DATE_JSON,
        classify_json=classify_json,
    )
    first = make_update(chat_id=test_owner_member.chat_id, photo=True)
    await receipt.photo_handler(first, context)
    second = make_update(chat_id=test_owner_member.chat_id, photo=True)
    await receipt.photo_handler(second, context)

    status = second.message.reply_text.return_value
    assert "уже добавлен" in status.edit_text.await_args.args[0]
    async with session_factory() as session:
        receipts = (await session.execute(select(Receipt))).scalars().all()
    assert len(receipts) == 1


async def test_no_date_saves_now_and_prompts(
    make_context: Callable[..., MagicMock],
    session_factory: async_sessionmaker[AsyncSession],
    seed_categories: list[Category],
    test_owner_member: FamilyMember,
) -> None:
    classify_json = (
        f'[{{"index": 0, "category_id": {seed_categories[0].id},'
        ' "confidence": 0.95}]'
    )
    context = _photo_context(
        make_context,
        session_factory,
        vision_json=_NO_DATE_JSON,
        classify_json=classify_json,
    )
    update = make_update(chat_id=test_owner_member.chat_id, photo=True)
    await receipt.photo_handler(update, context)

    # A date prompt (with keyboard) was sent and a pending date is tracked.
    prompted = any(
        call.kwargs.get("reply_markup") is not None
        for call in update.message.reply_text.await_args_list
    )
    assert prompted
    assert "awaiting_receipt_date" in context.user_data
    async with session_factory() as session:
        rcpt = (await session.execute(select(Receipt))).scalars().one()
    assert rcpt.fiscal_id == "555111"
    assert rcpt.purchased_at is not None


async def test_date_callback_sets_relative_date(
    make_context: Callable[..., MagicMock],
    session_factory: async_sessionmaker[AsyncSession],
    db_session: AsyncSession,
    test_owner_member: FamilyMember,
) -> None:
    from datetime import UTC, datetime, timedelta
    from decimal import Decimal

    saved = await receipt_repo.save_receipt_with_items(
        db_session,
        member_id=test_owner_member.id,
        shop_name="Shop",
        purchased_at=datetime(2020, 1, 1, tzinfo=UTC),
        total_amount=Decimal("100"),
        currency="KZT",
        photo_file_id="f",
        raw_claude_json={},
        dedup_key="x:1",
        items=[],
    )
    await db_session.commit()

    context = make_context()
    update = make_update(callback_data=f"rdate:{saved.id}:yesterday")
    await receipt.date_callback(update, context)

    async with session_factory() as session:
        rcpt = await receipt_repo.get_receipt(session, saved.id)
    assert rcpt is not None
    # purchased_at set to yesterday (relative to now), independent of today.
    expected = (datetime.now(UTC) - timedelta(days=1)).date()
    assert rcpt.purchased_at.date() == expected


async def test_date_text_handler_parses_manual_date(
    make_context: Callable[..., MagicMock],
    session_factory: async_sessionmaker[AsyncSession],
    db_session: AsyncSession,
    test_owner_member: FamilyMember,
) -> None:
    from datetime import UTC, date, datetime
    from decimal import Decimal

    saved = await receipt_repo.save_receipt_with_items(
        db_session,
        member_id=test_owner_member.id,
        shop_name="Shop",
        purchased_at=datetime(2026, 5, 30, tzinfo=UTC),
        total_amount=Decimal("100"),
        currency="KZT",
        photo_file_id="f",
        raw_claude_json={},
        dedup_key="x:2",
        items=[],
    )
    await db_session.commit()

    context = make_context()
    context.user_data["awaiting_receipt_date"] = saved.id
    update = make_update(chat_id=test_owner_member.chat_id, text="15.05.2026")
    await receipt.date_text_handler(update, context)

    async with session_factory() as session:
        rcpt = await receipt_repo.get_receipt(session, saved.id)
    assert rcpt is not None
    assert rcpt.purchased_at.date() == date(2026, 5, 15)
    assert "awaiting_receipt_date" not in context.user_data


async def test_manual_subcategory_learns_parent(
    make_context: Callable[..., MagicMock],
    session_factory: async_sessionmaker[AsyncSession],
    seed_categories: list[Category],
    test_owner_member: FamilyMember,
    db_session: AsyncSession,
) -> None:
    from datetime import UTC, datetime
    from decimal import Decimal

    from bot.db.repository import category as category_repo

    deti = next(c for c in seed_categories if c.name == "Дети")
    ilya = await category_repo.create_category(
        db_session,
        name="Илья",
        family_id=test_owner_member.family_id,
        parent_id=deti.id,
    )
    await db_session.commit()
    saved = await receipt_repo.save_receipt_with_items(
        db_session,
        member_id=test_owner_member.id,
        shop_name="Shop",
        purchased_at=datetime(2026, 5, 1, tzinfo=UTC),
        total_amount=Decimal("100"),
        currency="KZT",
        photo_file_id="f",
        raw_claude_json={},
        items=[
            receipt_repo.ItemRow(
                name="Игрушка",
                quantity=Decimal(1),
                unit_price=Decimal("100"),
                total_price=Decimal("100"),
                gtin="4870001112223",
            )
        ],
    )
    await db_session.commit()
    item_id = saved.items[0].id

    context = make_context()
    update = make_update(callback_data=f"cat:{item_id}:{ilya.id}")
    await receipt.category_callback(update, context)

    async with session_factory() as session:
        product = await product_repo.get_by_gtin(session, "4870001112223")
        item = (
            await session.execute(select(ReceiptItem).where(ReceiptItem.id == item_id))
        ).scalar_one()
    # Item keeps the subcategory; catalog learned the PARENT (top-level).
    assert item.category_id == ilya.id
    assert product is not None
    assert product.category_id == deti.id


async def test_category_drill_and_back_callbacks(
    make_context: Callable[..., MagicMock],
    session_factory: async_sessionmaker[AsyncSession],
    seed_categories: list[Category],
    test_owner_member: FamilyMember,
    db_session: AsyncSession,
) -> None:
    from bot.db.repository import category as category_repo

    deti = next(c for c in seed_categories if c.name == "Дети")
    await category_repo.create_category(
        db_session,
        name="Илья",
        family_id=test_owner_member.family_id,
        parent_id=deti.id,
    )
    await db_session.commit()
    context = make_context()

    drill = make_update(
        chat_id=test_owner_member.chat_id, callback_data=f"catd:1:{deti.id}"
    )
    await receipt.category_drill_callback(drill, context)
    drill.callback_query.edit_message_reply_markup.assert_awaited()

    back = make_update(chat_id=test_owner_member.chat_id, callback_data="catb:1")
    await receipt.category_back_callback(back, context)
    back.callback_query.edit_message_reply_markup.assert_awaited()
