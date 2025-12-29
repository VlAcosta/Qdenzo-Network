# -*- coding: utf-8 -*-

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


PROFILES = [
    ('smart', '🧠 Smart', 'Баланс стабильности/скорости; self-healing умеренный.'),
    ('stream', '🍿 Streaming', 'Throughput ↑, packet loss ↓, минимум перестроек.'),
    ('game', '🎮 Gaming', 'Latency ↓, jitter ↓, быстрый failover.'),
    ('low', '📶 Low Internet', 'Стабильность ↑, меньше реконнектов; осторожный self-healing.'),
    ('work', '💼 Work', 'Стабильность ↑, packet loss ↓; плавные перестроения.'),
    ('kids', '🧒 Kids Safe', 'Ограничения по расписанию/лимитам; безопасные настройки.'),
]


def profiles_kb(current: str | None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for code, title, _ in PROFILES:
        prefix = '✅ ' if current == code else ''
        rows.append([InlineKeyboardButton(text=prefix + title, callback_data=f'profile:{code}')])
    rows.append([InlineKeyboardButton(text='⬅️ Назад', callback_data='back')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def profile_apply_kb(code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text='✅ К аккаунту', callback_data=f'profile_apply:account:{code}'),
            InlineKeyboardButton(text='📱 К устройству', callback_data=f'profile_apply:device:{code}'),
        ],
        [InlineKeyboardButton(text='⬅️ Назад', callback_data='profiles')],
    ])


def profile_devices_kb(code: str, devices: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for device_id, title in devices:
        rows.append([InlineKeyboardButton(text=title, callback_data=f'profile_device:{code}:{device_id}')])
    rows.append([InlineKeyboardButton(text='⬅️ Назад', callback_data='profiles')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def profile_descr(code: str) -> str:
    for c, _, descr in PROFILES:
        if c == code:
            return descr
    return ''
