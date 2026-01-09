# -*- coding: utf-8 -*-

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def subscription_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text='🔄 Продлить', callback_data='buy:plans'),
            InlineKeyboardButton(text='🛠 Сменить тариф', callback_data='buy:plans'),
        ],
        [InlineKeyboardButton(text='🧾 История оплат', callback_data='sub:history')],
        [
            InlineKeyboardButton(text='⬅️ Назад', callback_data='buy'),
            InlineKeyboardButton(text='🏠 Главное меню', callback_data='back'),
        ],
    ])