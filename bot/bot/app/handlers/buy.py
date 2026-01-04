# -*- coding: utf-8 -*-

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from ..config import settings
from ..db import session_scope
from ..keyboards.buy import buy_manage_kb, trial_activated_kb
from ..keyboards.orders import order_payment_kb
from ..keyboards.plans import plans_kb
from ..services import create_subscription_order, get_order, get_or_create_subscription
from ..services.catalog import get_plan_option
from ..services.subscriptions import activate_trial, is_active
from ..services.users import get_or_create_user
from ..utils.text import h
from ..utils.telegram import edit_message_text

router = Router()


def _plan_choice_text(code: str, months: int) -> str:
    opt = get_plan_option(code, months)
    if code == "trial":
        return (
            f"🎁 <b>Trial</b> активирован на <b>{opt.duration_days * 24} ч</b>\n\n"
            f"Лимит устройств: <b>{opt.devices_limit}</b>\n"
            "👇 Нажмите кнопку ниже, чтобы подключить первое устройство."
        )
    return (
        f"🧾 Вы выбрали: <b>{h(opt.name)}</b>\n"
        f"Срок: <b>{months} мес</b> (≈ {opt.duration_days} дней)\n"
        f"Устройства: <b>{opt.devices_limit}</b>\n"
        f"Стоимость: <b>{opt.price_rub} ₽</b>\n"
    )


async def _notify_admins(bot: Bot, text: str, reply_markup=None) -> None:
    for admin_id in settings.admin_id_list:
        try:
            await bot.send_message(admin_id, text, reply_markup=reply_markup)
        except Exception:
            pass


@router.message(Command("buy"))
async def cmd_buy(message: Message) -> None:
    await message.answer("💳 Выберите тариф:", reply_markup=plans_kb(include_trial=True))


@router.callback_query(F.data == "buy")
async def cb_buy(call: CallbackQuery) -> None:
    """
    Если подписка активна -> показываем хаб управления.
    Если не активна -> показываем тарифы.
    """
    async with session_scope() as session:
        user = await get_or_create_user(
            session=session,
            tg_id=call.from_user.id,
            username=call.from_user.username,
            first_name=call.from_user.first_name,
            ref_code=None,
            locale=call.from_user.language_code,
        )
        sub = await get_or_create_subscription(session, user.id)

    if is_active(sub):
        await edit_message_text(
            call,
            "⚙️ <b>Qdenzo Network — управление сервисом</b>\n\nВыберите действие 👇",
            reply_markup=buy_manage_kb(),
        )
        await call.answer()
        return

    await edit_message_text(call, "💳 Выберите тариф:", reply_markup=plans_kb(include_trial=True))
    await call.answer()


@router.callback_query(F.data.startswith("plan:"))
async def cb_plan(call: CallbackQuery, bot: Bot) -> None:
    _, code, months_s = call.data.split(":", 2)
    months = int(months_s)

    async with session_scope() as session:
        user = await get_or_create_user(
            session=session,
            tg_id=call.from_user.id,
            username=call.from_user.username,
            first_name=call.from_user.first_name,
            ref_code=None,
            locale=call.from_user.language_code,
        )
        if user.is_banned:
            await call.answer("Доступ ограничен", show_alert=True)
            return

        if code == "trial":
            ok, reason = await activate_trial(session, user)
            if not ok:
                await edit_message_text(call, f"⛔️ {h(reason)}", reply_markup=plans_kb(include_trial=False))
                await call.answer()
                return

            await edit_message_text(call, _plan_choice_text(code, months), reply_markup=trial_activated_kb())
            await call.answer("Trial активирован")
            return

        opt = get_plan_option(code, months)
        order = await create_subscription_order(session, user.id, code, months, opt.price_rub, payment_method="manual")

    text = _plan_choice_text(code, months)
    text += "\n<b>Оплата:</b> сейчас <i>Manual</i> (админ подтверждает).\n"
    text += "После оплаты нажмите <b>Я оплатил</b> и отправьте чек/скрин в поддержку.\n\n"
    text += f"Поддержка: {h(settings.support_username)}"

    await edit_message_text(
        call,
        text,
        reply_markup=order_payment_kb(
            order.id,
            yookassa_url=(settings.yookassa_pay_url or None),
            crypto_url=(settings.crypto_pay_url or None),
        ),
    )

    # Notify admins
    admin_text = (
        f"🧾 <b>Новый заказ</b> #{order.id}\n"
        f"Пользователь: <code>{user.tg_id}</code> (@{h(user.username)})\n"
        f"Тариф: <b>{h(opt.name)}</b> {months} мес\n"
        f"Сумма: <b>{opt.price_rub} ₽</b>\n"
    )
    from ..keyboards.admin import admin_order_action_kb
    await _notify_admins(bot, admin_text, reply_markup=admin_order_action_kb(order.id))

    await call.answer()


@router.callback_query(F.data.startswith("paid:"))
async def cb_paid(call: CallbackQuery, bot: Bot) -> None:
    order_id = int(call.data.split(":", 1)[1])
    async with session_scope() as session:
        order = await get_order(session, order_id)
        if not order:
            await call.answer("Заказ не найден", show_alert=True)
            return
        if order.user_id != (
            await get_or_create_user(
                session=session,
                tg_id=call.from_user.id,
                username=call.from_user.username,
                first_name=call.from_user.first_name,
                ref_code=None,
                locale=call.from_user.language_code,
            )
        ).id:
            await call.answer("Это не ваш заказ", show_alert=True)
            return
        if order.status != "pending":
            await call.answer("Заказ уже обработан", show_alert=True)
            return

    from ..keyboards.admin import admin_order_action_kb

    await _notify_admins(
        bot,
        f"✅ Пользователь отметил оплату по заказу #{order_id}. Проверьте и подтвердите.",
        reply_markup=admin_order_action_kb(order_id),
    )

    await edit_message_text(
        call,
        f"✅ Ок! Мы получили отметку об оплате заказа #{order_id}.\n"
        f"Обычно подтверждение занимает 1–30 минут.\n\n"
        f"Поддержка: {h(settings.support_username)}",
        reply_markup=None,
    )
    await call.answer()


@router.callback_query(F.data.startswith("cancel_order:"))
async def cb_cancel_order(call: CallbackQuery) -> None:
    order_id = int(call.data.split(":", 1)[1])
    async with session_scope() as session:
        order = await get_order(session, order_id)
        if not order:
            await call.answer("Не найдено", show_alert=True)
            return
        if order.user_id != (
            await get_or_create_user(
                session=session,
                tg_id=call.from_user.id,
                username=call.from_user.username,
                first_name=call.from_user.first_name,
                ref_code=None,
                locale=call.from_user.language_code,
            )
        ).id:
            await call.answer("Это не ваш заказ", show_alert=True)
            return
        if order.status != "pending":
            await call.answer("Уже обработан", show_alert=True)
            return
        order.status = "canceled"
        session.add(order)
        await session.commit()

    await edit_message_text(call, f"❌ Заказ #{order_id} отменён.")
    await call.answer()
