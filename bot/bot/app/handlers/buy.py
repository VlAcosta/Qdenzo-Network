# -*- coding: utf-8 -*-
import json

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message, User

from aiogram.types import LabeledPrice, PreCheckoutQuery
from loguru import logger

from ..marzban.client import MarzbanClient
from ..models import Order
from ..services.orders import mark_order_paid
from ..services.catalog import get_plan_option
from ..services.payments import (
    CryptoPayClient,
    YooKassaClient,
    is_cryptopay_paid,
    is_yookassa_paid,
    load_order_meta,
    update_order_meta,
)

from ..config import settings
from ..db import session_scope
from ..keyboards.buy import buy_manage_kb, trial_activated_kb
from ..keyboards.orders import order_payment_kb
from ..keyboards.plans import plans_kb
from ..services import create_subscription_order, get_order, get_or_create_subscription
from ..services.subscriptions import activate_trial, is_active
from ..services.users import get_or_create_user
from ..utils.text import h
from ..utils.telegram import edit_message_text



router = Router()


def _marzban_client() -> MarzbanClient:
    return MarzbanClient(
        base_url=str(settings.marzban_base_url),
        username=settings.marzban_username,
        password=settings.marzban_password,
        verify_ssl=settings.marzban_verify_ssl,
    )


def _yookassa_enabled() -> bool:
    return bool(settings.yookassa_shop_id and settings.yookassa_secret_key and settings.yookassa_return_url)


def _cryptopay_enabled() -> bool:
    return bool(settings.cryptopay_token)



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

async def _get_order_for_user(session, order_id: int, user: User) -> Order | None:
    order = await get_order(session, order_id)
    if not order:
        return None
    db_user = await get_or_create_user(
        session=session,
        tg_id=user.id,
        username=user.username,
        first_name=user.first_name,
        ref_code=None,
        locale=getattr(user, "language_code", None),
    )
    if order.user_id != db_user.id:
        return None
    return order



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

