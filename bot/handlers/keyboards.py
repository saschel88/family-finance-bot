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


def category_keyboard(
    item_id: int, categories: list[Category], columns: int = 2
) -> InlineKeyboardMarkup:
    """Inline keyboard to pick a category for an uncertain receipt item.

    callback_data format: ``cat:{item_id}:{category_id}``.
    """
    buttons = [
        InlineKeyboardButton(
            f"{c.emoji} {c.name}",
            callback_data=f"cat:{item_id}:{c.id}",
        )
        for c in categories
    ]
    rows = [buttons[i : i + columns] for i in range(0, len(buttons), columns)]
    return InlineKeyboardMarkup(rows)
