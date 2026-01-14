# -*- coding: utf-8 -*-

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from ..services.catalog import list_plan_options_by_code, plan_title

def buy_manage_kb() -> InlineKeyboardMarkup:
    """
    Хаб управления (когда подписка активна).
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📱 Менеджер устройств", callback_data="devices")],
        [InlineKeyboardButton(text="📦 Тариф", callback_data="sub")],
        [InlineKeyboardButton(text="🧠 Режимы", callback_data="modes")],
        [InlineKeyboardButton(text="📊 Трафик", callback_data="traffic")],
        [
            InlineKeyboardButton(text="🆘 Поддержка", callback_data="support"),
            InlineKeyboardButton(text="❓ FAQ", callback_data="faq"),
        ],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back")],
    ])


def trial_activated_kb() -> InlineKeyboardMarkup:
    """
    Экран после Trial: ведём пользователя сразу к подключению.
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Подключить устройство", callback_data="dev:add")],
        [InlineKeyboardButton(text="📱 Мои устройства", callback_data="devices")],
        [
            InlineKeyboardButton(text="⬅️ Назад", callback_data="buy"),
            InlineKeyboardButton(text="🏠 Главное меню", callback_data="back"),
        ],
    ])

def _min_price(code: str) -> int:
    options = list_plan_options_by_code(code)
    return min(opt.price_rub for opt in options) if options else 0


def subscription_plans_kb(*, include_trial: bool = True) -> InlineKeyboardMarkup:
    start_price = _min_price("start")
    pro_price = _min_price("pro")
    family_price = _min_price("family")
    return InlineKeyboardMarkup(inline_keyboard=[
        *(
            [[InlineKeyboardButton(text="🎁 Попробовать бесплатно (48 часов)", callback_data="plan:trial:0")]]
            if include_trial
            else []
        ),
        [InlineKeyboardButton(text=f"{plan_title('start')} — от {start_price} ₽", callback_data="plan_group:start")],
        [InlineKeyboardButton(text=f"{plan_title('pro')} — от {pro_price} ₽", callback_data="plan_group:pro")],
        [InlineKeyboardButton(text=f"{plan_title('family')} — от {family_price} ₽", callback_data="plan_group:family")],
        [InlineKeyboardButton(text="🎟 Ввести промокод", callback_data="buy:promo")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back")],
    ])


def promo_input_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="buy")],
    ])
