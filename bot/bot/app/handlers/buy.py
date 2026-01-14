# -*- coding: utf-8 -*-
import json
import os
import math
from decimal import Decimal, ROUND_UP
from uuid import uuid4

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
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
from ..keyboards.buy import buy_manage_kb, promo_input_kb, subscription_plans_kb, trial_activated_kb
from ..keyboards.orders import order_canceled_kb, order_payment_kb
from ..keyboards.plans import plan_options_kb, plans_kb
from ..services import create_subscription_order, get_order, get_or_create_subscription
from ..services.devices import count_active_devices
from ..services.promos import promo_available_for_user, redeem_promo_to_balance
from ..services.subscriptions import activate_trial, is_active
from ..services.users import ensure_user
from ..utils.text import fmt_dt, h, months_title
from ..utils.telegram import edit_message_text, safe_answer_callback, send_html, send_html_with_photo

router = Router()

class BuyStates(StatesGroup):
    promo_input = State()


@router.message(BuyStates.promo_input)
async def msg_promo_input(message: Message, state: FSMContext) -> None:
    code = (message.text or "").strip()
    if not code:
        await send_html(message, "Введите промокод:")
        return
    async with session_scope() as session:
        user = await ensure_user(session=session, tg_user=message.from_user)
        promo, error = await promo_available_for_user(session, code=code, user_id=user.id)
        if not promo:
            await send_html(message, "Промокод не найден или больше недоступен.")
            await state.clear()
            return
        balance = await redeem_promo_to_balance(session, promo=promo, user=user)

    await send_html(
        message,
        f"✅ <b>Промокод применён:</b> {h(promo.code)}\n"
        f"💰 <b>Зачислено на баланс:</b> {promo.discount_rub} ₽\n"
        f"Баланс: <b>{balance} ₽</b>\n\n"
        "Теперь выберите тариф 👇",
        reply_markup=subscription_plans_kb(),
    )
    await state.clear()



