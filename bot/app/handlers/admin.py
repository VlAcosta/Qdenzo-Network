from __future__ import annotations

import time
from datetime import timedelta

import httpx
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from loguru import logger

from ..config import settings
from ..db import session_scope
from ..keyboards.admin import (
    admin_back_kb,
    admin_kb,
    admin_order_detail_kb,
    admin_payments_kb,
    admin_pending_list_kb,
    admin_plan_apply_kb,
    admin_plan_groups_kb,
    admin_plan_options_kb,
    admin_subs_kb,
    admin_user_actions_kb,
    admin_user_confirm_kb,
)
from ..marzban.client import MarzbanClient, MarzbanError
from ..models import Order, Subscription, User
from ..services.admin import (
    find_user,
    get_dashboard_stats,
    get_plan_distribution,
    get_user_devices,
    get_user_orders,
    list_expiring_subscriptions,
    list_pending_orders_older_than,
    list_recent_orders,
)
from ..services.catalog import get_plan_option, list_paid_plans, list_plan_options_by_code, plan_title
from ..services.devices import enforce_device_limit, sync_devices_expire
from ..services.orders import get_order, mark_order_paid
from ..services.payments import (
    CryptoPayClient,
    YooKassaClient,
    is_cryptopay_paid,
    is_yookassa_paid,
)
from ..services.subscriptions import get_or_create_subscription, is_active, now_utc
from ..utils.telegram import edit_message_text
from ..utils.text import fmt_dt, h

router = Router()


class AdminStates(StatesGroup):
    user_search = State()


def _ensure_admin(tg_id: int) -> bool:
    return tg_id in settings.admin_id_list


def _mask_secret(value: str | None) -> str:
    if not value:
        return "—"
    if len(value) <= 6:
        return "***"
    return value[:3] + "***" + value[-2:]


async def _render_admin_menu(event: CallbackQuery | Message) -> None:
    text = "<b>🛠 Admin</b>\n\nВыберите действие:"
    if isinstance(event, CallbackQuery):
        await edit_message_text(event, text, reply_markup=admin_kb())
        await event.answer()
    else:
        await event.answer(text, reply_markup=admin_kb())


async def _admin_access_denied(event: CallbackQuery | Message) -> None:
    if isinstance(event, CallbackQuery):
        await event.answer("Нет доступа", show_alert=True)
        return
    await event.answer("Нет доступа")


def _marzban_client() -> MarzbanClient:
    return MarzbanClient(
        base_url=str(settings.marzban_base_url),
        username=settings.marzban_username,
        password=settings.marzban_password,
        verify_ssl=settings.marzban_verify_ssl,
    )



@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    if not _ensure_admin(message.from_user.id):
        await _admin_access_denied(message)
        return
    await _render_admin_menu(message)


@router.callback_query(F.data.in_({"admin", "admin:menu"}))
async def cb_admin(call: CallbackQuery) -> None:
    if not _ensure_admin(call.from_user.id):
        await _admin_access_denied(call)
        return
    await _render_admin_menu(call)


@router.callback_query(F.data == "admin:dashboard")
async def cb_admin_dashboard(call: CallbackQuery) -> None:
    if not _ensure_admin(call.from_user.id):
        await _admin_access_denied(call)
        return
    try:
        async with session_scope() as session:
            stats = await get_dashboard_stats(session)
            plans = await get_plan_distribution(session)
    except Exception:
        logger.exception("Admin dashboard failed")
        await edit_message_text(call, "⚠️ Не удалось загрузить дашборд.", reply_markup=admin_back_kb())
        await call.answer()
        return

    plan_lines = [f"• {h(code)} — {count}" for code, count in plans[:5]] or ["—"]
    text = (
        "📊 <b>Дашборд</b>\n\n"
        f"👥 Пользователи: <b>{stats['total_users']}</b>\n"
        f"✅ Активные подписки: <b>{stats['active_subs']}</b>\n"
        f"🆕 Новые за 24ч: <b>{stats['new_users_24h']}</b>\n"
        f"🧾 Pending: <b>{stats['pending_orders']}</b>\n"
        f"📱 Активные устройства: <b>{stats['active_devices']}</b>\n\n"
        f"💰 Выручка 24ч: <b>{stats['revenue_24h']} ₽</b>\n"
        f"💰 Выручка 30д: <b>{stats['revenue_30d']} ₽</b>\n\n"
        "<b>Топ тарифов:</b>\n"
        + "\n".join(plan_lines)
    )
    await edit_message_text(call, text, reply_markup=admin_back_kb())
    await call.answer()

