# -*- coding: utf-8 -*-

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from ..db import session_scope
from ..keyboards.common import back_kb
from ..keyboards.profiles import PROFILES, profile_apply_kb, profile_devices_kb, profiles_kb
from ..services.devices import list_devices
from ..services.users import get_user_by_tg_id
from ..services.profiles import get_profile_code, set_profile_code
from ..services.subscriptions import get_or_create_subscription, is_active
from ..utils.telegram import edit_message_text
from ..utils.text import h

router = Router(name='profiles')


def _profile_title(code: str) -> str:
    for c, title, _ in PROFILES:
        if c == code:
            return title
    return code


@router.callback_query(F.data == 'profiles')
@router.callback_query(F.data == 'modes')
@router.message(Command('profiles'))
async def show_profiles(event) -> None:
    if isinstance(event, Message):
        tg_id = event.from_user.id
        answer = event.answer
    else:
        tg_id = event.from_user.id
        answer = edit_message_text

    async with session_scope() as session:
        user = await get_user_by_tg_id(session, tg_id)
        if not user:
            if isinstance(event, CallbackQuery):
                await event.answer('Сначала /start', show_alert=True)
            else:
                await event.answer('Сначала /start')
            return
        sub = await get_or_create_subscription(session, user.id)
        if not is_active(sub):
            text = (
                "🧠 <b>Режимы</b>\n\n"
                "Сначала активируйте подписку, чтобы выбрать профиль."
            )
            await answer(event, text, reply_markup=back_kb('buy'))
            if isinstance(event, CallbackQuery):
                await event.answer()
            return
        code = await get_profile_code(session, user.id)

    profiles_text = "\n".join([f"• <b>{h(title)}</b> — {h(descr)}" for _, title, descr in PROFILES])

    text = (
        "🧠 <b>Режимы</b> — профили использования\n\n"
        f"Текущий: <b>{h(_profile_title(code))}</b>\n\n"
        f"{profiles_text}\n\n"
        "Выберите режим ниже:"
    )
    await answer(event, text, reply_markup=profiles_kb(code))
    if isinstance(event, CallbackQuery):
        await event.answer()


@router.callback_query(F.data.startswith('profile:'))
async def cb_choose_profile(call: CallbackQuery) -> None:
    code = call.data.split(':', 1)[1]
    text = (
        "Куда применить режим?\n\n"
        "<b>К аккаунту</b> — по умолчанию для всех устройств.\n"
        "<b>К устройству</b> — точечно для выбранного устройства."
    )
    await edit_message_text(call, text, reply_markup=profile_apply_kb(code))
    await call.answer()


@router.callback_query(F.data.startswith('profile_apply:account:'))
async def cb_apply_profile_account(call: CallbackQuery) -> None:
    code = call.data.split(':', 2)[2]
    async with session_scope() as session:
        user = await get_user_by_tg_id(session, call.from_user.id)
        if not user:
            await call.answer('Сначала /start', show_alert=True)
            return
        await set_profile_code(session, user.id, code)

    await call.answer('Режим применён к аккаунту ✅')
    await show_profiles(call)


@router.callback_query(F.data.startswith('profile_apply:device:'))
async def cb_apply_profile_device(call: CallbackQuery) -> None:
    code = call.data.split(':', 2)[2]
    async with session_scope() as session:
        user = await get_user_by_tg_id(session, call.from_user.id)
        if not user:
            await call.answer('Сначала /start', show_alert=True)
            return
        devices = await list_devices(session, user.id)
        device_rows = [(d.id, f"#{d.slot} {h(d.label) or 'Устройство'}") for d in devices]

    if not device_rows:
        await call.answer('Нет устройств', show_alert=True)
        await show_profiles(call)
        return

    await edit_message_text(call, "Выберите устройство:", reply_markup=profile_devices_kb(code, device_rows))
    await call.answer()


@router.callback_query(F.data.startswith('profile_device:'))
async def cb_apply_profile_to_device(call: CallbackQuery) -> None:
    _, code, device_id_s = call.data.split(':', 2)
    device_id = int(device_id_s)
    async with session_scope() as session:
        user = await get_user_by_tg_id(session, call.from_user.id)
        if not user:
            await call.answer('Сначала /start', show_alert=True)
            return
        device = next((d for d in await list_devices(session, user.id) if d.id == device_id), None)
        if not device:
            await call.answer('Устройство не найдено', show_alert=True)
            return
        device.profile_code = code
        session.add(device)
        await session.commit()

    await call.answer('Режим применён к устройству ✅')
    await show_profiles(call)