def _marzban_client() -> MarzbanClient:
    return MarzbanClient(
        base_url=str(settings.marzban_base_url),
        username=settings.marzban_username,
        password=settings.marzban_password,
        verify_ssl=settings.marzban_verify_ssl,
        api_prefix=settings.marzban_api_prefix,
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
    key_variants = [
        f"STARS_{plan_code.upper()}_{months}M",
        f"STARS_PRICE_{plan_code.upper()}_{months}",
    ]
    value = None
    for key in key_variants:
        value = os.getenv(key)
        if value:
            break
    if value:
        try:
            return max(1, int(value))
        except ValueError:
            pass
    return max(1, int(math.ceil(price_rub * settings.stars_per_rub)))


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


def _plan_choice_text(code: str, months: int, *, final_price: int | None = None, discount: int = 0) -> str:
    opt = get_plan_option(code, months)
    if code == "trial":
        return (
            f"🎁 <b>Бесплатный доступ</b> активирован на <b>{opt.duration_days * 24} ч</b>\n\n"
            f"Лимит устройств: <b>{opt.devices_limit}</b>\n"
            "👇 Нажмите кнопку ниже, чтобы подключить первое устройство."
        )
    price = opt.price_rub if final_price is None else final_price
    discount_line = ""
    if discount:
        discount_line = f"Скидка: <b>{discount} ₽</b>\n"
    return (
        f"🧾 <b>Выбран тариф:</b> {h(opt.name)}\n"
        f"<b>Срок:</b> {months} {months_title(months, short=True)} (≈ {opt.duration_days} дней)\n"
        f"<b>Устройства:</b> {opt.devices_limit}\n"
        f"<b>Стоимость:</b> {price} ₽\n"
        f"{discount_line}"
    )


def _plans_menu_text() -> str:
    return (
        "<b>Выберите подходящий тариф:</b>\n\n"
        "🎁 Попробовать бесплатно (48 часов)\n\n"
        "Start — от 249 ₽\n"
        "Pro — от 399 ₽\n"
        "Family — от 1099 ₽\n\n"
        "🎟 Ввести промокод\n"
        "⬅ Назад"
    )

def _periods_text(code: str, discount_rub: int) -> str:
    options = [opt for opt in plan_options(include_trial=False) if opt.code == code]
    if not options:
        return "Тариф не найден."
    lines = ["<b>Выберите срок</b>\n"]
    for opt in options:
        months_label = f"{opt.months} {months_title(opt.months, short=False)}"
        final_price = max(0, opt.price_rub - discount_rub) if discount_rub else opt.price_rub
        if discount_rub and final_price != opt.price_rub:
            lines.append(f"{months_label} — {opt.price_rub} ₽ → {final_price} ₽")
        else:
            lines.append(f"{months_label} — {opt.price_rub} ₽")
    return "\n".join(lines)


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
    db_user = await ensure_user(session=session, tg_user=user)
    if order.user_id != db_user.id:
        return None
    return order



@router.message(Command("buy"))
async def cmd_buy(message: Message) -> None:
    await send_html_with_photo(
        message,
        _plans_menu_text(),
        reply_markup=subscription_plans_kb(),
        photo_path=settings.start_photo_path,
    )

@router.callback_query(F.data == "buy")
async def cb_buy(call: CallbackQuery) -> None:
    await safe_answer_callback(call)
    """
    Если подписка активна -> показываем хаб управления.
    Если не активна -> показываем тарифы.
    """
    async with session_scope() as session:
        user = await ensure_user(session=session, tg_user=call.from_user)
        sub = await get_or_create_subscription(session, user.id)
        devices_active = await count_active_devices(session, user.id)

    if is_active(sub):
        traffic_limit = _traffic_limit_gb(sub.plan_code)
        await edit_message_text(
            call,
            "⚙️ <b>Управление</b>\n\n"
            f"<b>ID:</b> <code>{user.tg_id}</code>\n"
            f"<b>Баланс:</b> {user.balance_rub} ₽\n"
            f"<b>Дата окончания подписки:</b> {fmt_dt(sub.expires_at)}\n"
            f"<b>Трафик:</b> 0/{traffic_limit} GB\n"
            f"<b>Активных устройств:</b> {devices_active}\n\n"
            "Выберите действие 👇",
            reply_markup=buy_manage_kb(),
        )

        return
    await edit_message_text(call, _plans_menu_text(), reply_markup=subscription_plans_kb())

@router.callback_query(F.data == "buy:plans")
async def cb_buy_plans(call: CallbackQuery) -> None:
    await safe_answer_callback(call)
    await safe_answer_callback(call)
    await edit_message_text(call, _plans_menu_text(), reply_markup=subscription_plans_kb())


@router.callback_query(F.data == "buy:promo")
async def cb_buy_promo(call: CallbackQuery, state: FSMContext) -> None:
    await safe_answer_callback(call)
    await state.set_state(BuyStates.promo_input)
    await edit_message_text(call, "Введите промокод:", reply_markup=promo_input_kb())


@router.callback_query(F.data.startswith("plan_group:"))
async def cb_plan_group(call: CallbackQuery, state: FSMContext) -> None:
    await safe_answer_callback(call)
    parts = call.data.split(":")
    if len(parts) != 2:
        return
    _, code = parts
    options = [opt for opt in plan_options(include_trial=False) if opt.code == code]
    if not options:
        await edit_message_text(call, "Тариф не найден.", reply_markup=subscription_plans_kb())
        return
    data = await state.get_data()
    discount_rub = int(data.get("promo_discount_rub") or 0)
    text = f"<b>{h(plan_title(code))}</b>\n\n{_periods_text(code, discount_rub)}"
    await edit_message_text(
        call,
        text,
        reply_markup=plan_options_kb(options, back_cb="buy:plans", promo_discount_rub=discount_rub),
    )



@router.callback_query(F.data.startswith("plan:"))
async def cb_plan(call: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    await safe_answer_callback(call)
    parts = call.data.split(":")
    action = None
    if len(parts) == 4:
        _, action, code, months_s = parts
    else:
        _, code, months_s = parts
    months = int(months_s)

    free_activation = False
    new_exp = None

    async with session_scope() as session:
        user = await ensure_user(session=session, tg_user=call.from_user)
        if user.is_banned:
            await edit_message_text(
                call,
                "⛔️ Доступ к боту ограничен.",
                reply_markup=subscription_plans_kb(),
            )
            return

        if code == "trial":
            ok, reason = await activate_trial(session, user)
            if not ok:
                await edit_message_text(call, f"⛔️ {h(reason)}", reply_markup=plans_kb(include_trial=False))
                return

            await edit_message_text(call, _plan_choice_text(code, months), reply_markup=trial_activated_kb())
            return

        opt = get_plan_option(code, months)
        data = await state.get_data()
        promo_discount_rub = int(data.get("promo_discount_rub") or 0)
        promo_id = data.get("promo_id")
        promo_code = data.get("promo_code")
        final_price = max(0, opt.price_rub - promo_discount_rub) if promo_discount_rub else opt.price_rub
        meta = {}
        if promo_id:
            meta = {
                "promo_id": promo_id,
                "promo_code": promo_code,
                "promo_discount_rub": promo_discount_rub,
                "price_rub_original": opt.price_rub,
            }
        order = await create_subscription_order(
            session,
            user.id,
            code,
            months,
            amount_rub=final_price,
            payment_method="manual",
            provider="manual",
            action=action,
            meta=meta or None,
        )
        sub = await get_or_create_subscription(session, user.id)
        if order.amount_rub <= 0:
            marz = _marzban_client()
            try:
                new_exp, _ = await mark_order_paid(session=session, marz=marz, order=order)
                free_activation = True
            finally:
                await marz.close()

    await state.clear()
    text = _plan_choice_text(code, months, final_price=final_price, discount=promo_discount_rub)
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

    if free_activation:
        await edit_message_text(
            call,
            f"✅ Подписка активирована до: {new_exp:%Y-%m-%d %H:%M} UTC\n"
            f"Заказ #{order.id} (скидка покрыла стоимость)",
        )
    else:
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
            ),
        )

    # Notify admins
    admin_text = (
        f"🧾 <b>Новый заказ</b> #{order.id}\n"
        f"Пользователь: <code>{user.tg_id}</code> (@{h(user.username)})\n"
        f"Тариф: <b>{h(opt.name)}</b> {months} {months_title(months, short=True)}\n"
        f"Сумма: <b>{order.amount_rub} ₽</b>\n"
    )
    from ..keyboards.admin import admin_order_action_kb
    await _notify_admins(bot, admin_text, reply_markup=admin_order_action_kb(order.id))