@router.callback_query(F.data == "admin:user")
async def cb_admin_user(call: CallbackQuery, state: FSMContext) -> None:
    if not _ensure_admin(call.from_user.id):
        await _admin_access_denied(call)
        return
    await state.set_state(AdminStates.user_search)
    await edit_message_text(
        call,
        "🔎 <b>Поиск пользователя</b>\n\n"
        "Введите Telegram ID или @username.",
        reply_markup=admin_back_kb(),
    )
    await call.answer()


@router.message(AdminStates.user_search)
async def msg_admin_user_search(message: Message, state: FSMContext) -> None:
    if not _ensure_admin(message.from_user.id):
        await _admin_access_denied(message)
        return
    query = (message.text or "").strip()
    if not query:
        await message.answer("Введите Telegram ID или @username.", reply_markup=admin_back_kb())
        return
    async with session_scope() as session:
        user = await find_user(session, query)
        if not user:
            await message.answer("Пользователь не найден.", reply_markup=admin_back_kb())
            return
        sub = await get_or_create_subscription(session, user.id)
        devices = await get_user_devices(session, user.id)
        orders = await get_user_orders(session, user.id)

    status = "активна" if is_active(sub) else "не активна"
    device_lines = [
        f"• {h(d.label or d.device_type)} — {h(d.status)} — {fmt_dt(d.created_at)}"
        for d in devices
    ] or ["—"]
    order_lines = [
        f"• #{o.id} — {o.amount or o.amount_rub} {h(o.currency)} — {h(o.provider)} — {h(o.status)} — {fmt_dt(o.created_at)}"
        for o in orders
    ] or ["—"]


    text = (
        "👤 <b>Карточка пользователя</b>\n\n"
        f"ID: <code>{user.tg_id}</code>\n"
        f"Username: @{h(user.username) if user.username else '—'}\n"
        f"Создан: {fmt_dt(user.created_at)}\n\n"
        f"Подписка: <b>{h(sub.plan_code.upper())}</b> ({status})\n"
        f"Действует до: <b>{fmt_dt(sub.expires_at)}</b>\n\n"
        "<b>Устройства:</b>\n"
        + "\n".join(device_lines)
        + "\n\n<b>Последние заказы:</b>\n"
        + "\n".join(order_lines)
    )
    await state.clear()
    await message.answer(
        text,
        reply_markup=admin_user_actions_kb(user.id, is_enabled=is_active(sub)),
    )


@router.callback_query(F.data.startswith("admin:user:extend:"))
async def cb_admin_user_extend(call: CallbackQuery) -> None:
    if not _ensure_admin(call.from_user.id):
        await _admin_access_denied(call)
        return
    _, _, _, user_id_s, days_s = call.data.split(":")
    user_id = int(user_id_s)
    days = int(days_s)
    async with session_scope() as session:
        user = await session.get(User, user_id)
        if not user:
            await call.answer("Пользователь не найден", show_alert=True)
            return
        sub = await get_or_create_subscription(session, user.id)
        start_from = sub.expires_at if is_active(sub) and sub.expires_at else now_utc()
        sub.expires_at = start_from + timedelta(days=days)
        session.add(sub)
        await session.commit()
        await session.refresh(sub)

        marz = _marzban_client()
        try:
            await sync_devices_expire(
                session=session,
                marz=marz,
                user_id=user.id,
                expire_ts=int(sub.expires_at.timestamp()),
            )
        except MarzbanError as exc:
            logger.warning("Admin extend: Marzban update failed for user %s: %s", user.tg_id, exc)
        finally:
            await marz.close()

    await call.answer(f"✅ Продлено на {days} дн.")


