# -*- coding: utf-8 -*-

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

router = Router()


_FAQ_TEXT = """<b>FAQ / Инструкции</b>

<b>Как подключиться?</b>
1) Нажмите <b>Устройства</b> → <b>Добавить устройство</b>
2) Выберите тип (Телефон/ПК/ТВ)
3) Откройте <b>Получить конфиг</b> и импортируйте ссылку в приложение

<b>Рекомендуемые приложения:</b>
• iOS: Hiddify, V2Box (или Shadowrocket)
• Android: Hiddify, v2rayNG, Nekobox
• Windows/macOS: Hiddify, Nekoray

<b>Если не подключается:</b>
• Проверьте, что подписка активна
• Пересоздайте ссылку (Устройства → Конфиг)
• Переключите профиль (Smart/Work)
• Напишите в поддержку (кнопка <b>Поддержка</b>)
"""


def _kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='⬅️ Назад', callback_data='back')],
    ])


@router.callback_query(F.data == 'faq')
async def cb_faq(call: CallbackQuery) -> None:
    await call.message.edit_text(_FAQ_TEXT, reply_markup=_kb())
    await call.answer()


@router.message(Command('faq'))
async def cmd_faq(msg: Message) -> None:
    await msg.answer(_FAQ_TEXT, reply_markup=_kb())
