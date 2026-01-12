from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def traffic_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='➕ Докупить трафик', callback_data='traffic:buy')],
        [
            InlineKeyboardButton(text='⬅️ Назад', callback_data='buy'),
            InlineKeyboardButton(text='🏠 Главное меню', callback_data='back'),
        ],
    ])