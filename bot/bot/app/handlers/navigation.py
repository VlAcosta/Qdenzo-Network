from aiogram import F, Router
from aiogram.types import CallbackQuery

from ..config import settings
from ..db import session_scope
from ..keyboards.main import main_menu
from ..services import get_or_create_subscription
from ..services.subscriptions import is_active
from ..services.users import ensure_user
from ..utils.telegram import edit_message_text
from ..utils.text import h

router = Router()


@router.callback_query(F.data == "back")
async def cb_back(call: CallbackQuery) -> None:
    async with session_scope() as session:
        user = await ensure_user(session=session, tg_user=call.from_user)

        if user.is_banned:
            await edit_message_text(
                call,
                "⛔️ Доступ к боту ограничен.\n"
                "Если это ошибка — напишите в поддержку: " + h(settings.support_username),
            )
            await call.answer()
            return

        sub = await get_or_create_subscription(session, user.id)

    await edit_message_text(
        call,
        f"🏠 <b>Главное меню</b> (ID: <code>{user.tg_id}</code>, Баланс: <b>—</b>)\n\n"
        "Выберите действие 👇",
        reply_markup=main_menu(user.is_admin, has_subscription=is_active(sub)),
    )
    await call.answer()


@router.callback_query(F.data.in_({"home", "main", "menu"}))
async def cb_home_alias(call: CallbackQuery) -> None:
    await cb_back(call)