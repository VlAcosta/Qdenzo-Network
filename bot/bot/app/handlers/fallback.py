# -*- coding: utf-8 -*-

from __future__ import annotations

from aiogram import Router
from aiogram.types import Message

from ..keyboards.main import main_menu
from ..config import settings
from ..db import session_scope
from ..services.users import get_user_by_tg_id

router = Router()


@router.message()
async def any_text(msg: Message) -> None:
    # If user sent text while we expected button presses
    async with session_scope() as session:
        user = await get_user_by_tg_id(session, msg.from_user.id)
    is_admin = bool(user and user.tg_id in settings.admin_id_list)

    await msg.answer(
        "Я работаю через кнопки меню 👇",
        reply_markup=main_menu(is_admin=is_admin),
    )
