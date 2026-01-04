# -*- coding: utf-8 -*-

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from ..models import Device
from ..services.devices import DEVICE_TYPES


def _type_title(device_type: str) -> str:
    return DEVICE_TYPES.get(device_type, device_type)


def devices_list_kb(devices: list[Device], *, can_add: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    for d in devices:
        if d.status == "deleted":
            continue
        status = "✅" if d.status == "active" else "❄️"
        title = f"{status} {_type_title(d.device_type)} {d.label or ''}".strip()
        rows.append([InlineKeyboardButton(text=title, callback_data=f"dev:view:{d.id}")])

    if can_add:
        rows.append([InlineKeyboardButton(text="➕ Подключить устройство", callback_data="dev:add")])

    rows.append([
        InlineKeyboardButton(text="⬅️ Назад", callback_data="back"),
        InlineKeyboardButton(text="🏠 Главное меню", callback_data="back"),
    ])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def device_type_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📱 Телефон", callback_data="dev:type:phone"),
            InlineKeyboardButton(text="💻 ПК", callback_data="dev:type:pc"),
        ],
        [
            InlineKeyboardButton(text="📺 ТВ", callback_data="dev:type:tv"),
            InlineKeyboardButton(text="📟 Планшет", callback_data="dev:type:tablet"),
        ],
        [
            InlineKeyboardButton(text="📡 Роутер", callback_data="dev:type:router"),
            InlineKeyboardButton(text="🔧 Другое", callback_data="dev:type:other"),
        ],
        [
            InlineKeyboardButton(text="⬅️ Назад", callback_data="devices"),
            InlineKeyboardButton(text="🏠 Главное меню", callback_data="back"),
        ],
    ])


def device_happ_kb(*, happ_url: str, continue_cb: str, back_cb: str) -> InlineKeyboardMarkup:
    """
    Экран "сначала открываем приложение/скрипт (Happ)".
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Открыть Happ / Приложение", url=happ_url)],
        [InlineKeyboardButton(text="✅ Я открыл приложение", callback_data=continue_cb)],
        [
            InlineKeyboardButton(text="⬅️ Назад", callback_data=back_cb),
            InlineKeyboardButton(text="🏠 Главное меню", callback_data="back"),
        ],
    ])


def device_menu_kb(device_id: int, *, is_active: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="🔗 Конфиг / Импорт", callback_data=f"dev:cfg:{device_id}")],
        [InlineKeyboardButton(text="🧪 Проверить доступ", callback_data=f"dev:check:{device_id}")],
        [InlineKeyboardButton(text="♻️ Перевыпустить конфиг", callback_data=f"dev:reissue:{device_id}")],
        [InlineKeyboardButton(text="✏️ Переименовать", callback_data=f"dev:rename:{device_id}")],
    ]

    if is_active:
        rows.append([InlineKeyboardButton(text="❄️ Заморозить", callback_data=f"dev:toggle:{device_id}")])
    else:
        rows.append([InlineKeyboardButton(text="✅ Разморозить", callback_data=f"dev:toggle:{device_id}")])

    rows.append([InlineKeyboardButton(text="🗑 Удалить", callback_data=f"dev:delete_confirm:{device_id}")])

    rows.append([
        InlineKeyboardButton(text="⬅️ Назад", callback_data="devices"),
        InlineKeyboardButton(text="🏠 Главное меню", callback_data="back"),
    ])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def device_delete_confirm_kb(device_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"dev:delete:{device_id}"),
            InlineKeyboardButton(text="❌ Отмена", callback_data=f"dev:view:{device_id}"),
        ],
        [
            InlineKeyboardButton(text="⬅️ Назад", callback_data=f"dev:view:{device_id}"),
            InlineKeyboardButton(text="🏠 Главное меню", callback_data="back"),
        ],
    ])