@router.callback_query(F.data.startswith("admin:user:plan:"))
async def cb_admin_user_plan(call: CallbackQuery) -> None:
    if not _ensure_admin(call.from_user.id):
        await _admin_access_denied(call)
        return
    user_id = int(call.data.split(":")[-1])
    async with session_scope() as session:
        sub = await get_or_create_subscription(session, user_id)
    codes = [code for code in list_paid_plans() if code != sub.plan_code]
    text = "🛠 <b>Смена тарифа</b>\n\nВыберите новый тариф:"
    await edit_message_text(
        call,
        text,
        reply_markup=admin_plan_groups_kb(user_id, codes, back_cb="admin:user"),
    )
    await call.answer()


@router.callback_query(F.data.startswith("admin:plan_group:"))
async def cb_admin_plan_group(call: CallbackQuery) -> None:
    if not _ensure_admin(call.from_user.id):
        await _admin_access_denied(call)
        return
    _, _, user_id_s, code = call.data.split(":")
    user_id = int(user_id_s)
    options = list_plan_options_by_code(code)
    if not options:
        await call.answer("Тариф не найден", show_alert=True)
        return
    text = f"Выберите период для тарифа <b>{h(plan_title(code))}</b>:"
    await edit_message_text(
        call,
        text,
        reply_markup=admin_plan_options_kb(user_id, options, back_cb=f"admin:user:plan:{user_id}"),
    )
    await call.answer()


@router.callback_query(F.data.startswith("admin:plan_option:"))
async def cb_admin_plan_option(call: CallbackQuery) -> None:
    if not _ensure_admin(call.from_user.id):
        await _admin_access_denied(call)
        return
    _, _, user_id_s, plan_code, months_s = call.data.split(":")
    user_id = int(user_id_s)
    months = int(months_s)
    text = (
        f"Тариф: <b>{h(plan_title(plan_code))}</b>\n"
        f"Период: <b>{months} мес</b>\n\n"
        "Как применить тариф?"
    )
    await edit_message_text(
        call,
        text,
        reply_markup=admin_plan_apply_kb(
            user_id,
            plan_code,
            months,
            back_cb=f"admin:plan_group:{user_id}:{plan_code}",
        ),
    )
    await call.answer()

@router.callback_query(F.data.startswith("admin:plan_apply:"))
async def cb_admin_plan_apply(call: CallbackQuery) -> None:
    if not _ensure_admin(call.from_user.id):
        await _admin_access_denied(call)
        return
    _, _, user_id_s, plan_code, months_s, mode = call.data.split(":")
    user_id = int(user_id_s)
    months = int(months_s)
    opt = get_plan_option(plan_code, months)
    async with session_scope() as session:
        user = await session.get(User, user_id)
        if not user:
            await call.answer("Пользователь не найден", show_alert=True)
            return
        sub = await get_or_create_subscription(session, user.id)
        if mode == "now":
            sub.plan_code = opt.code
            sub.devices_limit = opt.devices_limit
            sub.started_at = now_utc()
            sub.expires_at = now_utc() + timedelta(days=opt.duration_days)
            session.add(sub)
            await session.commit()
            await session.refresh(sub)
        else:
            new_expires = await _apply_plan_from_expiry(session, user, opt)
            sub.expires_at = new_expires

        marz = _marzban_client()
        try:
            await sync_devices_expire(
                session=session,
                marz=marz,
                user_id=user.id,
                expire_ts=int(sub.expires_at.timestamp()) if sub.expires_at else 0,
            )
            await enforce_device_limit(
                session=session,
                marz=marz,
                user_id=user.id,
                limit=opt.devices_limit,
            )
        except MarzbanError as exc:
            logger.warning("Admin plan apply Marzban error for user %s: %s", user.tg_id, exc)
        finally:
            await marz.close()

    await call.answer("✅ Тариф обновлён.")


