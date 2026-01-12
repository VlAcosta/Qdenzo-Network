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
                text=f"🎁 Trial — {TRIAL_HOURS}ч — бесплатно",
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
        title = f"{plan_title(code)} — от {min_price}₽"
        rows.append([InlineKeyboardButton(text=title, callback_data=f"{callback_prefix}:{code}")])

    rows.append([InlineKeyboardButton(text='⬅️ Назад', callback_data=back_cb)])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def plan_options_kb(
    options: list[PlanOption],
    *,
    back_cb: str,
    callback_prefix: str = "plan",
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for opt in options:
        if opt.code == 'trial':
            title = f"🎁 Trial — {TRIAL_HOURS}ч — бесплатно"
        else:
            title = f"{opt.name} — {opt.months} мес — {opt.price_rub}₽"
        rows.append([InlineKeyboardButton(text=title, callback_data=f"{callback_prefix}:{opt.code}:{opt.months}")])
    rows.append([InlineKeyboardButton(text='⬅️ Назад', callback_data=back_cb)])
    return InlineKeyboardMarkup(inline_keyboard=rows)