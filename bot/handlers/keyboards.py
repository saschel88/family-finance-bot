from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from bot.db.models import Category

CHOICE_CREATE = "onboard:create"
CHOICE_JOIN = "onboard:join"


def choice_keyboard() -> InlineKeyboardMarkup:
    """Onboarding choice: create a new family or join via invite."""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Создать семью", callback_data=CHOICE_CREATE)],
            [InlineKeyboardButton("Войти по приглашению", callback_data=CHOICE_JOIN)],
        ]
    )


def date_keyboard(receipt_id: int) -> InlineKeyboardMarkup:
    """Quick date choices for a receipt with no recognized date.

    callback_data format: ``rdate:{receipt_id}:{today|yesterday|dby|manual}``.
    """
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Сегодня", callback_data=f"rdate:{receipt_id}:today"
                ),
                InlineKeyboardButton(
                    "Вчера", callback_data=f"rdate:{receipt_id}:yesterday"
                ),
                InlineKeyboardButton(
                    "Позавчера", callback_data=f"rdate:{receipt_id}:dby"
                ),
            ],
            [
                InlineKeyboardButton(
                    "Ввести дату", callback_data=f"rdate:{receipt_id}:manual"
                )
            ],
        ]
    )


def _grid(
    buttons: list[InlineKeyboardButton], columns: int
) -> list[list[InlineKeyboardButton]]:
    return [buttons[i : i + columns] for i in range(0, len(buttons), columns)]


def category_tree_keyboard(
    item_id: int,
    categories: list[Category],
    *,
    sel: str = "cat",
    drill: str = "catd",
    columns: int = 2,
) -> InlineKeyboardMarkup:
    """Top-level category picker with drill-down into subcategories.

    A category that has children gets a "▸" button that drills in (``drill``);
    a leaf selects directly (``sel``). Callback format:
    ``{sel}:{item_id}:{category_id}`` / ``{drill}:{item_id}:{parent_id}``.
    """
    parents_with_children = {c.parent_id for c in categories if c.parent_id is not None}
    buttons: list[InlineKeyboardButton] = []
    for c in categories:
        if c.parent_id is not None:
            continue  # top-level only at this level
        if c.id in parents_with_children:
            buttons.append(
                InlineKeyboardButton(
                    f"{c.emoji} {c.name} ▸",
                    callback_data=f"{drill}:{item_id}:{c.id}",
                )
            )
        else:
            buttons.append(
                InlineKeyboardButton(
                    f"{c.emoji} {c.name}", callback_data=f"{sel}:{item_id}:{c.id}"
                )
            )
    return InlineKeyboardMarkup(_grid(buttons, columns))


def category_children_keyboard(
    item_id: int,
    parent: Category,
    children: list[Category],
    *,
    sel: str = "cat",
    back: str = "catb",
    columns: int = 2,
) -> InlineKeyboardMarkup:
    """Subcategory picker: children + "‹parent› (общее)" + back."""
    buttons = [
        InlineKeyboardButton(
            f"{c.emoji} {c.name}", callback_data=f"{sel}:{item_id}:{c.id}"
        )
        for c in children
    ]
    rows = _grid(buttons, columns)
    rows.append(
        [
            InlineKeyboardButton(
                f"{parent.emoji} {parent.name} (общее)",
                callback_data=f"{sel}:{item_id}:{parent.id}",
            )
        ]
    )
    rows.append([InlineKeyboardButton("‹ Назад", callback_data=f"{back}:{item_id}")])
    return InlineKeyboardMarkup(rows)
