from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.db.models import Category, FamilyMember, Receipt, ReceiptItem
from bot.db.repository import receipt as receipt_repo
from bot.handlers import reports
from bot.services.reporter import Reporter
from tests.conftest import make_update


def _ctx(
    make_context: Callable[..., MagicMock],
    session_factory: async_sessionmaker[AsyncSession],
) -> MagicMock:
    return make_context(reporter=Reporter(session_factory))


async def _seed_receipt(
    session_factory: async_sessionmaker[AsyncSession],
    member: FamilyMember,
    when: datetime,
    amount: Decimal,
    category_id: int,
) -> int:
    async with session_factory() as session:
        async with session.begin():
            receipt = await receipt_repo.save_receipt_with_items(
                session,
                member_id=member.id,
                shop_name="Магнум",
                purchased_at=when,
                total_amount=amount,
                currency="KZT",
                photo_file_id="f",
                raw_claude_json={},
                items=[
                    receipt_repo.ItemRow(
                        name="Хлеб",
                        quantity=Decimal(1),
                        unit_price=amount,
                        total_price=amount,
                        category_id=category_id,
                    )
                ],
            )
            return receipt.id


async def test_report_command_renders(
    make_context: Callable[..., MagicMock],
    session_factory: async_sessionmaker[AsyncSession],
    seed_categories: list[Category],
    test_owner_member: FamilyMember,
) -> None:
    update = make_update(chat_id=test_owner_member.chat_id)
    context = _ctx(make_context, session_factory)
    await reports.report_command(update, context)
    call = update.message.reply_text.await_args
    assert call.kwargs.get("reply_markup") is not None


async def test_rep_callback_switch_mode(
    make_context: Callable[..., MagicMock],
    session_factory: async_sessionmaker[AsyncSession],
    seed_categories: list[Category],
    test_owner_member: FamilyMember,
) -> None:
    update = make_update(
        chat_id=test_owner_member.chat_id, callback_data="rep:v:month:own:sum:0"
    )
    context = _ctx(make_context, session_factory)
    await reports.rep_callback(update, context)
    update.callback_query.edit_message_text.assert_awaited()


async def test_list_mode_and_open_card(
    make_context: Callable[..., MagicMock],
    session_factory: async_sessionmaker[AsyncSession],
    seed_categories: list[Category],
    test_owner_member: FamilyMember,
) -> None:
    rid = await _seed_receipt(
        session_factory,
        test_owner_member,
        datetime.now(UTC),
        Decimal("250.00"),
        seed_categories[0].id,
    )
    context = _ctx(make_context, session_factory)
    lst = make_update(
        chat_id=test_owner_member.chat_id, callback_data="rep:v:month:own:list:0"
    )
    await reports.rep_callback(lst, context)
    lst.callback_query.edit_message_text.assert_awaited()

    card = make_update(chat_id=test_owner_member.chat_id, callback_data=f"rcp:o:{rid}")
    await reports.rcp_callback(card, context)
    text = card.callback_query.edit_message_text.await_args.args[0]
    assert "Магнум" in text


async def test_edit_receipt_total(
    make_context: Callable[..., MagicMock],
    session_factory: async_sessionmaker[AsyncSession],
    seed_categories: list[Category],
    test_owner_member: FamilyMember,
) -> None:
    rid = await _seed_receipt(
        session_factory,
        test_owner_member,
        datetime.now(UTC),
        Decimal("250.00"),
        seed_categories[0].id,
    )
    context = _ctx(make_context, session_factory)
    context.user_data[reports._PENDING] = {"kind": "rtotal", "id": rid}
    update = make_update(chat_id=test_owner_member.chat_id, text="2000,50")
    await reports.report_text_handler(update, context)
    async with session_factory() as session:
        receipt = await receipt_repo.get_receipt(session, rid)
    assert receipt is not None and receipt.total_amount == Decimal("2000.50")
    assert reports._PENDING not in context.user_data