async def _apply_plan_from_expiry(session, user: User, opt) -> datetime:
    start_from = now_utc()
    sub = await get_or_create_subscription(session, user.id)
    if is_active(sub) and sub.expires_at:
        start_from = sub.expires_at
    sub.plan_code = opt.code
    sub.devices_limit = opt.devices_limit
    sub.expires_at = start_from + timedelta(days=opt.duration_days)
    if not sub.started_at or not is_active(sub):
        sub.started_at = now_utc()
    session.add(sub)
    await session.commit()
    await session.refresh(sub)
    return sub.expires_at


@router.callback_query(F.data.startswith("admin:user:disable:"))
async def cb_admin_user_disable(call: CallbackQuery) -> None:
    if not _ensure_admin(call.from_user.id):
        await _admin_access_denied(call)
        return
    user_id = int(call.data.split(":")[-1])
    await edit_message_text(
        call,
        "⏸ Отключить доступ пользователю в Marzban?",
        reply_markup=admin_user_confirm_kb(user_id, action="disable", back_cb="admin:user"),
    )
    await call.answer()


@router.callback_query(F.data.startswith("admin:user:enable:"))
async def cb_admin_user_enable(call: CallbackQuery) -> None:
    if not _ensure_admin(call.from_user.id):
        await _admin_access_denied(call)
        return
    user_id = int(call.data.split(":")[-1])
    await edit_message_text(
        call,
        "▶️ Включить доступ пользователю в Marzban?",
        reply_markup=admin_user_confirm_kb(user_id, action="enable", back_cb="admin:user"),
    )
    await call.answer()


@router.callback_query(F.data.startswith("admin:user:disable:confirm:"))
async def cb_admin_user_disable_confirm(call: CallbackQuery) -> None:
    if not _ensure_admin(call.from_user.id):
        await _admin_access_denied(call)
        return
    user_id = int(call.data.split(":")[-1])
    async with session_scope() as session:
        user = await session.get(User, user_id)
        if not user:
            await call.answer("Пользователь не найден", show_alert=True)
            return
        devices = await get_user_devices(session, user.id)
        marz = _marzban_client()
        try:
            for device in devices:
                if device.status != "deleted":
                    device.status = "disabled"
                    session.add(device)
            await session.commit()
            for device in devices:
                if device.status != "deleted" and device.marzban_username:
                    try:
                        await marz.update_user(device.marzban_username, status="disabled")
                    except Exception:
                        continue
        except Exception as exc:
            logger.warning("Admin disable failed for user %s: %s", user.tg_id, exc)
        finally:
            await marz.close()

    await call.answer("✅ Доступ отключён.")


@router.callback_query(F.data.startswith("admin:user:enable:confirm:"))
async def cb_admin_user_enable_confirm(call: CallbackQuery) -> None:
    if not _ensure_admin(call.from_user.id):
        await _admin_access_denied(call)
        return
        user_id = int(call.data.split(":")[-1])
    async with session_scope() as session:
        user = await session.get(User, user_id)
        if not user:
            await call.answer("Пользователь не найден", show_alert=True)
            return
        sub = await get_or_create_subscription(session, user.id)
        if not is_active(sub):
            await call.answer("Подписка не активна. Сначала продлите.", show_alert=True)
            return
        devices = await get_user_devices(session, user.id)
        marz = _marzban_client()
        try:
            for device in devices:
                if device.status != "deleted":
                    device.status = "active"
                    session.add(device)
            await session.commit()
            for device in devices:
                if device.status != "deleted" and device.marzban_username:
                    try:
                        await marz.update_user(device.marzban_username, status="active")
                    except Exception:
                        continue
        except Exception as exc:
            logger.warning("Admin enable failed for user %s: %s", user.tg_id, exc)
        finally:
            await marz.close()

    await call.answer("✅ Доступ включён.")


