# -*- coding: utf-8 -*-

from __future__ import annotations

import urllib.parse

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from ..config import settings
from ..db import session_scope
from ..services.users import get_user_by_tg_id
from ..services.referrals import CAP_SECONDS, get_referral_stats
from ..utils.text import fmt_dt, h

router = Router()


def _fmt_seconds(seconds: int) -> str:
    # human readable
    if seconds <= 0:
        return '0'
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    parts = []
    if days:
        parts.append(f"{days}д")
    if hours:
        parts.append(f"{hours}ч")
    if not parts:
        minutes = seconds // 60
        parts.append(f"{minutes}мин")
    return ' '.join(parts)


async def _render(call_or_msg, bot: Bot) -> None:
    tg_id = call_or_msg.from_user.id
    async with session_scope() as session:
        user = await get_user_by_tg_id(session, tg_id)
        if not user:
            text = 'Сначала нажмите /start'
            if hasattr(call_or_msg, 'answer'):
                await call_or_msg.answer(text, show_alert=True)
            else:
                await call_or_msg.answer(text)
            return

        me = await bot.get_me()
        bot_username = me.username or ''
        deep_link = f"https://t.me/{bot_username}?start=ref_{user.referral_code}" if bot_username else f"/start ref_{user.referral_code}"

        stats = await get_referral_stats(session, user.id)

    share_url = 'https://t.me/share/url?' + urllib.parse.urlencode({
        'url': deep_link,
        'text': f"Попробуй {settings.brand_name} — быстрый VPN. Вот ссылка: {deep_link}",
    })

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🔗 Поделиться', url=share_url)],
        [InlineKeyboardButton(text='⬅️ Назад', callback_data='back')],
    ])

    text = (
        "<b>🎁 Реферальная программа</b>\n\n"
        f"Ваша ссылка:\n<code>{h(deep_link)}</code>\n\n"
        f"Приглашено: <b>{stats['invited_count']}</b>\n"
        f"Бонус в текущем окне: <b>{_fmt_seconds(stats['window_applied_seconds'])}</b>\n"
        f"Лимит окна: <b>{_fmt_seconds(stats['cap_seconds'])}</b>\n"
        f"Осталось в окне: <b>{_fmt_seconds(stats['remaining_seconds'])}</b>\n"
        f"Окно до: <b>{fmt_dt(stats['window_end_at'])}</b>\n\n"
        "Бонус начисляется за <b>каждую оплату</b> реферала.\n"
        "Максимум — <b>15 дней</b> бонусов в каждом 30‑дневном окне."
    )

    if isinstance(call_or_msg, CallbackQuery):
        await call_or_msg.message.edit_text(text, reply_markup=kb)
        await call_or_msg.answer()
    else:
        await call_or_msg.answer(text, reply_markup=kb)


@router.callback_query(F.data == 'ref')
async def cb_ref(call: CallbackQuery, bot: Bot) -> None:
    await _render(call, bot)


@router.message(Command('ref'))
async def cmd_ref(msg: Message, bot: Bot) -> None:
    await _render(msg, bot)
