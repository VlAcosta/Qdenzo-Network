# -*- coding: utf-8 -*-

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from ..models import Order
from ..services.catalog import PlanOption, plan_title
from ..utils.text import months_title


def admin_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='📊 Дашборд', callback_data='admin:dashboard')],
        [InlineKeyboardButton(text='🔎 Пользователь', callback_data='admin:user')],
        [InlineKeyboardButton(text='💳 Платежи', callback_data='admin:payments')],
        [InlineKeyboardButton(text='📦 Подписки', callback_data='admin:subs')],
        [InlineKeyboardButton(text='🎟 Промокоды', callback_data='admin:promos')],
        [InlineKeyboardButton(text='📈 Трафик', callback_data='admin:traffic')],
        [InlineKeyboardButton(text='🧪 Качество', callback_data='admin:quality')],
        [InlineKeyboardButton(text='⚙️ Настройки', callback_data='admin:settings')],
        [InlineKeyboardButton(text='🧾 Ожидают оплаты', callback_data='admin:pending')],
        [InlineKeyboardButton(text='⬅️ Назад', callback_data='admin:menu')],
    ])


def admin_promos_kb(promos: list, *, back_cb: str = "admin:menu") -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for promo in promos:
        status = "🟢" if promo.active else "🔴"
        rows.append([
            InlineKeyboardButton(text=f"{status} {promo.code}", callback_data=f"admin:promo:toggle:{promo.id}"),
            InlineKeyboardButton(text="🗑", callback_data=f"admin:promo:delete:{promo.id}"),
        ])
    rows.append([InlineKeyboardButton(text="➕ Создать промокод", callback_data="admin:promo:create")])
    rows.append([InlineKeyboardButton(text='⬅️ Назад', callback_data=back_cb)])
    return InlineKeyboardMarkup(inline_keyboard=rows)



def admin_back_kb(target: str = "admin:menu") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='⬅️ Назад', callback_data=target)],
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
    rows.append([InlineKeyboardButton(text='⬅️ Назад', callback_data='admin:menu')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_user_actions_kb(user_id: int, *, is_enabled: bool) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text='➕ Продлить +7д', callback_data=f'admin:user:extend:{user_id}:7'),
            InlineKeyboardButton(text='➕ Продлить +30д', callback_data=f'admin:user:extend:{user_id}:30'),
        ],
        [InlineKeyboardButton(text='🛠 Сменить тариф', callback_data=f'admin:user:plan:{user_id}')],
    ]
    if is_enabled:
        rows.append([InlineKeyboardButton(text='⏸ Отключить доступ', callback_data=f'admin:user:disable:{user_id}')])
    else:
        rows.append([InlineKeyboardButton(text='▶️ Включить доступ', callback_data=f'admin:user:enable:{user_id}')])
    rows.append([InlineKeyboardButton(text='⬅️ Назад', callback_data='admin:user')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_user_confirm_kb(user_id: int, *, action: str, back_cb: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text='✅ Подтвердить', callback_data=f'admin:user:{action}:confirm:{user_id}'),
            InlineKeyboardButton(text='❌ Отмена', callback_data=back_cb),
        ],
    ])


def admin_plan_groups_kb(user_id: int, plan_codes: list[str], *, back_cb: str) -> InlineKeyboardMarkup:
    rows = []
    for code in plan_codes:
        rows.append([InlineKeyboardButton(text=plan_title(code), callback_data=f'admin:plan_group:{user_id}:{code}')])
    rows.append([InlineKeyboardButton(text='⬅️ Назад', callback_data=back_cb)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_plan_options_kb(user_id: int, options: list[PlanOption], *, back_cb: str) -> InlineKeyboardMarkup:
    rows = []
    for opt in options:
        title = f"{opt.name} — {opt.months} {months_title(opt.months, short=True)}"
        rows.append([InlineKeyboardButton(text=title, callback_data=f'admin:plan_option:{user_id}:{opt.code}:{opt.months}')])
    rows.append([InlineKeyboardButton(text='⬅️ Назад', callback_data=back_cb)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_plan_apply_kb(user_id: int, plan_code: str, months: int, *, back_cb: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text='▶️ Применить сейчас',
                callback_data=f'admin:plan_apply:{user_id}:{plan_code}:{months}:now',
            ),
            InlineKeyboardButton(
                text='⏳ С конца текущего',
                callback_data=f'admin:plan_apply:{user_id}:{plan_code}:{months}:expiry',
            ),
        ],
        [InlineKeyboardButton(text='⬅️ Назад', callback_data=back_cb)],
    ])


def admin_payments_kb(orders: list[Order]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text='Все', callback_data='admin:payments'),
            InlineKeyboardButton(text='Ожидают', callback_data='admin:payments:status:pending'),
            InlineKeyboardButton(text='Оплачены', callback_data='admin:payments:status:paid'),
            InlineKeyboardButton(text='Отменены', callback_data='admin:payments:status:canceled'),
        ],
    ]
    for order in orders:
        title = f"#{order.id} {order.provider} {order.status}"
        rows.append([InlineKeyboardButton(text=title, callback_data=f'admin:order:{order.id}')])
    rows.append([InlineKeyboardButton(text='⬅️ Назад', callback_data='admin:menu')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_order_detail_kb(order_id: int, *, show_check: bool, show_cancel: bool, back_cb: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if show_check:
        rows.append([InlineKeyboardButton(text='🔄 Проверить оплату', callback_data=f'admin:order:check:{order_id}')])
    if show_cancel:
        rows.append([InlineKeyboardButton(text='❌ Отменить заказ', callback_data=f'admin:order:cancel:{order_id}')])
    rows.append([InlineKeyboardButton(text='⬅️ Назад', callback_data=back_cb)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_pending_kb(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text='🔄 Проверить', callback_data=f'admin:pending:check:{order_id}'),
            InlineKeyboardButton(text='❌ Отменить', callback_data=f'admin:pending:cancel:{order_id}'),
        ],
        [InlineKeyboardButton(text='⬅️ Назад', callback_data='admin:pending')],
    ])


def admin_pending_list_kb(orders: list[Order]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for order in orders:
        rows.append([
            InlineKeyboardButton(text=f'🔄 #{order.id}', callback_data=f'admin:pending:check:{order.id}'),
            InlineKeyboardButton(text='❌', callback_data=f'admin:pending:cancel:{order.id}'),
        ])
    rows.append([InlineKeyboardButton(text='⬅️ Назад', callback_data='admin:menu')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_subs_kb(user_ids: list[int]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for user_id in user_ids:
        rows.append([
            InlineKeyboardButton(text=f'✉️ {user_id}', callback_data=f'admin:subs:msg:{user_id}'),
            InlineKeyboardButton(text='+7д', callback_data=f'admin:subs_extend:{user_id}:7'),
            InlineKeyboardButton(text='+30д', callback_data=f'admin:subs_extend:{user_id}:30'),
        ])
    rows.append([InlineKeyboardButton(text='⬅️ Назад', callback_data='admin:menu')])
    return InlineKeyboardMarkup(inline_keyboard=rows)