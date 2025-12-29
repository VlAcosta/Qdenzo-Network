# -*- coding: utf-8 -*-

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import FSInputFile, CallbackQuery, Message

from ..config import settings
from ..db import session_scope
from ..keyboards.main import main_menu
from ..services import get_or_create_subscription
from ..services.users import get_or_create_user
from ..utils.text import h

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    ref = None
    if message.text and ' ' in message.text:
        _, arg = message.text.split(' ', 1)
        if arg.startswith('ref_'):
            ref = arg.replace('ref_', '', 1)

    async with session_scope() as session:
        user = await get_or_create_user(
            session=session,
            tg_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            ref_code=ref,
        )
        sub = await get_or_create_subscription(session, user.id)
        if user.is_banned:
            await message.answer(
                '⛔️ Доступ к боту ограничен.\nЕсли это ошибка — напишите в поддержку: ' + h(settings.support_username)
            )
            return

        caption = (
            f"👋 Добро пожаловать в <b>{h(settings.brand_name)}</b>\n\n"
            f"Выберите действие ниже 👇\n"
            f"<i>Поддержка:</i> {h(settings.support_username)}"
        )

    # Send photo if configured (path can be relative to /app/bot via settings.start_photo_path)
    photo_path = settings.start_photo_path
    if photo_path:
        try:
            photo = FSInputFile(str(photo_path))
            await message.answer_photo(photo=photo, caption=caption, reply_markup=main_menu(user.is_admin))
            return
        except Exception:
            # fall back to text
            pass

    await message.answer(caption, reply_markup=main_menu(user.is_admin))


@router.message(Command('menu'))
async def cmd_menu(message: Message) -> None:
    async with session_scope() as session:
        user = await get_or_create_user(
            session=session,
            tg_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            ref_code=None,
        )
        if user.is_banned:
            await message.answer('⛔️ Доступ к боту ограничен.')
            return
    text = f"🏠 <b>Меню {h(settings.brand_name)}</b>"
    await message.answer(text, reply_markup=main_menu(user.is_admin))


@router.callback_query(F.data == 'back')
async def cb_back(call: CallbackQuery) -> None:
    async with session_scope() as session:
        user = await get_or_create_user(
            session=session,
            tg_id=call.from_user.id,
            username=call.from_user.username,
            first_name=call.from_user.first_name,
            ref_code=None,
        )
    await call.message.edit_text(f"🏠 <b>Меню {h(settings.brand_name)}</b>", reply_markup=main_menu(user.is_admin))
    await call.answer()
