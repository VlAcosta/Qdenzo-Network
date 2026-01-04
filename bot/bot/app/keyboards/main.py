# -*- coding: utf-8 -*-

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu(is_admin: bool, *, has_subscription: bool) -> InlineKeyboardMarkup:
    """
    Главное меню (по ТЗ пользователя):
    - На старте НЕ показываем Устройства/Режимы/Трафик/Рефералы
    - Только: Управление(если активна)/Купить(если нет), Поддержка, FAQ (+ Admin)
    """
    first = "⚙️ Управление" if has_subscription else "🛒 Купить"

    rows = [
        [InlineKeyboardButton(text=first, callback_data="buy")],
        [
            InlineKeyboardButton(text="🆘 Поддержка", callback_data="support"),
            InlineKeyboardButton(text="❓ FAQ", callback_data="faq"),
        ],
    ]
    if is_admin:
        rows.append([InlineKeyboardButton(text="🛠 Admin", callback_data="admin")])

    return InlineKeyboardMarkup(inline_keyboard=rows)
