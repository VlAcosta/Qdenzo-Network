# -*- coding: utf-8 -*-

from __future__ import annotations

from datetime import datetime, timezone

from ..config import settings
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from sqlalchemy import desc, select

from ..db import session_scope
from ..keyboards.nav import nav_kb
from ..keyboards.plans import plan_groups_kb, plan_options_kb
from ..keyboards.subscription import subscription_kb
from ..models import Order
from ..services import get_or_create_subscription
from ..services.catalog import list_plan_options_by_code, plan_options, plan_title
from ..services.devices import count_active_devices
from ..services.users import ensure_user
from ..utils.telegram import edit_message_text, safe_answer_callback, send_html_with_photo
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
        user = await ensure_user(session=session, tg_user=message.from_user)
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
    await send_html_with_photo(
        message,
        text,
        reply_markup=subscription_kb(),
        photo_path=settings.start_photo_path,
    )


@router.callback_query(F.data == 'sub')
async def cb_sub(call: CallbackQuery) -> None:
    await safe_answer_callback(call)
    async with session_scope() as session:
        user = await ensure_user(session=session, tg_user=call.from_user)
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
    await safe_answer_callback(call)
    

@router.callback_query(F.data == 'sub:renew')
async def cb_sub_renew(call: CallbackQuery) -> None:
    await safe_answer_callback(call)
    async with session_scope() as session:
        user = await ensure_user(session=session, tg_user=call.from_user)
        sub = await get_or_create_subscription(session, user.id)

    options = [opt for opt in list_plan_options_by_code(sub.plan_code) if opt.months > 0]
    text = (
        f"🔄 <b>Продлить подписку</b>\n\n"
        f"Сейчас у вас: <b>{h(plan_title(sub.plan_code))}</b>\n"
        f"Действует до: <b>{fmt_dt(sub.expires_at)}</b>\n\n"
        "Продлить на:"
    )
    await edit_message_text(
        call,
        text,
        reply_markup=plan_options_kb(options, back_cb="sub", callback_prefix="plan:renew"),
    )
    await safe_answer_callback(call)


@router.callback_query(F.data == 'sub:change')
async def cb_sub_change(call: CallbackQuery) -> None:
    await safe_answer_callback(call)
    async with session_scope() as session:
        user = await ensure_user(session=session, tg_user=call.from_user)
        sub = await get_or_create_subscription(session, user.id)

    text = (
        f"🛠 <b>Сменить тариф</b>\n\n"
        f"Сейчас у вас: <b>{h(plan_title(sub.plan_code))}</b>\n"
        f"Действует до: <b>{fmt_dt(sub.expires_at)}</b>\n\n"
        "Новый тариф применится сразу после оплаты.\n\n"
        "Сменить тариф: выберите новый 👇"
    )
    await edit_message_text(
        call,
        text,
        reply_markup=plan_groups_kb(
            include_trial=False,
            back_cb="sub",
            callback_prefix="plan_group:change",
            exclude_codes={sub.plan_code},
        ),
    )
    await safe_answer_callback(call)


@router.callback_query(F.data.startswith("plan_group:change:"))
async def cb_sub_change_group(call: CallbackQuery) -> None:
    await safe_answer_callback(call)
    parts = call.data.split(":")
    if len(parts) != 3:
        return
    _, _, code = parts
    async with session_scope() as session:
        user = await ensure_user(session=session, tg_user=call.from_user)
        sub = await get_or_create_subscription(session, user.id)

    if code == sub.plan_code:
        await safe_answer_callback(call, "Этот тариф уже активен", show_alert=True)
        return

    options = [opt for opt in plan_options(include_trial=False) if opt.code == code]
    if not options:
        await safe_answer_callback(call, "Тариф не найден", show_alert=True)
        return

    text = (
        f"🛠 <b>Сменить тариф</b>\n\n"
        f"Сейчас у вас: <b>{h(plan_title(sub.plan_code))}</b>\n"
        f"Новый тариф: <b>{h(plan_title(code))}</b>\n\n"
        "Выберите период подписки:"
    )
    await edit_message_text(
        call,
        text,
        reply_markup=plan_options_kb(options, back_cb="sub:change", callback_prefix="plan:change"),
    )
    await safe_answer_callback(call)

@router.callback_query(F.data == 'sub:history')
async def cb_sub_history(call: CallbackQuery) -> None:
    await safe_answer_callback(call)
    async with session_scope() as session:
        user = await ensure_user(session=session, tg_user=call.from_user)
        q = await session.execute(
            select(Order).where(Order.user_id == user.id).order_by(desc(Order.created_at)).limit(10)
        )
        orders = list(q.scalars().all())

    if not orders:
        text = "История оплат пока пуста."
    else:
        lines = ["🧾 <b>История оплат</b>\n"]
        for order in orders:
            plan = plan_title(order.plan_code or "—")
            amount = order.amount or str(order.amount_rub)
            currency = order.currency or "RUB"
            lines.append(
                f"• {fmt_dt(order.created_at)} — #{order.id} — {h(plan)} — {amount} {h(currency)} — "
                f"{h(order.provider)} — {h(order.status)}"
            )
        text = "\n".join(lines)

    await edit_message_text(call, text, reply_markup=nav_kb(back_cb='sub', home_cb='back'))
    await safe_answer_callback(call)


def _profiles_for_plan(plan_code: str) -> str:
    plan = (plan_code or '').lower()
    if plan == 'start':
        return "Smart, Work, Low Internet"
    if plan == 'pro':
        return "Smart, Work, Low Internet, Streaming, Gaming"
    if plan == 'family':
        return "Все профили + Kids Safe"
    return "—"