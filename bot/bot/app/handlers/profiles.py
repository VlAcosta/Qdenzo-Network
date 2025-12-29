# -*- coding: utf-8 -*-

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from ..db import session_scope
from ..keyboards.common import back_kb
from ..keyboards.profiles import PROFILES, profiles_kb
from ..services.users import get_user_by_tg_id
from ..services.profiles import get_profile_code, set_profile_code
from ..utils.text import h

router = Router(name='profiles')


def _profile_title(code: str) -> str:
    for c, title, _ in PROFILES:
        if c == code:
            return title
    return code


@router.callback_query(F.data == 'profiles')
@router.message(Command('profiles'))
async def show_profiles(event) -> None:
    if isinstance(event, Message):
        chat_msg = event
        tg_id = event.from_user.id
        answer = event.answer
    else:
        chat_msg = event.message
        tg_id = event.from_user.id
        answer = event.message.edit_text

    async with session_scope() as session:
        user = await get_user_by_tg_id(session, tg_id)
        if not user:
            if isinstance(event, CallbackQuery):
                await event.answer('Сначала /start', show_alert=True)
            else:
                await event.answer('Сначала /start')
            return
        code = await get_profile_code(session, user.id)

    text = (
        f"🧠 <b>Режимы</b>\n\n"
        f"Текущий: <b>{h(_profile_title(code))}</b>\n\n"
        f"Выберите режим ниже:"
    )
    await answer(text, reply_markup=profiles_kb(code))
    if isinstance(event, CallbackQuery):
        await event.answer()


@router.callback_query(F.data.startswith('profile:'))
async def cb_set_profile(call: CallbackQuery) -> None:
    code = call.data.split(':', 1)[1]
    async with session_scope() as session:
        user = await get_user_by_tg_id(session, call.from_user.id)
        if not user:
            await call.answer('Сначала /start', show_alert=True)
            return
        await set_profile_code(session, user.id, code)

    await call.answer('Режим обновлён ✅')
    # re-render
    await show_profiles(call)