@router.callback_query(F.data.startswith("admin:payments"))
async def cb_admin_payments(call: CallbackQuery) -> None:
    if not _ensure_admin(call.from_user.id):
        await _admin_access_denied(call)
        return
    parts = call.data.split(":")
    status = None
    if len(parts) == 4:
        status = parts[-1]
    try:
        async with session_scope() as session:
            orders = await list_recent_orders(session, status=status, limit=20)
    except Exception:
        logger.exception("Admin payments failed")
        await edit_message_text(call, "⚠️ Не удалось загрузить платежи.", reply_markup=admin_back_kb())
        await call.answer()
        return

    if not orders:
        await edit_message_text(
            call,
            "💳 <b>Платежи</b>\n\nЗаписей пока нет.",
            reply_markup=admin_back_kb(),
        )
        await call.answer()
        return

    lines = ["💳 <b>Платежи</b>\n"]
    for o in orders:
        lines.append(
            f"• #{o.id} — {o.amount or o.amount_rub} {h(o.currency)} — "
            f"{h(o.provider)} — {h(o.status)} — user {o.user_id}"
        )
    text = "\n".join(lines)
    await edit_message_text(call, text, reply_markup=admin_payments_kb(orders))
    await call.answer()



@router.callback_query(F.data.regexp(r"^admin:order:\d+$"))
async def cb_admin_order_detail(call: CallbackQuery) -> None:
    if not _ensure_admin(call.from_user.id):
        await _admin_access_denied(call)
        return
    _, _, order_id_s = call.data.split(":")
    order_id = int(order_id_s)
    async with session_scope() as session:
        order = await get_order(session, order_id)
    if not order:
        await call.answer("Заказ не найден", show_alert=True)
        return
    text = (
        f"🧾 <b>Заказ #{order.id}</b>\n\n"
        f"Пользователь: {order.user_id}\n"
        f"Сумма: {order.amount or order.amount_rub} {h(order.currency)}\n"
        f"Провайдер: {h(order.provider)}\n"
        f"Статус: {h(order.status)}\n"
        f"Создан: {fmt_dt(order.created_at)}\n"
        f"Оплачен: {fmt_dt(order.paid_at)}"
    )
    show_check = order.status == "pending" and order.provider in {"yookassa", "cryptopay"}
    show_cancel = order.status == "pending"
    await edit_message_text(
        call,
        text,
        reply_markup=admin_order_detail_kb(
            order.id,
            show_check=show_check,
            show_cancel=show_cancel,
            back_cb="admin:payments",
        ),
    )
    await call.answer()


@router.callback_query(F.data.startswith("admin:order:check:"))
async def cb_admin_order_check(call: CallbackQuery) -> None:
    if not _ensure_admin(call.from_user.id):
        await _admin_access_denied(call)
        return
    order_id = int(call.data.split(":")[-1])
    async with session_scope() as session:
        order = await get_order(session, order_id)
        if not order or order.status != "pending":
            await call.answer("Заказ не найден или уже обработан", show_alert=True)
            return


        if not order.provider_payment_id:
            await call.answer("Платеж не найден", show_alert=True)
            return
        if order.provider == "yookassa":
            if not (settings.yookassa_shop_id and settings.yookassa_secret_key):
                await call.answer("YooKassa не настроена", show_alert=True)
                return
            client = YooKassaClient(settings.yookassa_shop_id, settings.yookassa_secret_key)
            try:
                payment = await client.get_payment(order.provider_payment_id)
            except Exception:
                logger.exception("Admin check YooKassa failed for order %s", order_id)
                await call.answer("Не удалось проверить оплату", show_alert=True)
                return
            if not is_yookassa_paid(payment.status):
                await call.answer("Оплата еще не подтверждена", show_alert=True)
                return
        elif order.provider == "cryptopay":
            if not settings.cryptopay_token:
                await call.answer("CryptoPay не настроен", show_alert=True)
                return
            client = CryptoPayClient(settings.cryptopay_token)
            try:
                invoice = await client.get_invoice(int(order.provider_payment_id))
            except Exception:
                logger.exception("Admin check CryptoPay failed for order %s", order_id)
                await call.answer("Не удалось проверить оплату", show_alert=True)
                return
            if not invoice or not is_cryptopay_paid(invoice.status):
                await call.answer("Оплата еще не подтверждена", show_alert=True)
                return
        else:
            await call.answer("Провайдер не поддерживает проверку", show_alert=True)
            return

        marz = _marzban_client()
        try:
            await mark_order_paid(session=session, marz=marz, order=order)
        except MarzbanError as exc:
            logger.warning("Admin check: Marzban error for order %s: %s", order_id, exc)
            await call.answer("Оплата подтверждена, но Marzban недоступен.", show_alert=True)
            return
        finally:
            await marz.close()

    await call.answer("✅ Оплата подтверждена")


