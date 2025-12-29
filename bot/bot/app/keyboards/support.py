from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def support_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text='❓ FAQ', callback_data='faq'),
            InlineKeyboardButton(text='🩺 Диагностика', callback_data='support:diag'),
        ],
        [InlineKeyboardButton(text='✉️ Написать оператору', callback_data='support:chat')],
        [InlineKeyboardButton(text='⬅️ Главное меню', callback_data='back')],
    ])