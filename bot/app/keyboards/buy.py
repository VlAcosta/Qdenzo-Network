# -*- coding: utf-8 -*-

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def buy_manage_kb() -> InlineKeyboardMarkup:
    """
    Хаб управления (когда подписка активна).
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📱 Менеджер устройств", callback_data="devices")],
        [InlineKeyboardButton(text="📦 Тариф", callback_data="sub")],
        [InlineKeyboardButton(text="🧠 Режимы", callback_data="modes")],
        [InlineKeyboardButton(text="📊 Трафик", callback_data="traffic")],
        [
            InlineKeyboardButton(text="🆘 Поддержка", callback_data="support"),
            InlineKeyboardButton(text="❓ FAQ", callback_data="faq"),
        ],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back")],
    ])


def trial_activated_kb() -> InlineKeyboardMarkup:
    """
    Экран после Trial: ведём пользователя сразу к подключению.
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Подключить устройство", callback_data="dev:add")],
        [InlineKeyboardButton(text="📱 Мои устройства", callback_data="devices")],
        [
            InlineKeyboardButton(text="⬅️ Назад", callback_data="buy"),
            InlineKeyboardButton(text="🏠 Главное меню", callback_data="back"),
        ],
    ])
