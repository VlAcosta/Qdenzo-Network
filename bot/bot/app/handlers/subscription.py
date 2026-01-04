# -*- coding: utf-8 -*-

from __future__ import annotations

from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from ..db import session_scope
from ..keyboards.nav import nav_kb
from ..keyboards.subscription import subscription_kb
from ..services import get_or_create_subscription
from ..services.devices import count_active_devices
from ..services.users import get_or_create_user
from ..utils.telegram import edit_message_text
from ..utils.text import fmt_dt, h

router = Router()


def _remaining(expires_at: datetime | None) -> str:
    if not expires_at:
        return '—'
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    delta = expires_at - datetime.now(timezone.utc)
    if delta.total_seconds() <= 0:
        return 'истекла'
    days = int(delta.total_seconds() // 86400)
    hours = int((delta.total_seconds() % 86400) // 3600)
    if days > 0:
        return f"{days} дн {hours} ч"
    return f"{hours} ч"


@router.message(Command('sub'))
async def cmd_sub(message: Message) -> None:
    async with session_scope() as session:
        user = await get_or_create_user(
            session=session,
            tg_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            ref_code=None,
            locale=message.from_user.language_code,
        )
        sub = await get_or_create_subscription(session, user.id)
        used = await count_active_devices(session, user.id)

    text = (
        "📦 <b>Ваша подписка</b>\n\n"
        f"Тариф: <b>{h(sub.plan_code.upper())}</b>\n"
        f"Действует до: <b>{fmt_dt(sub.expires_at)}</b>\n"
        f"Осталось: <b>{_remaining(sub.expires_at)}</b>\n\n"
        f"Устройства: <b>{used}/{sub.devices_limit}</b>\n"
        "\n<b>Доступные профили:</b>\n"
        + _profiles_for_plan(sub.plan_code)
        + "\n\n<b>Лимиты по тарифам:</b>\n"
        "Start — 3 устройства (1 телефон, 1 ПК, 1 ТВ)\n"
        "Pro — 5 устройств (макс: 1 ПК, 2 ТВ, 3 телефон/планшет)\n"
        "Family — 10 устройств (макс: 5 телефон/планшет, 2 ПК, 3 ТВ)\n"
    )
    await message.answer(text, reply_markup=subscription_kb())


@router.callback_query(F.data == 'sub')
async def cb_sub(call: CallbackQuery) -> None:
    async with session_scope() as session:
        user = await get_or_create_user(
            session=session,
            tg_id=call.from_user.id,
            username=call.from_user.username,
            first_name=call.from_user.first_name,
            ref_code=None,
            locale=call.from_user.language_code,
        )
        sub = await get_or_create_subscription(session, user.id)
        used = await count_active_devices(session, user.id)

    text = (
        "📦 <b>Ваша подписка</b>\n\n"
        f"Тариф: <b>{h(sub.plan_code.upper())}</b>\n"
        f"Действует до: <b>{fmt_dt(sub.expires_at)}</b>\n"
        f"Осталось: <b>{_remaining(sub.expires_at)}</b>\n\n"
        f"Устройства: <b>{used}/{sub.devices_limit}</b>\n"
        "\n<b>Доступные профили:</b>\n"
        + _profiles_for_plan(sub.plan_code)
        + "\n\n<b>Лимиты по тарифам:</b>\n"
        "Start — 3 устройства (1 телефон, 1 ПК, 1 ТВ)\n"
        "Pro — 5 устройств (макс: 1 ПК, 2 ТВ, 3 телефон/планшет)\n"
        "Family — 10 устройств (макс: 5 телефон/планшет, 2 ПК, 3 ТВ)\n"
    )
    await edit_message_text(call, text, reply_markup=subscription_kb())
    await call.answer()
    
@router.callback_query(F.data == 'sub:history')
async def cb_sub_history(call: CallbackQuery) -> None:
    await edit_message_text(call, "История оплат появится здесь позже.", reply_markup=nav_kb(back_cb='sub', home_cb='back'))
    await call.answer()


def _profiles_for_plan(plan_code: str) -> str:
    plan = (plan_code or '').lower()
    if plan == 'start':
        return "Smart, Work, Low Internet"
    if plan == 'pro':
        return "Smart, Work, Low Internet, Streaming, Gaming"
    if plan == 'family':
        return "Все профили + Kids Safe"
    return "—"