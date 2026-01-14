# -*- coding: utf-8 -*-

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def onboarding_start_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Старт", callback_data="onb:2")],
    ])


def onboarding_continue_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Продолжить", callback_data="onb:3")],
    ])


def onboarding_finish_kb(*, include_trial: bool = True) -> InlineKeyboardMarkup:
    rows = []
    if include_trial:
        rows.append([InlineKeyboardButton(text="🎁 Попробовать бесплатно (48 часов)", callback_data="plan:trial:0")])
    rows.append([InlineKeyboardButton(text="Перейти в главное меню", callback_data="nav:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)