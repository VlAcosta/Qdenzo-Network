# -*- coding: utf-8 -*-

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from ..models import Order


def admin_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🧾 Ожидают оплаты', callback_data='admin:pending')],
        [InlineKeyboardButton(text='🔎 Пользователь', callback_data='admin:find')],
        [InlineKeyboardButton(text='⬅️ Назад', callback_data='back')],
    ])


def admin_order_actions_kb(order: Order) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text='✅ Подтвердить', callback_data=f'admin:approve:{order.id}'),
            InlineKeyboardButton(text='❌ Отклонить', callback_data=f'admin:cancel:{order.id}'),
        ],
        [InlineKeyboardButton(text='⬅️ Назад', callback_data='admin:pending')],
    ])


def admin_orders_kb(orders: list[Order]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for order in orders:
        rows.append([
            InlineKeyboardButton(text=f'✅ #{order.id}', callback_data=f'admin:approve:{order.id}'),
            InlineKeyboardButton(text='❌', callback_data=f'admin:cancel:{order.id}'),
        ])
    rows.append([InlineKeyboardButton(text='⬅️ Назад', callback_data='admin')])
    return InlineKeyboardMarkup(inline_keyboard=rows)