@router.callback_query(F.data == "buy:plans")
async def cb_buy_plans(call: CallbackQuery) -> None:
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
        order = await create_subscription_order(session, user.id, code, months, payment_method="manual")

    text = _plan_choice_text(code, months)
    text += "\n<b>Оплата:</b> выберите способ ниже.\n"
    if settings.payment_manual_enabled:
        text += f"{h(settings.manual_payment_text)}\n\n"
    text += f"Поддержка: {h(settings.support_username)}"

    await edit_message_text(
        call,
        text,
        reply_markup=order_payment_kb(
            order.id,
            yookassa_enabled=_yookassa_enabled(),
            yookassa_url=settings.yookassa_pay_url,
            crypto_enabled=_cryptopay_enabled(),
            crypto_url=settings.crypto_pay_url,
            stars_enabled=settings.payment_stars_enabled,
            manual_enabled=settings.payment_manual_enabled,
        )
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

@router.callback_query(F.data.startswith("pay:yookassa:"))
async def cb_pay_yookassa(call: CallbackQuery) -> None:
    if not _yookassa_enabled():
        await call.answer("YooKassa не настроена.", show_alert=True)
        return

    order_id = int(call.data.split(":", 2)[2])
    async with session_scope() as session:
        order = await _get_order_for_user(session, order_id, call.from_user)
        if not order:
            await call.answer("Заказ не найден", show_alert=True)
            return
        if order.status != "pending":
            await call.answer("Заказ уже обработан", show_alert=True)
            return

        meta = load_order_meta(order)
        if meta.get("provider") == "yookassa" and meta.get("pay_url"):
            pay_url = meta["pay_url"]
        else:
            client = YooKassaClient(settings.yookassa_shop_id, settings.yookassa_secret_key)
            try:
                payment = await client.create_payment(
                    amount_rub=order.amount_rub,
                    description=f"Заказ #{order.id}",
                    return_url=settings.yookassa_return_url,
                    metadata={"order_id": order.id, "tg_id": call.from_user.id},
                )
            except Exception:
                logger.exception("Failed to create YooKassa payment for order %s", order.id)
                await call.answer("Не удалось создать платеж. Попробуйте позже.", show_alert=True)
                return

            pay_url = payment.confirmation_url
            update_order_meta(
                order,
                {
                    "provider": "yookassa",
                    "provider_payment_id": payment.payment_id,
                    "pay_url": pay_url,
                    "amount": order.amount_rub,
                    "currency": "RUB",
                    "metadata": {"order_id": order.id, "tg_id": call.from_user.id},
                },
            )
            order.payment_method = "yookassa"
            session.add(order)
            await session.commit()

    if not pay_url:
        await call.answer("Не удалось получить ссылку оплаты.", show_alert=True)
        return

    await edit_message_text(
        call,
        "💳 Счёт YooKassa создан. Нажмите кнопку ниже для оплаты.",
        reply_markup=order_payment_kb(order_id, pay_url=pay_url, show_check=True),
    )
    await call.answer()


@router.callback_query(F.data.startswith("pay:cryptopay:"))
async def cb_pay_cryptopay(call: CallbackQuery) -> None:
    if not _cryptopay_enabled():
        await call.answer("Crypto Pay не настроен.", show_alert=True)
        return

    order_id = int(call.data.split(":", 2)[2])
    async with session_scope() as session:
        order = await _get_order_for_user(session, order_id, call.from_user)
        if not order:
            await call.answer("Заказ не найден", show_alert=True)
            return
        if order.status != "pending":
            await call.answer("Заказ уже обработан", show_alert=True)
            return

        meta = load_order_meta(order)
        if meta.get("provider") == "cryptopay" and meta.get("pay_url"):
            pay_url = meta["pay_url"]
        else:
            client = CryptoPayClient(settings.cryptopay_token)
            payload = json.dumps({"order_id": order.id, "tg_id": call.from_user.id})
            amount = str(order.amount_rub)  # TODO: convert RUB to CryptoPay asset amount.
            try:
                invoice = await client.create_invoice(
                    amount=amount,
                    asset=settings.cryptopay_asset,
                    description=f"Заказ #{order.id}",
                    payload=payload,
                )
            except Exception:
                logger.exception("Failed to create CryptoPay invoice for order %s", order.id)
                await call.answer("Не удалось создать счет. Попробуйте позже.", show_alert=True)
                return

            pay_url = invoice.pay_url
            update_order_meta(
                order,
                {
                    "provider": "cryptopay",
                    "provider_invoice_id": invoice.invoice_id,
                    "pay_url": pay_url,
                    "amount": amount,
                    "currency": settings.cryptopay_asset,
                    "metadata": {"order_id": order.id, "tg_id": call.from_user.id},
                },
            )
            order.payment_method = "cryptopay"
            session.add(order)
            await session.commit()

    if not pay_url:
        await call.answer("Не удалось получить ссылку оплаты.", show_alert=True)
        return

    await edit_message_text(
        call,
        "🪙 Счёт Crypto Pay создан. Нажмите кнопку ниже для оплаты.",
        reply_markup=order_payment_kb(order_id, pay_url=pay_url, show_check=True),
    )
    await call.answer()


@router.callback_query(F.data.startswith("check:"))
async def cb_check_payment(call: CallbackQuery) -> None:
    order_id = int(call.data.split(":", 1)[1])
    async with session_scope() as session:
        order = await _get_order_for_user(session, order_id, call.from_user)
        if not order:
            await call.answer("Заказ не найден", show_alert=True)
            return
        if order.status != "pending":
            await call.answer("Заказ уже обработан", show_alert=True)
            return

        meta = load_order_meta(order)
        provider = meta.get("provider")
        if provider == "cryptopay":
            if not _cryptopay_enabled():
                await call.answer("Crypto Pay не настроен.", show_alert=True)
                return
            invoice_id = meta.get("provider_invoice_id")
            if not invoice_id:
                await call.answer("Счет не найден.", show_alert=True)
                return
            client = CryptoPayClient(settings.cryptopay_token)
            invoice = await client.get_invoice(int(invoice_id))
            if not invoice or not is_cryptopay_paid(invoice.status):
                await call.answer("Оплата еще не подтверждена.", show_alert=True)
                return
        elif provider == "yookassa":
            if not _yookassa_enabled():
                await call.answer("YooKassa не настроена.", show_alert=True)
                return
            payment_id = meta.get("provider_payment_id")
            if not payment_id:
                await call.answer("Платеж не найден.", show_alert=True)
                return
            client = YooKassaClient(settings.yookassa_shop_id, settings.yookassa_secret_key)
            payment = await client.get_payment(str(payment_id))
            if not is_yookassa_paid(payment.status):
                await call.answer("Оплата еще не подтверждена.", show_alert=True)
                return
        else:
            await call.answer("Автоплатеж для заказа не настроен.", show_alert=True)
            return

        marz = _marzban_client()
        new_exp, _ = await mark_order_paid(session=session, marz=marz, order=order)

    await edit_message_text(
        call,
        f"✅ Оплата подтверждена!\nПодписка активирована до: {new_exp:%Y-%m-%d %H:%M} UTC\nЗаказ #{order_id}",
    )
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
        if order.payment_method != "manual" or not settings.payment_manual_enabled:
            await call.answer("Этот способ оплаты обрабатывается автоматически.", show_alert=True)
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


@router.callback_query(F.data.startswith("stars:"))
async def cb_stars_pay(call: CallbackQuery, bot: Bot) -> None:
    order_id = int(call.data.split(":")[1])

    async with session_scope() as session:
        order = await get_order(session, order_id)
        if not order or order.user_id is None:
            await call.answer("Заказ не найден", show_alert=True)
            return

        # защита: заказ должен принадлежать пользователю
        user = await get_or_create_user(
            session=session,
            tg_id=call.from_user.id,
            username=call.from_user.username,
        )
        if order.user_id != user.id:
            await call.answer("Это не ваш заказ", show_alert=True)
            return

        if order.status != "pending":
            await call.answer(f"Нельзя оплатить: статус {order.status}", show_alert=True)
            return

        plan = get_plan_option(order.plan_code, int(order.months))
        stars_amount = max(1, int(round(plan.price_rub * settings.stars_per_rub)))

        # фиксируем метод и валюту (в твоей модели amount_rub используем как "amount" вообще)
        order.payment_method = "stars"
        order.currency = "XTR"
        order.amount_rub = stars_amount
        session.add(order)
        await session.commit()

    payload = f"order:{order_id}:{call.from_user.id}"

    await bot.send_invoice(
        chat_id=call.message.chat.id,
        title=f"Подписка {plan.name}",
        description=f"{plan.name} на {plan.months} мес.",
        payload=payload,
        currency="XTR",
        prices=[LabeledPrice(label="Подписка", amount=stars_amount)],
        provider_token=None,  # важно: не пустая строка
    )

    await call.answer()

@router.pre_checkout_query()
async def stars_pre_checkout(pre: PreCheckoutQuery) -> None:
    # Подтверждаем платеж перед списанием
    # Можно тут валидировать payload/заказ
    await pre.answer(ok=True)

@router.message(F.successful_payment)
async def stars_successful_payment(message: Message, bot: Bot) -> None:
    sp = message.successful_payment
    payload = sp.invoice_payload or ""

    # ожидаем payload вида order:<id>:<tg_id>
    try:
        _, order_id_s, tg_id_s = payload.split(":")
        order_id = int(order_id_s)
        tg_id = int(tg_id_s)
    except Exception:
        await message.answer("Оплата получена, но payload не распознан. Напишите в поддержку.")
        return

    if message.from_user.id != tg_id:
        await message.answer("Оплата получена, но пользователь не совпадает. Напишите в поддержку.")
        return

    marz = MarzbanClient(
        base_url=str(settings.marzban_base_url),
        username=settings.marzban_username,
        password=settings.marzban_password,
        verify_ssl=settings.marzban_verify_ssl,
    )

    async with session_scope() as session:
        order = await get_order(session, order_id)
        if not order:
            await message.answer("Оплата получена, но заказ не найден. Напишите в поддержку.")
            return

        # еще раз защита по владельцу
        user = await get_or_create_user(
            session=session,
            tg_id=message.from_user.id,
            username=message.from_user.username,
        )
        if order.user_id != user.id:
            await message.answer("Оплата получена, но заказ не ваш. Напишите в поддержку.")
            return

        new_exp, notes = await mark_order_paid(session=session, marz=marz, order=order)

    await message.answer(
        f"✅ Оплата Stars прошла успешно!\n"
        f"Подписка активирована до: {new_exp:%Y-%m-%d %H:%M} UTC\n"
        f"Заказ #{order_id}\n"
        f"Метод: ⭐ Stars"
    )
