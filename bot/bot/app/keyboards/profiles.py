# -*- coding: utf-8 -*-

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


PROFILES = [
    ('smart', '🧠 Smart', 'Авто-режим (по умолчанию)'),
    ('stream', '🍿 Streaming', 'Приоритет стабильности видео'),
    ('game', '🎮 Gaming', 'Минимальная задержка'),
    ('work', '💼 Work', 'Максимальная надёжность'),
    ('low', '📶 Low Internet', 'Экономия трафика и соединения'),
    ('kids', '🧒 Kids Safe', 'Мягкий фильтр / безопасный режим'),
]


def profiles_kb(current: str | None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for code, title, _ in PROFILES:
        prefix = '✅ ' if current == code else ''
        rows.append([InlineKeyboardButton(text=prefix + title, callback_data=f'mode:{code}')])
    rows.append([InlineKeyboardButton(text='⬅️ Назад', callback_data='back')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def profile_descr(code: str) -> str:
    for c, _, descr in PROFILES:
        if c == code:
            return descr
    return ''
