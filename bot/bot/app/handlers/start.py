# -*- coding: utf-8 -*-

from aiogram.filters import Command, CommandStart
from aiogram.types import FSInputFile, Message
from aiogram import Router

from ..config import settings
from ..db import session_scope
from ..keyboards.main import main_menu
from ..services.subscriptions import is_active
from ..services import get_or_create_subscription
from ..services.users import ensure_user
from ..utils.text import h

router = Router()


def _parse_ref(message: Message) -> str | None:
    if not message.text:
        return None
    if " " not in message.text:
        return None
    _, arg = message.text.split(" ", 1)
    if arg.startswith("ref_"):
        return arg.replace("ref_", "", 1)
    return None


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    ref = _parse_ref(message)

    async with session_scope() as session:
        user = await ensure_user(session=session, tg_user=message.from_user, ref_code=ref)
        if user.is_banned:
            await message.answer(
                "⛔️ Доступ к боту ограничен.\n"
                "Если это ошибка — напишите в поддержку: " + h(settings.support_username)
            )
            return

        sub = await get_or_create_subscription(session, user.id)
        has_sub = is_active(sub)

    caption = (
        f"🏠 <b>Главное меню</b> (ID: <code>{user.tg_id}</code>, Баланс: <b>—</b>)\n\n"
        "Выберите действие ниже 👇\n\n"
        f"<i>Поддержка:</i> {h(settings.support_username)}"
    )

    photo_path = settings.start_photo_path
    if photo_path:
        try:
            photo = FSInputFile(str(photo_path))
            await message.answer_photo(
                photo=photo,
                caption=caption,
                reply_markup=main_menu(user.is_admin, has_subscription=has_sub),
            )
            return
        except Exception:
            pass

    await message.answer(
        caption,
        reply_markup=main_menu(user.is_admin, has_subscription=has_sub),
    )


@router.message(Command("menu"))
async def cmd_menu(message: Message) -> None:
    async with session_scope() as session:
        user = await ensure_user(session=session, tg_user=message.from_user)
        sub = await get_or_create_subscription(session, user.id)

    await message.answer(
        f"🏠 <b>Главное меню</b> (ID: <code>{user.tg_id}</code>, Баланс: <b>—</b>)\n\n"
        "Выберите действие 👇",
        reply_markup=main_menu(user.is_admin, has_subscription=is_active(sub)),
    )
