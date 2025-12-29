# -*- coding: utf-8 -*-

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from ..config import settings

router = Router()


def _kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='✉️ Написать в поддержку', url=f'https://t.me/{settings.support_username.lstrip("@")}')],
        [InlineKeyboardButton(text='⬅️ Назад', callback_data='back')],
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
    await call.message.edit_text(_TEXT, reply_markup=_kb())
    await call.answer()


@router.message(Command('support'))
async def cmd_support(msg: Message) -> None:
    await msg.answer(_TEXT, reply_markup=_kb())