@router.callback_query(F.data.startswith("admin:order:cancel:"))
async def cb_admin_order_cancel(call: CallbackQuery) -> None:
    if not _ensure_admin(call.from_user.id):
        await _admin_access_denied(call)
        return
    order_id = int(call.data.split(":")[-1])

    async with session_scope() as session:
        order = await get_order(session, order_id)
        if not order:
            await call.answer("Заказ не найден", show_alert=True)
            return
        if order.status != "pending":
            await call.answer("Нельзя отменить", show_alert=True)
            return
        order.status = "canceled"
        session.add(order)
        await session.commit()
    await call.answer("❌ Заказ отменен")


@router.callback_query(F.data == "admin:subs")
async def cb_admin_subs(call: CallbackQuery) -> None:
    if not _ensure_admin(call.from_user.id):
        await _admin_access_denied(call)
        return
    try:
        async with session_scope() as session:
            exp_1 = await list_expiring_subscriptions(session, within_days=1)
            exp_3 = await list_expiring_subscriptions(session, within_days=3)
            exp_7 = await list_expiring_subscriptions(session, within_days=7)
    except Exception:
        logger.exception("Admin subscriptions failed")
        await edit_message_text(call, "⚠️ Не удалось загрузить подписки.", reply_markup=admin_back_kb())
        await call.answer()
        return

    def _render_block(title: str, items: list[tuple[Subscription, User]]) -> list[str]:
        lines = [f"<b>{title}</b>"]
        if not items:
            lines.append("—")
            return lines
        for sub, user in items:
            lines.append(
                f"• <code>{user.tg_id}</code> — {h(sub.plan_code)} — до {fmt_dt(sub.expires_at)}"
            )
        return lines

    text = (
        "📦 <b>Подписки (истекают)</b>\n\n"
        + "\n".join(_render_block("≤ 1 день", exp_1))
        + "\n\n"
        + "\n".join(_render_block("≤ 3 дня", exp_3))
        + "\n\n"
        + "\n".join(_render_block("≤ 7 дней", exp_7))
    )
    user_ids = list({user.id for _, user in exp_1 + exp_3 + exp_7})[:10]
    reply_markup = admin_subs_kb(user_ids) if user_ids else admin_back_kb()
    await edit_message_text(call, text, reply_markup=reply_markup)
    await call.answer()


@router.callback_query(F.data.startswith("admin:subs:msg:"))
async def cb_admin_subs_msg(call: CallbackQuery) -> None:
    if not _ensure_admin(call.from_user.id):
        await _admin_access_denied(call)
        return
    user_id = int(call.data.split(":")[-1])
    async with session_scope() as session:
        user = await session.get(User, user_id)
        if not user:
            await call.answer("Пользователь не найден", show_alert=True)
            return
        sub = await get_or_create_subscription(session, user.id)
    text = (
        "⚠️ Ваша подписка скоро закончится.\n"
        f"Тариф: {h(sub.plan_code.upper())}\n"
        f"Действует до: {fmt_dt(sub.expires_at)}\n\n"
        "Продлите подписку, чтобы сохранить доступ."
    )
    try:
        await call.bot.send_message(user.tg_id, text)
    except Exception:
        await call.answer("Не удалось отправить сообщение", show_alert=True)
        return
    await call.answer("✅ Сообщение отправлено")


