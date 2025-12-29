# -*- coding: utf-8 -*-

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu(is_admin: bool) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text='🛒 Купить', callback_data='buy'),
            InlineKeyboardButton(text='📱 Устройства', callback_data='devices'),
        ],
        [
            InlineKeyboardButton(text='🧠 Режимы', callback_data='modes'),
            InlineKeyboardButton(text='📊 Трафик', callback_data='traffic'),
        ],
        [
            InlineKeyboardButton(text='🎁 Рефералы', callback_data='ref'),
            InlineKeyboardButton(text='🆘 Поддержка', callback_data='support'),
        ],
        [
            InlineKeyboardButton(text='❓ FAQ', callback_data='faq'),
        ],
    ]
    if is_admin:
        rows.append([InlineKeyboardButton(text='🛠 Admin', callback_data='admin')])
    return InlineKeyboardMarkup(inline_keyboard=rows)
