# -*- coding: utf-8 -*-

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from ..config import settings
from ..db import session_scope
from ..keyboards.nav import nav_kb
from ..keyboards.traffic import traffic_kb
from ..marzban.client import MarzbanClient
from ..services.devices import DEVICE_TYPES, list_devices
from ..services.subscriptions import get_or_create_subscription
from ..services.users import get_user_by_tg_id
from ..utils.telegram import edit_message_text

router = Router()


def _gb(n_bytes: int | None) -> float:
    if not n_bytes:
        return 0.0
    return n_bytes / (1024 ** 3)


def _plan_limit_gb(plan_code: str) -> int:
    return {
        'trial': settings.traffic_limit_trial_gb,
        'start': settings.traffic_limit_start_gb,
        'pro': settings.traffic_limit_pro_gb,
        'family': settings.traffic_limit_family_gb,
    }.get(plan_code, 0)

def _type_title(device_type: str) -> str:
    return DEVICE_TYPES.get(device_type, device_type)

async def _render(call_or_msg, *, user_id: int, tg_id: int, edit: bool) -> None:
    async with session_scope() as session:
        sub = await get_or_create_subscription(session, user_id)
        devices = await list_devices(session, user_id)

    marz = MarzbanClient(
        base_url=str(settings.marzban_base_url),
        username=settings.marzban_username,
        password=settings.marzban_password,
        verify_ssl=settings.marzban_verify_ssl,
        api_prefix=settings.marzban_api_prefix,
    )

    total_used = 0
    lines = []
    for d in devices:
        used = 0
        try:
            if d.marzban_username:
                u = await marz.get_user(d.marzban_username)
                used = int(u.get('used_traffic') or 0)
        except Exception:
            used = 0
        total_used += used
        lines.append(f"• {_type_title(d.device_type)} <b>{d.label}</b>: { _gb(used):.2f } GB")

    limit_gb = _plan_limit_gb(sub.plan_code)
    limit_bytes = limit_gb * (1024 ** 3)
    pct = (total_used / limit_bytes * 100.0) if limit_bytes else 0.0

    text = (
        "<b>📊 Трафик</b>\n\n"
        f"План: <b>{sub.plan_code}</b>\n"
        f"Использовано: <b>{_gb(total_used):.2f} GB</b> / <b>{limit_gb} GB</b>\n"
        f"Заполнено: <b>{pct:.0f}%</b>\n\n"
        "<b>По устройствам:</b>\n"
        + ("\n".join(lines) if lines else "—")
        + "\n\n"
        "<b>Soft cap</b>: при 100% интернет не отключается — включается Traffic Saver Mode.\n"
        "Traffic Saver Mode: ограничивает Streaming/Gaming; оставляет Smart/Work/Low Internet."
    )

    if edit:
        await edit_message_text(call_or_msg, text, reply_markup=nav_kb(back_cb='buy', home_cb='back'))
        await call_or_msg.answer()
    else:
        await call_or_msg.answer(text, reply_markup=traffic_kb())


@router.callback_query(F.data == 'traffic:buy')
async def cb_traffic_buy(call: CallbackQuery) -> None:
    text = (
        "<b>➕ Докупить трафик</b>\n\n"
        "• +0.5 ТБ — 149 ₽ (до конца текущего периода)\n"
        "• +1 ТБ — 249 ₽ (до конца текущего периода)\n"
        "• +2 ТБ — 449 ₽ (до конца текущего периода)\n\n"
        "Для покупки напишите в поддержку и приложите оплату."
    )
    await edit_message_text(call, text, reply_markup=nav_kb(back_cb='traffic', home_cb='back'))
    await call.answer()


@router.callback_query(F.data == 'traffic')
async def cb_traffic(call: CallbackQuery) -> None:
    async with session_scope() as session:
        user = await get_user_by_tg_id(session, call.from_user.id)
        if not user:
            await call.answer('Сначала /start', show_alert=True)
            return
        await _render(call, user_id=user.id, tg_id=user.tg_id, edit=True)


@router.message(Command('traffic'))
async def cmd_traffic(msg: Message) -> None:
    async with session_scope() as session:
        user = await get_user_by_tg_id(session, msg.from_user.id)
        if not user:
            await msg.answer('Сначала /start')
            return
        await _render(msg, user_id=user.id, tg_id=user.tg_id, edit=False)
