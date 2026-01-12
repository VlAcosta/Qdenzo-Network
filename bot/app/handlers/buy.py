# -*- coding: utf-8 -*-
import json
import os
from decimal import Decimal, ROUND_UP
from uuid import uuid4

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message, User

from aiogram.types import LabeledPrice, PreCheckoutQuery
from loguru import logger

from ..marzban.client import MarzbanClient
from ..models import Order
from ..services.orders import mark_order_paid
from ..services.catalog import get_plan_option, plan_options, plan_title
from ..services.payments import (
    CryptoPayClient,
    YooKassaClient,
    is_cryptopay_paid,
    is_yookassa_paid,
)
from ..services.payments.common import update_order_meta

from ..config import settings
from ..db import session_scope
from ..keyboards.buy import buy_manage_kb, trial_activated_kb
from ..keyboards.orders import order_canceled_kb, order_payment_kb
from ..keyboards.plans import plan_options_kb, plans_kb
from ..services import create_subscription_order, get_order, get_or_create_subscription
from ..services.devices import count_active_devices
from ..services.subscriptions import activate_trial, is_active
from ..services.users import get_or_create_user
from ..utils.text import fmt_dt, h
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
    return bool(
        getattr(settings, "yookassa_shop_id", None)
        and getattr(settings, "yookassa_secret_key", None)
        and getattr(settings, "yookassa_return_url", None)
    )


def _cryptopay_enabled() -> bool:
    return bool(getattr(settings, "cryptopay_token", None))

def _stars_enabled() -> bool:
    return bool(settings.payment_stars_enabled and settings.tg_stars_enabled)


def _traffic_limit_gb(plan_code: str) -> int:
    return {
        "trial": settings.traffic_limit_trial_gb,
        "start": settings.traffic_limit_start_gb,
        "pro": settings.traffic_limit_pro_gb,
        "family": settings.traffic_limit_family_gb,
    }.get(plan_code, 0)

def _stars_price(plan_code: str, months: int, price_rub: int) -> int:
    key = f"STARS_PRICE_{plan_code.upper()}_{months}"
    value = os.getenv(key)
    if value:
        try:
            return max(1, int(value))
        except ValueError:
            pass
    return max(1, int(round(price_rub * settings.stars_per_rub)))


def _find_rate(rates: list[dict[str, str]], source: str, target: str) -> Decimal | None:
    for rate in rates:
        if rate.get("source") == source and rate.get("target") == target:
            try:
                return Decimal(str(rate.get("rate")))
            except Exception:
                return None
    return None


