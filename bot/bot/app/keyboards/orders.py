# -*- coding: utf-8 -*-

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def order_payment_kb(
    order_id: int,
    *,
    yookassa_url: str | None = None,
    crypto_url: str | None = None,
    stars_enabled: bool = False,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    if yookassa_url:
        rows.append([InlineKeyboardButton(text="💳 Карта/СБП", url=yookassa_url)])
    if crypto_url:
        rows.append([InlineKeyboardButton(text="🪙 Крипта", url=crypto_url)])

    if stars_enabled:
        rows.append([InlineKeyboardButton(text="⭐ Telegram Stars", callback_data=f"stars:{order_id}")])

    rows.append([
        InlineKeyboardButton(text="✅ Я оплатил", callback_data=f"paid:{order_id}"),
        InlineKeyboardButton(text="❌ Отменить", callback_data=f"cancel:{order_id}"),
    ])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
