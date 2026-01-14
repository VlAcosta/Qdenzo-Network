# -*- coding: utf-8 -*-

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from ..services.catalog import (
    TRIAL_HOURS,
    PlanOption,
    list_paid_plans,
    list_plan_options_by_code,
    plan_options,
    plan_title,
)
from ..utils.text import months_title

def plans_kb(*, include_trial: bool = True) -> InlineKeyboardMarkup:
    return plan_groups_kb(include_trial=include_trial, back_cb="back", callback_prefix="plan_group")


def plan_groups_kb(
    *,
    include_trial: bool = True,
    back_cb: str,
    callback_prefix: str = "plan_group",
    exclude_codes: set[str] | None = None,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    exclude = exclude_codes or set()

    if include_trial:
        rows.append([
            InlineKeyboardButton(
                text="🎁 Попробовать бесплатно (48 часов)",
                callback_data="plan:trial:0",
            )
        ])

    for code in list_paid_plans():
        if code in exclude:
            continue
        options = list_plan_options_by_code(code)
        if not options:
            continue
        min_price = min(opt.price_rub for opt in options)
        title = f"{plan_title(code)} — от {min_price} ₽"
        rows.append([InlineKeyboardButton(text=title, callback_data=f"{callback_prefix}:{code}")])

    rows.append([InlineKeyboardButton(text='⬅️ Назад', callback_data=back_cb)])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def plan_options_kb(
    options: list[PlanOption],
    *,
    back_cb: str,
    callback_prefix: str = "plan",
    promo_discount_rub: int = 0,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for opt in options:
        if opt.months == 0:
            months_title = f"{TRIAL_HOURS} часов"
        elif opt.months == 1:
            months_title = "1 месяц"
        elif opt.months in (2, 3, 4):
            months_title = f"{opt.months} месяца"
        else:
            months_title = f"{opt.months} месяцев"
        final_price = max(0, opt.price_rub - promo_discount_rub) if promo_discount_rub else opt.price_rub
        if promo_discount_rub and final_price != opt.price_rub:
            title = f"{months_title} — {opt.price_rub} ₽ → {final_price} ₽"
        else:
            title = f"{months_title} — {opt.price_rub} ₽"
        rows.append([InlineKeyboardButton(text=title, callback_data=f"{callback_prefix}:{opt.code}:{opt.months}")])
    rows.append([InlineKeyboardButton(text='⬅️ Назад', callback_data=back_cb)])
    return InlineKeyboardMarkup(inline_keyboard=rows)