async def _cryptopay_amount_rub(
    client: CryptoPayClient, *, amount_rub: int, asset: str
) -> str:
    rates = await client.get_exchange_rates()
    rate = _find_rate(rates, asset, "RUB")
    if rate is None:
        rate_usd = _find_rate(rates, asset, "USD")
        usd_rub = _find_rate(rates, "USD", "RUB")
        if rate_usd is not None and usd_rub is not None:
            rate = rate_usd * usd_rub
    if rate is None or rate <= 0:
        raise ValueError("crypto_rate_unavailable")
    amount_asset = (Decimal(amount_rub) / rate).quantize(Decimal("0.000001"), rounding=ROUND_UP)
    if amount_asset <= 0:
        raise ValueError("crypto_amount_invalid")
    return format(amount_asset.normalize(), "f")


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
        devices_active = await count_active_devices(session, user.id)

    if is_active(sub):
        traffic_limit = _traffic_limit_gb(sub.plan_code)
        await edit_message_text(
            call,
            "⚙️ <b>Управление</b> "
            f"(ID: <code>{user.tg_id}</code>, Баланс: <b>—</b>, "
            f"Дата окончания подписки: <b>{fmt_dt(sub.expires_at)}</b>, "
            f"Трафик: <b>0/{traffic_limit} GB</b>, "
            f"Активных устройств: <b>{devices_active}</b>)\n\n"
            "Выберите действие 👇",
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


@router.callback_query(F.data.startswith("plan_group:"))
async def cb_plan_group(call: CallbackQuery) -> None:
    parts = call.data.split(":")
    if len(parts) != 2:
        return
    _, code = parts
    options = [opt for opt in plan_options(include_trial=False) if opt.code == code]
    if not options:
        await call.answer("Тариф не найден", show_alert=True)
        return
    text = f"💳 <b>{h(plan_title(code))}</b>\nВыберите период подписки:"
    await edit_message_text(
        call,
        text,
        reply_markup=plan_options_kb(options, back_cb="buy:plans"),
    )
    await call.answer()


@router.callback_query(F.data.startswith("plan:"))
async def cb_plan(call: CallbackQuery, bot: Bot) -> None:
    parts = call.data.split(":")
    action = None
    if len(parts) == 4:
        _, action, code, months_s = parts
    else:
        _, code, months_s = parts
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
        order = await create_subscription_order(
            session,
            user.id,
            code,
            months,
            payment_method="manual",
            provider="manual",
            action=action,
        )
        sub = await get_or_create_subscription(session, user.id)

    text = _plan_choice_text(code, months)
    if action == "renew":
        text += (
            f"\n<b>Продление</b>: текущий тариф — <b>{h(sub.plan_code.upper())}</b>\n"
            f"Окончание: <b>{fmt_dt(sub.expires_at)}</b>\n"
        )
    elif action == "change":
        text += (
            f"\n<b>Смена тарифа</b>: сейчас у вас <b>{h(sub.plan_code.upper())}</b>\n"
            f"Окончание: <b>{fmt_dt(sub.expires_at)}</b>\n"
            "Новый тариф применится сразу после оплаты.\n"
        )
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
            stars_enabled=_stars_enabled(),
            manual_enabled=settings.payment_manual_enabled
            and not (_yookassa_enabled() or _cryptopay_enabled() or _stars_enabled()),
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

        if order.provider == "yookassa" and order.pay_url:
            pay_url = order.pay_url
        else:
            shop_id = getattr(settings, "yookassa_shop_id", None)
            secret_key = getattr(settings, "yookassa_secret_key", None)
            return_url = getattr(settings, "yookassa_return_url", None)
            client = YooKassaClient(shop_id, secret_key)
            try:
                payment = await client.create_payment(
                    amount_rub=order.amount_rub,
                    description=f"Заказ #{order.id}",
                    return_url=return_url,
                    metadata={
                        "order_id": order.id,
                        "tg_id": call.from_user.id,
                        "plan_code": order.plan_code,
                        "months": order.months,
                    },
                    idempotence_key=f"{order.id}-{uuid4()}",
                )
            except Exception:
                logger.exception("Failed to create YooKassa payment for order %s", order.id)
                await call.answer("Не удалось создать платеж. Попробуйте позже.", show_alert=True)
                return

            pay_url = payment.confirmation_url
            order.provider = "yookassa"
            order.provider_payment_id = payment.payment_id
            order.pay_url = pay_url
            order.amount = f"{order.amount_rub:.2f}"
            order.currency = "RUB"
            order.raw_provider_payload = json.dumps(payment.raw, ensure_ascii=False)
            order.payment_method = "yookassa"
            update_order_meta(
                order,
                {
                    "yookassa_payment_id": payment.payment_id,
                    "yookassa_confirmation_url": payment.confirmation_url,
                },
            )
            session.add(order)
            await session.commit()

    if not pay_url:
        await call.answer("Не удалось получить ссылку оплаты.", show_alert=True)
        return

    await edit_message_text(
        call,
        "💳 Счёт YooKassa создан. Нажмите кнопку ниже для оплаты.",
        reply_markup=order_payment_kb(order_id, pay_url=pay_url, show_check=True, manual_enabled=False),
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

        if order.provider == "cryptopay" and order.pay_url:
            pay_url = order.pay_url
        else:
            cryptopay_token = getattr(settings, "cryptopay_token", None)
            client = CryptoPayClient(cryptopay_token)
            payload = json.dumps(
                {"order_id": order.id, "tg_id": call.from_user.id, "plan_code": order.plan_code, "months": order.months},
                ensure_ascii=False,
            )
            try:
                amount = await _cryptopay_amount_rub(
                    client,
                    amount_rub=order.amount_rub,
                    asset=getattr(settings, "cryptopay_asset", "USDT"),
                )
            except Exception:
                logger.exception("Failed to resolve CryptoPay rate for order %s", order.id)
                await call.answer("Не удалось рассчитать сумму. Попробуйте позже.", show_alert=True)
                return
            try:
                invoice = await client.create_invoice(
                    amount=amount,
                    asset=getattr(settings, "cryptopay_asset", "USDT"),
                    description=f"Заказ #{order.id}",
                    payload=payload,
                    expires_in=settings.cryptopay_invoice_expires_in,
                )
            except Exception:
                logger.exception("Failed to create CryptoPay invoice for order %s", order.id)
                await call.answer("Не удалось создать счет. Попробуйте позже.", show_alert=True)
                return

            pay_url = invoice.pay_url
            order.provider = "cryptopay"
            order.provider_payment_id = str(invoice.invoice_id)
            order.pay_url = pay_url
            order.amount = amount
            order.currency = settings.cryptopay_asset
            order.raw_provider_payload = json.dumps(invoice.raw, ensure_ascii=False)
            order.payment_method = "cryptopay"
            update_order_meta(
                order,
                {
                    "cryptopay_invoice_id": invoice.invoice_id,
                    "cryptopay_pay_url": invoice.pay_url,
                },
            )
            session.add(order)
            await session.commit()

    if not pay_url:
        await call.answer("Не удалось получить ссылку оплаты.", show_alert=True)
        return

    await edit_message_text(
        call,
        "🪙 Счёт Crypto Pay создан. Нажмите кнопку ниже для оплаты.",
        reply_markup=order_payment_kb(order_id, pay_url=pay_url, show_check=True, manual_enabled=False),
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

        provider = order.provider
        if provider == "cryptopay":
            if not _cryptopay_enabled():
                await call.answer("Crypto Pay не настроен.", show_alert=True)
                return
            invoice_id = order.provider_payment_id
            if not invoice_id:
                await call.answer("Счет не найден.", show_alert=True)
                return
            cryptopay_token = getattr(settings, "cryptopay_token", None)
            client = CryptoPayClient(cryptopay_token)
            try:
                invoice = await client.get_invoice(int(invoice_id))
            except Exception:
                logger.exception("Failed to fetch CryptoPay invoice %s", invoice_id)
                await call.answer("Не удалось проверить оплату. Попробуйте позже.", show_alert=True)
                return
            if not invoice or not is_cryptopay_paid(invoice.status):
                await call.answer("Оплата еще не подтверждена.", show_alert=True)
                return
            order.raw_provider_payload = json.dumps(invoice.raw, ensure_ascii=False)
        elif provider == "yookassa":
            if not _yookassa_enabled():
                await call.answer("YooKassa не настроена.", show_alert=True)
                return
            payment_id = order.provider_payment_id
            if not payment_id:
                await call.answer("Платеж не найден.", show_alert=True)
                return
            shop_id = getattr(settings, "yookassa_shop_id", None)
            secret_key = getattr(settings, "yookassa_secret_key", None)
            client = YooKassaClient(shop_id, secret_key)
            try:
                payment = await client.get_payment(str(payment_id))
            except Exception:
                logger.exception("Failed to fetch YooKassa payment %s", payment_id)
                await call.answer("Не удалось проверить оплату. Попробуйте позже.", show_alert=True)
                return
            if not is_yookassa_paid(payment.status):
                await call.answer("Оплата еще не подтверждена.", show_alert=True)
                return
            order.raw_provider_payload = json.dumps(payment.raw, ensure_ascii=False)
        else:
            await call.answer("Автоплатеж для заказа не настроен.", show_alert=True)
            return

        marz = _marzban_client()
        try:
            new_exp, _ = await mark_order_paid(session=session, marz=marz, order=order)
        finally:
            await marz.close()

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
    await edit_message_text(call, f"❌ Заказ #{order_id} отменён.", reply_markup=order_canceled_kb())
    await call.answer()


@router.callback_query(F.data.startswith("stars:"))
async def cb_stars_pay(call: CallbackQuery, bot: Bot) -> None:
    if not _stars_enabled():
        await call.answer("Stars не настроены.", show_alert=True)
        return
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
        stars_amount = _stars_price(plan.code, plan.months, plan.price_rub)

        order.provider = "stars"
        order.payment_method = "stars"
        order.currency = "XTR"
        order.amount = str(stars_amount)
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
    payload = pre.invoice_payload or ""
    try:
        _, order_id_s, tg_id_s = payload.split(":")
        order_id = int(order_id_s)
        tg_id = int(tg_id_s)
    except Exception:
        await pre.answer(ok=False, error_message="Некорректный заказ.")
        return

    if pre.from_user.id != tg_id:
        await pre.answer(ok=False, error_message="Пользователь не совпадает.")
        return

    async with session_scope() as session:
        order = await get_order(session, order_id)
        if not order or order.status != "pending":
            await pre.answer(ok=False, error_message="Заказ уже обработан.")
            return

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
        if order.status != "pending":
            await message.answer("Оплата уже обработана. Спасибо!")
            return


        order.provider = "stars"
        order.payment_method = "stars"
        order.provider_payment_id = sp.telegram_payment_charge_id
        order.currency = sp.currency or "XTR"
        order.amount = str(sp.total_amount)
        order.raw_provider_payload = json.dumps(sp.model_dump(), ensure_ascii=False)
        update_order_meta(order, {"telegram_payment_charge_id": sp.telegram_payment_charge_id})
        session.add(order)
        await session.commit()

        try:
            new_exp, notes = await mark_order_paid(session=session, marz=marz, order=order)
        finally:
            await marz.close()
            
    await message.answer(
        f"✅ Оплата Stars прошла успешно!\n"
        f"Подписка активирована до: {new_exp:%Y-%m-%d %H:%M} UTC\n"
        f"Заказ #{order_id}\n"
        f"Метод: ⭐ Stars"
    )