@router.callback_query(F.data.startswith("admin:subs:extend:"))
async def cb_admin_subs_extend(call: CallbackQuery) -> None:
    if not _ensure_admin(call.from_user.id):
        await _admin_access_denied(call)
        return
    _, _, user_id_s, days_s = call.data.split(":")
    user_id = int(user_id_s)
    days = int(days_s)
    async with session_scope() as session:
        user = await session.get(User, user_id)
        if not user:
            await call.answer("Пользователь не найден", show_alert=True)
            return
        
        sub = await get_or_create_subscription(session, user.id)
        start_from = sub.expires_at if is_active(sub) and sub.expires_at else now_utc()
        sub.expires_at = start_from + timedelta(days=days)
        session.add(sub)
        await session.commit()
        await session.refresh(sub)
        marz = _marzban_client()
        try:
            await sync_devices_expire(
                session=session,
                marz=marz,
                user_id=user.id,
                expire_ts=int(sub.expires_at.timestamp()),
            )
        except MarzbanError as exc:
            logger.warning("Admin subs extend: Marzban error for user %s: %s", user.tg_id, exc)
        finally:
            await marz.close()
    await call.answer(f"✅ Продлено на {days} дн.")


@router.callback_query(F.data == "admin:traffic")
async def cb_admin_traffic(call: CallbackQuery) -> None:
    if not _ensure_admin(call.from_user.id):
        await _admin_access_denied(call)
        return
    text = (
        "📈 <b>Трафик</b>\n\n"
        "Данные будут доступны после настройки сбора статистики.\n"
        "Подсказка: подключите сбор трафика через Marzban API и периодический job."
    )
    await edit_message_text(call, text, reply_markup=admin_back_kb())
    await call.answer()


@router.callback_query(F.data == "admin:quality")
async def cb_admin_quality(call: CallbackQuery) -> None:
    if not _ensure_admin(call.from_user.id):
        await _admin_access_denied(call)
        return

    marz_status = "FAIL"
    happ_status = "FAIL"
    yk_status = "FAIL"
    marz_latency_ms = None
    happ_latency_ms = None

    marz = _marzban_client()
    start = time.monotonic()
    try:
        await marz.get_user("healthcheck")
        marz_status = "OK"
    except MarzbanError as exc:
        marz_status = f"FAIL ({exc})"
    except Exception as exc:
        marz_status = f"FAIL ({exc})"
    finally:
        marz_latency_ms = int((time.monotonic() - start) * 1000)
        await marz.close()

    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.post("https://crypto.happ.su/api.php", json={"url": "https://example.com"})
        resp.raise_for_status()
        data = resp.json()
        if data.get("url") or data.get("result") or data.get("link"):
            happ_status = "OK"
        else:
            happ_status = "FAIL (bad response)"
    except Exception as exc:
        happ_status = f"FAIL ({exc})"
    finally:
        happ_latency_ms = int((time.monotonic() - start) * 1000)

    if settings.yookassa_shop_id and settings.yookassa_secret_key:
        yk_status = "OK (ключи заданы)"

    text = (
        "🧪 <b>Качество</b>\n\n"
        f"Marzban API: <b>{h(marz_status)}</b> ({marz_latency_ms} ms)\n"
        f"Happ crypto: <b>{h(happ_status)}</b> ({happ_latency_ms} ms)\n"
        f"YooKassa: <b>{h(yk_status)}</b>\n"
    )
    await edit_message_text(call, text, reply_markup=admin_back_kb())
    await call.answer()


@router.callback_query(F.data == "admin:settings")
async def cb_admin_settings(call: CallbackQuery) -> None:
    if not _ensure_admin(call.from_user.id):
        await _admin_access_denied(call)
        return
    yookassa_enabled = bool(settings.yookassa_shop_id and settings.yookassa_secret_key)
    cryptopay_enabled = bool(settings.cryptopay_token)
    text = (
        "⚙️ <b>Настройки</b>\n\n"
        f"Manual payments: <b>{'ON' if settings.payment_manual_enabled else 'OFF'}</b>\n"
        f"Stars enabled: <b>{'ON' if settings.tg_stars_enabled else 'OFF'}</b>\n"
        f"YooKassa enabled: <b>{'ON' if yookassa_enabled else 'OFF'}</b>\n"
        f"CryptoPay enabled: <b>{'ON' if cryptopay_enabled else 'OFF'}</b>\n\n"
        f"Marzban URL: <code>{h(settings.marzban_base_url)}</code>\n"
        f"Marzban verify SSL: <b>{'ON' if settings.marzban_verify_ssl else 'OFF'}</b>\n\n"
        f"YOOKASSA_SHOP_ID: {_mask_secret(settings.yookassa_shop_id)}\n"
        f"CRYPTOPAY_TOKEN: {_mask_secret(settings.cryptopay_token)}\n"
    )
    await edit_message_text(call, text, reply_markup=admin_back_kb())
    await call.answer()


