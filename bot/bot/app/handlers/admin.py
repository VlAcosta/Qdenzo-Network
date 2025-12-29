# -*- coding: utf-8 -*-


from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from ..config import settings
from ..db import session_scope
from ..keyboards.admin import admin_kb, admin_orders_kb
from ..marzban.client import MarzbanClient
from ..services.orders import get_order, list_pending_orders, mark_order_paid
from ..utils.telegram import edit_message_text

router = Router()


def _ensure_admin(tg_id: int) -> bool:
    return tg_id in settings.admin_id_list


async def _admin_placeholder(call: CallbackQuery, title: str) -> None:
    text = (
        f"<b>{title}</b>\n\n"
        "Раздел в разработке. Здесь будут сводки и операции по правилам из ТЗ."
    )
    await edit_message_text(call, text, reply_markup=admin_kb())
    await call.answer()


@router.callback_query(F.data == 'admin')
async def cb_admin(call: CallbackQuery) -> None:
    if not _ensure_admin(call.from_user.id):
        await call.answer('Нет доступа', show_alert=True)
        return
    await edit_message_text(call, '<b>🛠 Admin</b>\n\nВыберите действие:', reply_markup=admin_kb())
    await call.answer()

# -*- coding: utf-8 -*-

from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from ..config import settings
from ..db import session_scope
from ..keyboards.admin import admin_kb, admin_orders_kb
from ..marzban.client import MarzbanClient
from ..services.orders import get_order, list_pending_orders, mark_order_paid
from ..utils.telegram import edit_message_text

router = Router()


def _ensure_admin(tg_id: int) -> bool:
    return tg_id in settings.admin_id_list


async def _admin_placeholder(call: CallbackQuery, title: str) -> None:
    text = (
        f"<b>{title}</b>\n\n"
        "Раздел в разработке. Здесь будут сводки и операции по правилам из ТЗ."
    )
    await edit_message_text(call, text, reply_markup=admin_kb())
    await call.answer()


@router.callback_query(F.data == 'admin')
async def cb_admin(call: CallbackQuery) -> None:
    if not _ensure_admin(call.from_user.id):
        await call.answer('Нет доступа', show_alert=True)
        return
    await edit_message_text(call, '<b>🛠 Admin</b>\n\nВыберите действие:', reply_markup=admin_kb())
    await call.answer()


@router.callback_query(F.data == 'admin:dashboard')
async def cb_admin_dashboard(call: CallbackQuery) -> None:
    if not _ensure_admin(call.from_user.id):
        await call.answer('Нет доступа', show_alert=True)
        return
    await _admin_placeholder(call, '📊 Дашборд')


@router.callback_query(F.data == 'admin:user')
async def cb_admin_user(call: CallbackQuery) -> None:
    if not _ensure_admin(call.from_user.id):
        await call.answer('Нет доступа', show_alert=True)
        return
    await _admin_placeholder(call, '🔎 Пользователь')


@router.callback_query(F.data == 'admin:payments')
async def cb_admin_payments(call: CallbackQuery) -> None:
    if not _ensure_admin(call.from_user.id):
        await call.answer('Нет доступа', show_alert=True)
        return
    await _admin_placeholder(call, '💳 Платежи')


@router.callback_query(F.data == 'admin:subs')
async def cb_admin_subs(call: CallbackQuery) -> None:
    if not _ensure_admin(call.from_user.id):
        await call.answer('Нет доступа', show_alert=True)
        return
    await _admin_placeholder(call, '📦 Подписки')


@router.callback_query(F.data == 'admin:traffic')
async def cb_admin_traffic(call: CallbackQuery) -> None:
    if not _ensure_admin(call.from_user.id):
        await call.answer('Нет доступа', show_alert=True)
        return
    await _admin_placeholder(call, '📈 Трафик')


@router.callback_query(F.data == 'admin:quality')
async def cb_admin_quality(call: CallbackQuery) -> None:
    if not _ensure_admin(call.from_user.id):
        await call.answer('Нет доступа', show_alert=True)
        return
    await _admin_placeholder(call, '🧪 Качество')


@router.callback_query(F.data == 'admin:settings')
async def cb_admin_settings(call: CallbackQuery) -> None:
    if not _ensure_admin(call.from_user.id):
        await call.answer('Нет доступа', show_alert=True)
        return
    await _admin_placeholder(call, '⚙️ Настройки')


@router.message(Command('admin'))
async def cmd_admin(msg: Message) -> None:
    if not _ensure_admin(msg.from_user.id):
        return
    await msg.answer('<b>🛠 Admin</b>\n\nВыберите действие:', reply_markup=admin_kb())


@router.callback_query(F.data == 'admin:pending')
async def cb_admin_pending(call: CallbackQuery) -> None:
    if not _ensure_admin(call.from_user.id):
        await call.answer('Нет доступа', show_alert=True)
        return
    async with session_scope() as session:
        orders = await list_pending_orders(session)

    if not orders:
        await edit_message_text(call, '✅ Нет заявок, ожидающих подтверждения.', reply_markup=admin_kb())
        await call.answer()
        return

    text = '<b>🧾 Ожидают оплаты</b>\n\n'
    for o in orders:
        text += f"• #{o.id} — {o.plan_code} {o.months}м — {o.amount_rub}₽ — user_id={o.user_id}\n"

    await edit_message_text(call, text, reply_markup=admin_orders_kb(orders))
    await call.answer()


@router.callback_query(F.data.startswith('admin:approve:'))
async def cb_admin_approve(call: CallbackQuery, bot: Bot) -> None:
    if not _ensure_admin(call.from_user.id):
        await call.answer('Нет доступа', show_alert=True)
        return

    order_id = int(call.data.split(':')[-1])
    marz = MarzbanClient(
        base_url=str(settings.marzban_base_url),
        username=settings.marzban_username,
        password=settings.marzban_password,
        verify_ssl=settings.marzban_verify_ssl,
    )

    async with session_scope() as session:
        order = await get_order(session, order_id)
        if not order:
            await call.answer('Заказ не найден', show_alert=True)
            return
        if order.status != 'pending':
            await call.answer(f'Нельзя подтвердить: статус {order.status}', show_alert=True)
            return

        await mark_order_paid(session, marz, order_id)
        # Get user tg_id to notify
        user = await session.get(type(order.user), order.user_id) if False else None

        # Safer: re-query
        from ..models import User
        u = await session.get(User, order.user_id)
        if u:
            await bot.send_message(u.tg_id, f"✅ Оплата подтверждена. Подписка активирована: <b>{order.plan_code}</b> {order.months} мес.")

    await call.answer('✅ Подтверждено')
    # Refresh list
    await cb_admin_pending(call)


@router.callback_query(F.data.startswith('admin:cancel:'))
async def cb_admin_cancel(call: CallbackQuery, bot: Bot) -> None:
    if not _ensure_admin(call.from_user.id):
        await call.answer('Нет доступа', show_alert=True)
        return

    order_id = int(call.data.split(':')[-1])
    async with session_scope() as session:
        order = await get_order(session, order_id)
        if not order:
            await call.answer('Заказ не найден', show_alert=True)
            return
        if order.status != 'pending':
            await call.answer(f'Нельзя отменить: статус {order.status}', show_alert=True)
            return
        order.status = 'canceled'
        session.add(order)
        await session.commit()
        from ..models import User
        u = await session.get(User, order.user_id)
        if u:
            await bot.send_message(u.tg_id, f"❌ Заказ #{order.id} отклонён. Если вы оплатили — напишите в поддержку.")

    await call.answer('❌ Отклонено')
    await cb_admin_pending(call)
