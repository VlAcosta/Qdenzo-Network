# -*- coding: utf-8 -*-

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

PROFILES = [
    ("smart", "🧠 Smart", "Баланс стабильности/скорости; self-healing умеренный."),
    ("stream", "🍿 Streaming", "Throughput ↑, packet loss ↓, минимум перестроек."),
    ("game", "🎮 Gaming", "Latency ↓, jitter ↓, быстрый failover."),
    ("low", "📶 Low Internet", "Стабильность ↑, меньше реконнектов; осторожный self-healing."),
    ("work", "💼 Work", "Стабильность ↑, packet loss ↓; плавные перестроения."),
    ("kids", "🧒 Kids Safe", "Ограничения/безопасные настройки (для Family)."),
]


def profiles_kb(current: str | None, *, allowed: set[str]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for code, title, _ in PROFILES:
        is_current = (current == code)
        is_allowed = (code in allowed)
        prefix = "✅ " if is_current else ""
        lock = "" if is_allowed else " 🔒"
        rows.append([InlineKeyboardButton(text=f"{prefix}{title}{lock}", callback_data=f"profile:{code}")])

    rows.append([
        InlineKeyboardButton(text="⬅️ Назад", callback_data="back"),
        InlineKeyboardButton(text="🏠 Главное меню", callback_data="back"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def profile_apply_kb(code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ К аккаунту", callback_data=f"profile_apply:account:{code}"),
            InlineKeyboardButton(text="📱 К устройству", callback_data=f"profile_apply:device:{code}"),
        ],
        [
            InlineKeyboardButton(text="⬅️ Назад", callback_data="profiles"),
            InlineKeyboardButton(text="🏠 Главное меню", callback_data="back"),
        ],
    ])


def profile_devices_kb(code: str, devices: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for device_id, title in devices:
        rows.append([InlineKeyboardButton(text=title, callback_data=f"profile_device:{code}:{device_id}")])

    rows.append([
        InlineKeyboardButton(text="⬅️ Назад", callback_data="profiles"),
        InlineKeyboardButton(text="🏠 Главное меню", callback_data="back"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def profile_descr(code: str) -> str:
    for c, _, descr in PROFILES:
        if c == code:
            return descr
    return ""
