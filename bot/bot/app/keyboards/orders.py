# -*- coding: utf-8 -*-

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup



def order_payment_kb(
    order_id: int,
    *,
    yookassa_enabled: bool = False,
    yookassa_url: str | None = None,
    crypto_enabled: bool = False,
    crypto_url: str | None = None,
    stars_enabled: bool = False,
    manual_enabled: bool = False,
    pay_url: str | None = None,
    show_check: bool = False,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    if pay_url:
        rows.append([InlineKeyboardButton(text="Перейти к оплате", url=pay_url)])
    else:
        if yookassa_enabled:
            rows.append([InlineKeyboardButton(text="💳 Карта/СБП", callback_data=f"pay:yookassa:{order_id}")])
        elif yookassa_url:
            rows.append([InlineKeyboardButton(text="💳 Карта/СБП", url=yookassa_url)])
        if crypto_enabled:
            rows.append([InlineKeyboardButton(text="🪙 Крипта", callback_data=f"pay:cryptopay:{order_id}")])
        elif crypto_url:
            rows.append([InlineKeyboardButton(text="🪙 Крипта", url=crypto_url)])

    if stars_enabled:
        rows.append([InlineKeyboardButton(text="⭐ Telegram Stars", callback_data=f"stars:{order_id}")])

    if show_check:
        rows.append([InlineKeyboardButton(text="🔄 Проверить оплату", callback_data=f"check:{order_id}")])

    if manual_enabled and not pay_url:
        rows.append([InlineKeyboardButton(text="✅ Я оплатил", callback_data=f"paid:{order_id}")])

    rows.append([InlineKeyboardButton(text="❌ Отменить", callback_data=f"cancel_order:{order_id}")])

    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def order_canceled_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Выбрать тариф", callback_data="buy:plans")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back")],
    ])