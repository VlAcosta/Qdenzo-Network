# -*- coding: utf-8 -*-

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from ..config import settings
from ..utils.telegram import edit_message_text, safe_answer
from ..db import session_scope
from ..keyboards.nav import nav_kb
from ..keyboards.support import support_kb
from ..services.devices import count_active_devices
from ..services.subscriptions import get_or_create_subscription, is_active
from ..services.users import get_user_by_tg_id

router = Router()


def _kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='✉️ Написать в поддержку', url=f'https://t.me/{settings.support_username.lstrip("@")}')],
        nav_kb(back_cb="support", home_cb="back").inline_keyboard[0],
    ])


_TEXT = (
    "Если что-то не подключается — напишите нам, мы поможем.\n\n"
    f"Контакт: <b>{settings.support_username}</b>\n\n"
    "Чтобы мы быстро разобрались, пришлите:\n"
    "1) Модель устройства (iPhone/Android/TV/PC)\n"
    "2) Какой клиент используете\n"
    "3) Скрин ошибки (если есть)\n"
)


@router.callback_query(F.data == 'support')
async def cb_support(call: CallbackQuery) -> None:
    await edit_message_text(call, _TEXT, reply_markup=support_kb())
    await safe_answer(call)


@router.message(Command('support'))
async def cmd_support(msg: Message) -> None:
    await msg.answer(_TEXT, reply_markup=support_kb())


@router.callback_query(F.data == 'support:chat')
async def cb_support_chat(call: CallbackQuery) -> None:
    url = f'https://t.me/{settings.support_username.lstrip("@")}'
    await edit_message_text(
        call,
        f"Напишите оператору: {settings.support_username}\n\n{url}",
        reply_markup=_kb(),
    )
    await safe_answer(call)


@router.callback_query(F.data == 'support:diag')
async def cb_support_diag(call: CallbackQuery) -> None:
    async with session_scope() as session:
        user = await get_user_by_tg_id(session, call.from_user.id)
        if not user:
            await call.answer('Сначала /start', show_alert=True)
            return
        sub = await get_or_create_subscription(session, user.id)
        devices_active = await count_active_devices(session, user.id)

    sub_status = '✅ активна' if is_active(sub) else '⛔️ не активна'
    text = (
        "<b>🩺 Диагностика</b>\n\n"
        f"Подписка: {sub_status}\n"
        f"Лимит устройств: <b>{sub.devices_limit}</b>\n"
        f"Активных устройств: <b>{devices_active}</b>\n\n"
        "Если подписка не активна — перейдите в <b>Купить</b>.\n"
        "Если конфиг не работает — проверьте статус устройства и повторно импортируйте ссылку."
    )
    await edit_message_text(call, text, reply_markup=support_kb())
    await safe_answer(call)