async def test_delete_receipt_confirmed(
    make_context: Callable[..., MagicMock],
    session_factory: async_sessionmaker[AsyncSession],
    seed_categories: list[Category],
    test_owner_member: FamilyMember,
) -> None:
    rid = await _seed_receipt(
        session_factory,
        test_owner_member,
        datetime.now(UTC),
        Decimal("250.00"),
        seed_categories[0].id,
    )
    context = _ctx(make_context, session_factory)
    update = make_update(
        chat_id=test_owner_member.chat_id, callback_data=f"rcp:drc:{rid}"
    )
    await reports.rcp_callback(update, context)
    async with session_factory() as session:
        assert await receipt_repo.get_receipt(session, rid) is None
        items = (await session.execute(select(ReceiptItem))).scalars().all()
    assert items == []


async def test_manual_add_flow(
    make_context: Callable[..., MagicMock],
    session_factory: async_sessionmaker[AsyncSession],
    seed_categories: list[Category],
    test_owner_member: FamilyMember,
) -> None:
    context = _ctx(make_context, session_factory)
    cat = seed_categories[1]
    pick = make_update(
        chat_id=test_owner_member.chat_id, callback_data=f"add:cat:{cat.id}"
    )
    await reports.add_cat_callback(pick, context)
    assert context.user_data[reports._PENDING]["kind"] == "add"

    text = make_update(chat_id=test_owner_member.chat_id, text="Кофе 1500")
    await reports.report_text_handler(text, context)
    async with session_factory() as session:
        receipt = (await session.execute(select(Receipt))).scalars().one()
        item = (await session.execute(select(ReceiptItem))).scalars().one()
    assert receipt.total_amount == Decimal("1500")
    assert receipt.dedup_key is None  # manual entries are never deduplicated
    assert item.name == "Кофе"
    assert item.category_id == cat.id
    assert item.is_manual is True


async def test_manual_add_amount_only(
    make_context: Callable[..., MagicMock],
    session_factory: async_sessionmaker[AsyncSession],
    seed_categories: list[Category],
    test_owner_member: FamilyMember,
) -> None:
    context = _ctx(make_context, session_factory)
    cat = seed_categories[0]
    context.user_data[reports._PENDING] = {"kind": "add", "id": cat.id}
    text = make_update(chat_id=test_owner_member.chat_id, text="1500")
    await reports.report_text_handler(text, context)
    async with session_factory() as session:
        item = (await session.execute(select(ReceiptItem))).scalars().one()
    # No name → falls back to category name.
    assert item.name == cat.name
    assert item.total_price == Decimal("1500")


async def test_category_management_add_subcategory(
    make_context: Callable[..., MagicMock],
    session_factory: async_sessionmaker[AsyncSession],
    seed_categories: list[Category],
    test_owner_member: FamilyMember,
) -> None:
    from bot.db.repository import category as category_repo

    deti = next(c for c in seed_categories if c.name == "Дети")
    context = _ctx(make_context, session_factory)
    pick = make_update(
        chat_id=test_owner_member.chat_id, callback_data=f"cm:addsub:{deti.id}"
    )
    await reports.cm_callback(pick, context)
    assert context.user_data[reports._PENDING] == {
        "kind": "cat_add",
        "parent_id": deti.id,
    }
    txt = make_update(chat_id=test_owner_member.chat_id, text="Илья")
    await reports.report_text_handler(txt, context)
    async with session_factory() as session:
        cats = await category_repo.list_for_family(session, test_owner_member.family_id)
    ilya = next((c for c in cats if c.name == "Илья"), None)
    assert ilya is not None
    assert ilya.parent_id == deti.id
    assert ilya.family_id == test_owner_member.family_id


async def test_categories_menu_renders(
    make_context: Callable[..., MagicMock],
    session_factory: async_sessionmaker[AsyncSession],
    seed_categories: list[Category],
    test_owner_member: FamilyMember,
) -> None:
    update = make_update(chat_id=test_owner_member.chat_id)
    context = _ctx(make_context, session_factory)
    await reports.categories_menu(update, context)
    assert update.message.reply_text.await_args.kwargs.get("reply_markup") is not None


