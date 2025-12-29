# -*- coding: utf-8 -*-

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from ..models import Device
from ..services.devices import type_title


def devices_list_kb(devices: list[Device], *, can_add: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for d in devices:
        status = '✅' if d.status == 'active' else '⛔️'
        title = f"{status} {type_title(d.device_type)} {d.label or ''}".strip()
        rows.append([InlineKeyboardButton(text=title, callback_data=f'dev:{d.id}')])

    if can_add:
        rows.append([InlineKeyboardButton(text='➕ Добавить устройство', callback_data='dev_add')])

    rows.append([InlineKeyboardButton(text='⬅️ Назад', callback_data='back')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def device_menu_kb(device_id: int, *, is_active: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text='🔗 Получить конфиг', callback_data=f'dev_cfg:{device_id}')],
        [InlineKeyboardButton(text='✏️ Переименовать', callback_data=f'dev_rename:{device_id}')],
        [InlineKeyboardButton(text='🧪 Проверить доступ', callback_data=f'dev_check:{device_id}')],
    ]
    if is_active:
        rows.append([InlineKeyboardButton(text='⛔️ Отключить', callback_data=f'dev_toggle:{device_id}')])
    else:
        rows.append([InlineKeyboardButton(text='✅ Включить', callback_data=f'dev_toggle:{device_id}')])
    rows.append([InlineKeyboardButton(text='🗑 Удалить', callback_data=f'dev_del:{device_id}')])
    rows.append([InlineKeyboardButton(text='⬅️ Назад', callback_data='devices')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def device_type_kb() -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text='📱 Телефон', callback_data='devtype:phone'),
            InlineKeyboardButton(text='💻 ПК', callback_data='devtype:pc'),
        ],
        [
            InlineKeyboardButton(text='📺 ТВ', callback_data='devtype:tv'),
            InlineKeyboardButton(text='📟 Планшет', callback_data='devtype:tablet'),
        ],
        [
            InlineKeyboardButton(text='📡 Роутер', callback_data='devtype:router'),
            InlineKeyboardButton(text='🔧 Другое', callback_data='devtype:other'),
        ],
        [InlineKeyboardButton(text='⬅️ Назад', callback_data='devices')],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)