@router.callback_query(F.data.startswith("pay:yookassa:"))
async def cb_pay_yookassa(call: CallbackQuery) -> None:
    await safe_answer_callback(call)
    if not _yookassa_enabled():
        await edit_message_text(call, "YooKassa не настроена.", reply_markup=order_canceled_kb())
        return

    order_id = int(call.data.split(":", 2)[2])
    async with session_scope() as session:
        order = await _get_order_for_user(session, order_id, call.from_user)
        if not order:
            await edit_message_text(call, "Заказ не найден.", reply_markup=order_canceled_kb())
            return
        if order.status != "pending":
            await edit_message_text(call, "Заказ уже обработан.")
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
                await edit_message_text(call, "Не удалось создать платеж. Попробуйте позже.")
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
        await edit_message_text(call, "Не удалось получить ссылку оплаты.")
        return

    await edit_message_text(
        call,
        "💳 Счёт YooKassa создан. Нажмите кнопку ниже для оплаты.",
        reply_markup=order_payment_kb(order_id, pay_url=pay_url, show_check=True, manual_enabled=False),
    )


@router.callback_query(F.data.startswith("pay:cryptopay:"))
async def cb_pay_cryptopay(call: CallbackQuery) -> None:
    await safe_answer_callback(call)
    if not _cryptopay_enabled():
        await edit_message_text(call,"Crypto Pay не настроен.", show_alert=True)
        return

    order_id = int(call.data.split(":", 2)[2])
    async with session_scope() as session:
        order = await _get_order_for_user(session, order_id, call.from_user)
        if not order:
            await edit_message_text(call,"Заказ не найден", show_alert=True)
            return
        if order.status != "pending":
            await edit_message_text(call, "Заказ уже обработан.", reply_markup=order_canceled_kb())
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
                await edit_message_text(call, "Не удалось рассчитать сумму. Попробуйте позже.")
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
                await edit_message_text(call, "Не удалось создать счет. Попробуйте позже.")
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
        await edit_message_text(call, "Не удалось получить ссылку оплаты.")
        return

    await edit_message_text(
        call,
        "🪙 Счёт Crypto Pay создан. Нажмите кнопку ниже для оплаты.",
        reply_markup=order_payment_kb(order_id, pay_url=pay_url, show_check=True, manual_enabled=False),
    )



@router.callback_query(F.data.startswith("check:"))
async def cb_check_payment(call: CallbackQuery) -> None:
    await safe_answer_callback(call)
    order_id = int(call.data.split(":", 1)[1])
    async with session_scope() as session:
        order = await _get_order_for_user(session, order_id, call.from_user)
        if not order:
            await edit_message_text(call, "Заказ не найден.", reply_markup=order_canceled_kb())
            return
        if order.status != "pending":
            await edit_message_text(call, "Заказ уже обработан.")
            return

        provider = order.provider
        if provider == "cryptopay":
            if not _cryptopay_enabled():
                await edit_message_text(call, "Crypto Pay не настроен.")
                return
            invoice_id = order.provider_payment_id
            if not invoice_id:
                await edit_message_text(call, "Счет не найден.")
                return
            cryptopay_token = getattr(settings, "cryptopay_token", None)
            client = CryptoPayClient(cryptopay_token)
            invoice = await client.get_invoice(int(invoice_id))
            try:
                invoice = await client.get_invoice(int(invoice_id))
            except Exception:
                logger.exception("Failed to fetch CryptoPay invoice %s", invoice_id)
                await edit_message_text(call,"Не удалось проверить оплату. Попробуйте позже.", show_alert=True)
                return
            if not invoice or not is_cryptopay_paid(invoice.status):
                await edit_message_text(call,"Оплата еще не подтверждена.", show_alert=True)
                return
            order.raw_provider_payload = json.dumps(invoice.raw, ensure_ascii=False)
        elif provider == "yookassa":
            if not _yookassa_enabled():
                await edit_message_text(call,"YooKassa не настроена.", show_alert=True)
                return
            payment_id = order.provider_payment_id
            if not payment_id:
                await edit_message_text(call,"Платеж не найден.", show_alert=True)
                return
            shop_id = getattr(settings, "yookassa_shop_id", None)
            secret_key = getattr(settings, "yookassa_secret_key", None)
            client = YooKassaClient(shop_id, secret_key)
            try:
                payment = await client.get_payment(str(payment_id))
            except Exception:
                logger.exception("Failed to fetch YooKassa payment %s", payment_id)
                await edit_message_text(call,"Не удалось проверить оплату. Попробуйте позже.", show_alert=True)
                return
            if not is_yookassa_paid(payment.status):
                await edit_message_text(call,"Оплата еще не подтверждена.", show_alert=True)
                return
            order.raw_provider_payload = json.dumps(payment.raw, ensure_ascii=False)
        else:
            await edit_message_text(call,"Автоплатеж для заказа не настроен.", show_alert=True)
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