async def test_cm_add_top_level_category(
    make_context: Callable[..., MagicMock],
    session_factory: async_sessionmaker[AsyncSession],
    seed_categories: list[Category],
    test_owner_member: FamilyMember,
) -> None:
    from bot.db.repository import category as category_repo

    context = _ctx(make_context, session_factory)
    await reports.cm_callback(
        make_update(chat_id=test_owner_member.chat_id, callback_data="cm:addtop"),
        context,
    )
    assert context.user_data[reports._PENDING] == {"kind": "cat_add", "parent_id": None}
    await reports.report_text_handler(
        make_update(chat_id=test_owner_member.chat_id, text="Хобби"), context
    )
    async with session_factory() as session:
        cats = await category_repo.list_for_family(session, test_owner_member.family_id)
    hobby = next((c for c in cats if c.name == "Хобби"), None)
    assert hobby is not None and hobby.parent_id is None and hobby.family_id is not None


async def test_cm_addsubpick_lists_parents(
    make_context: Callable[..., MagicMock],
    session_factory: async_sessionmaker[AsyncSession],
    seed_categories: list[Category],
    test_owner_member: FamilyMember,
) -> None:
    context = _ctx(make_context, session_factory)
    upd = make_update(chat_id=test_owner_member.chat_id, callback_data="cm:addsubpick")
    await reports.cm_callback(upd, context)
    upd.callback_query.edit_message_text.assert_awaited()


async def test_cm_edit_rename_delete(
    make_context: Callable[..., MagicMock],
    session_factory: async_sessionmaker[AsyncSession],
    seed_categories: list[Category],
    test_owner_member: FamilyMember,
    db_session: AsyncSession,
) -> None:
    from bot.db.repository import category as category_repo

    cat = await category_repo.create_category(
        db_session, name="Хобби", family_id=test_owner_member.family_id
    )
    await db_session.commit()
    context = _ctx(make_context, session_factory)

    await reports.cm_callback(
        make_update(chat_id=test_owner_member.chat_id, callback_data="cm:editlist"),
        context,
    )
    await reports.cm_callback(
        make_update(
            chat_id=test_owner_member.chat_id, callback_data=f"cm:edit:{cat.id}"
        ),
        context,
    )
    # rename
    await reports.cm_callback(
        make_update(
            chat_id=test_owner_member.chat_id, callback_data=f"cm:ren:{cat.id}"
        ),
        context,
    )
    assert context.user_data[reports._PENDING] == {"kind": "cat_rename", "id": cat.id}
    await reports.report_text_handler(
        make_update(chat_id=test_owner_member.chat_id, text="Хобби 2"), context
    )
    # delete
    await reports.cm_callback(
        make_update(
            chat_id=test_owner_member.chat_id, callback_data=f"cm:delc:{cat.id}"
        ),
        context,
    )
    async with session_factory() as session:
        assert await category_repo.get_category(session, cat.id) is None


async def test_rcp_item_category_drilldown(
    make_context: Callable[..., MagicMock],
    session_factory: async_sessionmaker[AsyncSession],
    seed_categories: list[Category],
    test_owner_member: FamilyMember,
    db_session: AsyncSession,
) -> None:
    from bot.db.repository import category as category_repo

    deti = next(c for c in seed_categories if c.name == "Дети")
    ilya = await category_repo.create_category(
        db_session,
        name="Илья",
        family_id=test_owner_member.family_id,
        parent_id=deti.id,
    )
    rid = await _seed_receipt(
        session_factory, test_owner_member, datetime.now(UTC), Decimal("100"), deti.id
    )
    await db_session.commit()
    async with session_factory() as session:
        rcpt = await receipt_repo.get_receipt(session, rid)
        item_id = rcpt.items[0].id
    context = _ctx(make_context, session_factory)

    # open item category picker (top-level with drill-down)
    await reports.rcp_callback(
        make_update(
            chat_id=test_owner_member.chat_id, callback_data=f"rcp:ic:{item_id}"
        ),
        context,
    )
    # drill into Дети
    await reports.rcp_callback(
        make_update(
            chat_id=test_owner_member.chat_id,
            callback_data=f"rcp:scd:{item_id}:{deti.id}",
        ),
        context,
    )
    # select Илья
    await reports.rcp_callback(
        make_update(
            chat_id=test_owner_member.chat_id,
            callback_data=f"rcp:sc:{item_id}:{ilya.id}",
        ),
        context,
    )
    async with session_factory() as session:
        item = (
            await session.execute(select(ReceiptItem).where(ReceiptItem.id == item_id))
        ).scalar_one()
    assert item.category_id == ilya.id
