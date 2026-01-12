# -*- coding: utf-8 -*-

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def nav_kb(*, back_cb: str, home_cb: str = "back") -> InlineKeyboardMarkup:
    """
    Универсальная навигация:
    - back_cb: куда ведёт "⬅️ Назад"
    - home_cb: куда ведёт "🏠 Главное меню" (по умолчанию -> callback 'back')
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⬅️ Назад", callback_data=back_cb),
            InlineKeyboardButton(text="🏠 Главное меню", callback_data=home_cb),
        ]
    ])