@router.callback_query(F.data.startswith("paid:"))
async def cb_paid(call: CallbackQuery, bot: Bot) -> None:
    await safe_answer_callback(call)
    order_id = int(call.data.split(":", 1)[1])
    async with session_scope() as session:
        order = await get_order(session, order_id)
        if not order:
            await edit_message_text(call, "Заказ не найден.")
            return
        if order.user_id != (
            await ensure_user(session=session, tg_user=call.from_user)
        ).id:
            await edit_message_text(call,"Это не ваш заказ", show_alert=True)
            return
        if order.status != "pending":
            await edit_message_text(call, "Заказ уже обработан.")
            return
        if order.payment_method != "manual" or not settings.payment_manual_enabled:
            await edit_message_text(call,"Этот способ оплаты обрабатывается автоматически.", show_alert=True)
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



@router.callback_query(F.data.startswith("cancel_order:"))
async def cb_cancel_order(call: CallbackQuery) -> None:
    await safe_answer_callback(call)
    order_id = int(call.data.split(":", 1)[1])
    async with session_scope() as session:
        order = await get_order(session, order_id)
        if not order:
            await edit_message_text(call,"Не найдено", show_alert=True)
            return
        if order.user_id != (
            await ensure_user(session=session, tg_user=call.from_user)
        ).id:
            await edit_message_text(call,"Это не ваш заказ", show_alert=True)
            return
        if order.status != "pending":
            await edit_message_text(call,"Уже обработан", show_alert=True)
            return
        order.status = "canceled"
        session.add(order)
        await session.commit()
    await edit_message_text(call, f"❌ Заказ #{order_id} отменён.", reply_markup=order_canceled_kb())



@router.callback_query(F.data.startswith("stars:"))
async def cb_stars_pay(call: CallbackQuery, bot: Bot) -> None:
    await safe_answer_callback(call)
    if not _stars_enabled():
        await edit_message_text(call,"Stars не настроены.", show_alert=True)
        return
    order_id = int(call.data.split(":")[1])

    async with session_scope() as session:
        order = await get_order(session, order_id)
        if not order or order.user_id is None:
            await edit_message_text(call,"Заказ не найден", show_alert=True)
            return

        # защита: заказ должен принадлежать пользователю
        user = await ensure_user(session=session, tg_user=call.from_user)
        if order.user_id != user.id:
            await edit_message_text(call,"Это не ваш заказ", show_alert=True)
            return

        if order.status != "pending":
            await edit_message_text(call,f"Нельзя оплатить: статус {order.status}", show_alert=True)
            return

        plan = get_plan_option(order.plan_code, int(order.months))
        stars_amount = _stars_price(plan.code, plan.months, order.amount_rub)

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
        description=f"{plan.name} на {plan.months} {months_title(plan.months, short=True)}. "
        f"К оплате: {stars_amount} ⭐",
        payload=payload,
        currency="XTR",
        prices=[LabeledPrice(label="Подписка", amount=stars_amount)],
        provider_token=None,  # важно: не пустая строка
    )



@router.pre_checkout_query()
async def stars_pre_checkout(pre: PreCheckoutQuery) -> None:
    await safe_answer_callback(call)
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
    await safe_answer_callback(call)
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
        api_prefix=settings.marzban_api_prefix,
    )

    async with session_scope() as session:
        order = await get_order(session, order_id)
        if not order:
            await message.answer("Оплата получена, но заказ не найден. Напишите в поддержку.")
            return

        # еще раз защита по владельцу
        user = await ensure_user(session=session, tg_user=message.from_user)
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
