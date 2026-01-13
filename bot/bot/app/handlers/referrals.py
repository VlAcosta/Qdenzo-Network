# -*- coding: utf-8 -*-

import urllib.parse

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from ..config import settings
from ..db import session_scope
from ..services.users import get_user_by_tg_id
from ..services.referrals import get_referral_stats
from ..utils.telegram import edit_message_text, safe_answer_callback
from ..utils.text import fmt_dt, h

router = Router()


def _fmt_seconds(seconds: int) -> str:
    if not seconds or seconds <= 0:
        return "0"
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60
    parts = []
    if days:
        parts.append(f"{days}д")
    if hours:
        parts.append(f"{hours}ч")
    if not days and not hours and minutes:
        parts.append(f"{minutes}м")
    return " ".join(parts) if parts else "0"


def _share_url(deep_link: str) -> str:
    # Красивый “как у конкурентов” текст
    share_text = (
        "🎁 3 дня VPN бесплатно — SMART-сервера!\n"
        "✅ YouTube без рекламы • ⚡️ высокая скорость • 🛡 приватность\n\n"
        f"Ссылка: {deep_link}"
    )
    return "https://t.me/share/url?" + urllib.parse.urlencode({"url": deep_link, "text": share_text})


async def _render(call_or_msg, bot: Bot) -> None:
    tg_id = call_or_msg.from_user.id

    async with session_scope() as session:
        user = await get_user_by_tg_id(session, tg_id)
        if not user:
            if isinstance(call_or_msg, CallbackQuery):
                await safe_answer_callback(call_or_msg, "Сначала нажмите /start", show_alert=True)
            else:
                await call_or_msg.answer("Сначала нажмите /start")
            return

        me = await bot.get_me()
        bot_username = me.username or settings.bot_username or ""
        if bot_username:
            deep_link = f"https://t.me/{bot_username}?start=ref_{user.referral_code}"
        else:
            deep_link = f"/start ref_{user.referral_code}"

        stats = await get_referral_stats(session, user.id)

    invited = int(stats.get("invited_count", 0))
    applied = int(stats.get("window_applied_seconds", stats.get("applied_seconds", 0)) or 0)
    remaining = int(stats.get("remaining_seconds", 0) or 0)
    cap = int(stats.get("cap_seconds", 0) or 0)
    window_end = stats.get("window_end_at")

    window_str = "—"
    if window_end:
        window_str = fmt_dt(window_end)

    text = (
        "🎁 <b>Реферальная программа</b>\n\n"
        "Ваша ссылка:\n"
        f"<code>{h(deep_link)}</code>\n\n"
        f"👥 Приглашено: <b>{invited}</b>\n"
        f"⏳ Бонус в окне: <b>{_fmt_seconds(applied)}</b>\n"
        + (f"🎯 Лимит окна: <b>{_fmt_seconds(cap)}</b>\n" if cap else "")
        + f"⌛ Осталось в окне: <b>{_fmt_seconds(remaining)}</b>\n"
        f"🗓 Окно до: <b>{h(window_str)}</b>\n\n"
        "📌 Бонус начисляется после оплаты реферала.\n"
        "Максимум — <b>15 дней</b> бонуса в каждом <b>30-дневном</b> окне.\n\n"
        "<b>Начисления (пример):</b>\n"
        "• Start 1 мес: тебе +1 день / Pro +12ч / Family +3ч\n"
        "• Start 3 мес: тебе +36ч / Pro +12ч / Family +6ч\n"
        "• Start 6/12 мес: тебе +3 дня / Pro +2 дня / Family +1 день\n\n"
        "• Pro 1/3 мес: тебе +2 дня / Pro +1 день / Family +12ч\n"
        "• Pro 6/12 мес: тебе +3 дня / Pro +2 дня / Family +1 день\n\n"
        "• Family 3/6 мес: тебе +5 дней / Pro +3 дня / Family +2 дня\n"
        "• Family 12 мес: тебе +7 дней / Pro +5 дней / Family +3 дня"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📨 Поделиться", url=_share_url(deep_link))],
        [
            InlineKeyboardButton(text="⬅️ Назад", callback_data="back"),
            InlineKeyboardButton(text="🏠 Главное меню", callback_data="back"),
        ],
    ])

    if isinstance(call_or_msg, CallbackQuery):
        await edit_message_text(call_or_msg, text, reply_markup=kb)
        await call_or_msg.answer()
    else:
        await call_or_msg.answer(text, reply_markup=kb)


@router.callback_query(F.data == "ref")
@router.callback_query(F.data == "referrals")
@router.message(Command("ref"))
@router.message(Command("referrals"))
async def cb_ref(event, bot: Bot) -> None:
    await _render(event, bot)
