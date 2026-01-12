# -*- coding: utf-8 -*-

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from .nav import nav_kb

PROFILES = [
    ("smart", "🧠 Smart", "Баланс стабильности/скорости; self-healing умеренный."),
    ("stream", "🍿 Streaming", "Throughput ↑, packet loss ↓, минимум перестроек."),
    ("game", "🎮 Gaming", "Latency ↓, jitter ↓, быстрый failover."),
    ("low", "📶 Low Internet", "Стабильность ↑, меньше реконнектов; осторожный self-healing."),
    ("work", "💼 Work", "Стабильность ↑, packet loss ↓; плавные перестроения."),
    ("kids", "🧒 Kids Safe", "Ограничения/безопасные настройки (для Family)."),
]


def modes_root_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="👤 К аккаунту", callback_data="profiles:account"),
            InlineKeyboardButton(text="📱 К устройству", callback_data="profiles:device"),
        ],
        nav_kb(back_cb="buy", home_cb="back").inline_keyboard[0],
    ])


def profiles_account_kb(current: str | None, *, allowed: set[str]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = _profiles_rows(
        current=current,
        allowed=allowed,
        cb_builder=lambda code: f"profile_apply:account:{code}",
    )
    rows.append(nav_kb(back_cb="profiles", home_cb="back").inline_keyboard[0])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def profiles_device_list_kb(devices: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for device_id, title in devices:
        rows.append([InlineKeyboardButton(text=title, callback_data=f"profiles:device:{device_id}")])
    rows.append(nav_kb(back_cb="profiles", home_cb="back").inline_keyboard[0])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def profiles_device_modes_kb(device_id: int, current: str | None, *, allowed: set[str]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = _profiles_rows(
        current=current,
        allowed=allowed,
        cb_builder=lambda code: f"profile_apply:device:{device_id}:{code}",
    )
    rows.append(nav_kb(back_cb="profiles:device", home_cb="back").inline_keyboard[0])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def _profiles_rows(
    *,
    current: str | None,
    allowed: set[str],
    cb_builder,
) -> list[list[InlineKeyboardButton]]:
    rows: list[list[InlineKeyboardButton]] = []
    for code, title, _ in PROFILES:
        is_current = (current == code)
        is_allowed = (code in allowed)
        prefix = "✅ " if is_current else ""
        lock = "" if is_allowed else " 🔒"
        rows.append([InlineKeyboardButton(text=f"{prefix}{title}{lock}", callback_data=cb_builder(code))])
    return rows


def profile_descr(code: str) -> str:
    for c, _, descr in PROFILES:
        if c == code:
            return descr
    return ""
