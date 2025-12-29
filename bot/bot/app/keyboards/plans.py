# -*- coding: utf-8 -*-

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from ..services.catalog import TRIAL_HOURS, plan_options


def plans_kb(*, include_trial: bool = True) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    for opt in plan_options(include_trial=include_trial):
        if opt.code == 'trial':
            title = f"🎁 Trial — {TRIAL_HOURS}ч — бесплатно"
        else:
            title = f"{opt.name} — {opt.months} мес — {opt.price_rub}₽"
        rows.append([InlineKeyboardButton(text=title, callback_data=f"plan:{opt.code}:{opt.months}")])

    rows.append([InlineKeyboardButton(text='⬅️ Назад', callback_data='back')])
    return InlineKeyboardMarkup(inline_keyboard=rows)
