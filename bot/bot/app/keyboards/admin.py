# -*- coding: utf-8 -*-

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from ..models import Order


def admin_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='📊 Дашборд', callback_data='admin:dashboard')],
        [InlineKeyboardButton(text='🔎 Пользователь', callback_data='admin:user')],
        [InlineKeyboardButton(text='💳 Платежи', callback_data='admin:payments')],
        [InlineKeyboardButton(text='📦 Подписки', callback_data='admin:subs')],
        [InlineKeyboardButton(text='📈 Трафик', callback_data='admin:traffic')],
        [InlineKeyboardButton(text='🧪 Качество', callback_data='admin:quality')],
        [InlineKeyboardButton(text='⚙️ Настройки', callback_data='admin:settings')],
        [InlineKeyboardButton(text='🧾 Ожидают оплаты', callback_data='admin:pending')],
        [InlineKeyboardButton(text='⬅️ Назад', callback_data='back')],
    ])


def admin_order_action_kb(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text='✅ Подтвердить', callback_data=f'admin:approve:{order_id}'),
            InlineKeyboardButton(text='❌ Отклонить', callback_data=f'admin:cancel:{order_id}'),
        ],
        [InlineKeyboardButton(text='⬅️ Назад', callback_data='admin:pending')],
    ])

def admin_order_actions_kb(order: Order) -> InlineKeyboardMarkup:
    return admin_order_action_kb(order.id)


def admin_orders_kb(orders: list[Order]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for order in orders:
        rows.append([
            InlineKeyboardButton(text=f'✅ #{order.id}', callback_data=f'admin:approve:{order.id}'),
            InlineKeyboardButton(text='❌', callback_data=f'admin:cancel:{order.id}'),
        ])
    rows.append([InlineKeyboardButton(text='⬅️ Назад', callback_data='admin')])
    return InlineKeyboardMarkup(inline_keyboard=rows)