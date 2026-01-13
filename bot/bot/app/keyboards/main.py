# -*- coding: utf-8 -*-

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu(is_admin: bool, *, has_subscription: bool) -> InlineKeyboardMarkup:
    """
    Главное меню (по ТЗ пользователя):
    - На старте НЕ показываем Устройства/Режимы/Трафик/Рефералы
    - Только: Управление(если активна)/Купить(если нет), Поддержка, FAQ (+ Admin)
    """
    rows = []

    if has_subscription:
        rows.append([InlineKeyboardButton(text="⚙️ Управление", callback_data="buy")])
        rows.append([InlineKeyboardButton(text="💳 Подключить подписку", callback_data="buy:plans")])
    else:
        rows.append([InlineKeyboardButton(text="💳 Подключить подписку", callback_data="buy")])

    rows.append([
        InlineKeyboardButton(text="🆘 Поддержка", callback_data="support"),
        InlineKeyboardButton(text="❓ FAQ", callback_data="faq"),
    ])
    if is_admin:
        rows.append([InlineKeyboardButton(text="🛠 Admin", callback_data="admin")])

    return InlineKeyboardMarkup(inline_keyboard=rows)