@router.callback_query(F.data == "admin:pending")
async def cb_admin_pending(call: CallbackQuery) -> None:
    if not _ensure_admin(call.from_user.id):
        await _admin_access_denied(call)
        return
    try:
        async with session_scope() as session:
            orders = await list_pending_orders_older_than(session, older_than=timedelta(minutes=30))
    except Exception:
        logger.exception("Admin pending failed")
        await edit_message_text(call, "⚠️ Не удалось загрузить список.", reply_markup=admin_back_kb())
        await call.answer()
        return


    if not orders:
        await edit_message_text(call, "✅ Нет ожидающих оплат.", reply_markup=admin_back_kb())
        await call.answer()
        return

    lines = ["🧾 <b>Ожидают оплаты</b>\n"]
    for o in orders:
        lines.append(
            f"• #{o.id} — {h(o.plan_code)} {o.months}м — {o.amount_rub}₽ — {h(o.provider)} — {fmt_dt(o.created_at)}"
        )
    await edit_message_text(call, "\n".join(lines), reply_markup=admin_pending_list_kb(orders))
    await call.answer()


@router.callback_query(F.data.startswith("admin:pending:check:"))
async def cb_admin_pending_check(call: CallbackQuery) -> None:
    if not _ensure_admin(call.from_user.id):
        await _admin_access_denied(call)
        return

    order_id = int(call.data.split(":")[-1])
    async with session_scope() as session:
        order = await get_order(session, order_id)
        if not order:
            await call.answer("Заказ не найден", show_alert=True)
            return
        if order.provider not in {"yookassa", "cryptopay"}:
            await call.answer("Провайдер не поддерживает проверку", show_alert=True)
            return
        if order.status != "pending":
            await call.answer("Заказ уже обработан", show_alert=True)
            return

        if not order.provider_payment_id:
            await call.answer("Платеж не найден", show_alert=True)
            return
        if order.provider == "yookassa":
            if not (settings.yookassa_shop_id and settings.yookassa_secret_key):
                await call.answer("YooKassa не настроена", show_alert=True)
                return
            client = YooKassaClient(settings.yookassa_shop_id, settings.yookassa_secret_key)
            payment = await client.get_payment(order.provider_payment_id)
            if not is_yookassa_paid(payment.status):
                await call.answer("Оплата еще не подтверждена", show_alert=True)
                return
        else:
            if not settings.cryptopay_token:
                await call.answer("CryptoPay не настроен", show_alert=True)
                return
            client = CryptoPayClient(settings.cryptopay_token)
            invoice = await client.get_invoice(int(order.provider_payment_id))
            if not invoice or not is_cryptopay_paid(invoice.status):
                await call.answer("Оплата еще не подтверждена", show_alert=True)
                return

        marz = _marzban_client()
        try:
            await mark_order_paid(session=session, marz=marz, order=order)
        except MarzbanError as exc:
            logger.warning("Admin pending check: Marzban error for order %s: %s", order_id, exc)
            await call.answer("Оплата подтверждена, но Marzban недоступен.", show_alert=True)
            return
        finally:
            await marz.close()

    await call.answer("✅ Оплата подтверждена")


@router.callback_query(F.data.startswith("admin:pending:cancel:"))
async def cb_admin_pending_cancel(call: CallbackQuery) -> None:
    if not _ensure_admin(call.from_user.id):
        await _admin_access_denied(call)
        return
    order_id = int(call.data.split(":")[-1])
    async with session_scope() as session:
        order = await get_order(session, order_id)
        if not order:
            await call.answer("Заказ не найден", show_alert=True)
            return
        if order.status != "pending":
            await call.answer("Заказ уже обработан", show_alert=True)
            return
        order.status = "canceled"
        session.add(order)
        await session.commit()
    await call.answer("❌ Заказ отменён")
